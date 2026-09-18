"""Stage 1: fetch Esri World Imagery XYZ tiles covering the AOI and mosaic them.

The endpoint orders its path as {z}/{y}/{x}, not the usual {z}/{x}/{y}.
A swapped mosaic looks plausible but is geographically scrambled.
"""

from __future__ import annotations

import io
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
import requests
from PIL import Image
from shapely.geometry import Polygon

from .. import config
from . import geo
from .errors import PipelineError
from .ingest import Scene


def tile_url(z: int, x: int, y: int) -> str:
    return config.TILE_URL_TEMPLATE.format(z=z, x=x, y=y)


def tile_range(aoi: Polygon, zoom: int) -> tuple[int, int, int, int]:
    minx, miny, maxx, maxy = aoi.bounds
    x0, y0 = geo.lonlat_to_tile(minx, maxy, zoom)  # top-left
    x1, y1 = geo.lonlat_to_tile(maxx, miny, zoom)  # bottom-right
    return x0, y0, x1, y1


def _fetch_one(z: int, x: int, y: int) -> np.ndarray:
    cache = config.TILE_CACHE_DIR / f"{z}_{x}_{y}.jpg"
    if cache.exists():
        data = cache.read_bytes()
    else:
        url = tile_url(z, x, y)
        last_exc: Exception | None = None
        data = None
        for attempt in range(config.TILE_RETRIES + 1):
            try:
                r = requests.get(url, timeout=config.TILE_TIMEOUT_S, headers={"User-Agent": config.TILE_USER_AGENT})
                if r.status_code == 200 and r.content:
                    data = r.content
                    break
                last_exc = RuntimeError(f"HTTP {r.status_code}")
            except requests.RequestException as exc:
                last_exc = exc
            if attempt < config.TILE_RETRIES:
                time.sleep(0.5 * (2**attempt))
        if data is None:
            raise PipelineError(
                "tile_fetch_failed",
                f"Could not download imagery tile z={z} x={x} y={y} after {config.TILE_RETRIES + 1} attempts ({last_exc}). "
                "The job was stopped rather than analysing an image with holes in it. Please try again in a minute.",
            )
        cache.write_bytes(data)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    if img.size != (geo.TILE_SIZE, geo.TILE_SIZE):
        raise PipelineError("tile_bad_size", f"Imagery tile z={z} x={x} y={y} had unexpected size {img.size}.")
    return np.asarray(img, dtype=np.uint8)


PLACEHOLDER_GREY = 204  # Esri's flat "Map data not yet available" tile


def placeholder_fraction(rgb: np.ndarray) -> float:
    """Share of 256 px tiles that are Esri's grey no-data placeholder (it is served with HTTP 200)."""
    a = rgb if rgb.dtype == np.uint8 else (np.clip(rgb, 0, 1) * 255)
    ts = geo.TILE_SIZE
    h, w = a.shape[:2]
    blocks = [a[r : r + ts, c : c + ts] for r in range(0, h, ts) for c in range(0, w, ts)]
    bad = sum(1 for b in blocks if b.size and abs(float(b.mean()) - PLACEHOLDER_GREY) < 6 and float(b.std()) < 12)
    return bad / max(1, len(blocks))


def scene_pixels(aoi: Polygon, zoom: int) -> int:
    """Pixels in the AOI bounding box at this zoom, before any processing."""
    minx, miny, maxx, maxy = aoi.bounds
    mx0, my1 = geo.lonlat_to_mercator(minx, maxy)
    mx1, my0 = geo.lonlat_to_mercator(maxx, miny)
    res = geo.mercator_nominal_px(zoom)
    return int(((mx1 - mx0) / res + 1) * ((my1 - my0) / res + 1))


def tile_count(aoi: Polygon, zoom: int) -> int:
    x0, y0, x1, y1 = tile_range(aoi, zoom)
    return (x1 - x0 + 1) * (y1 - y0 + 1)


def choose_zoom(aoi: Polygon, requested: int) -> int:
    """The finest zoom, at most the requested one, whose scene fits the pixel and tile budgets."""
    for z in range(requested, config.MIN_AUTO_ZOOM - 1, -1):
        if scene_pixels(aoi, z) <= config.MAX_SCENE_PX and tile_count(aoi, z) <= config.MAX_TILES:
            return z
    raise PipelineError(
        "aoi_too_large",
        f"This area needs {scene_pixels(aoi, config.MIN_AUTO_ZOOM) / 1e6:.0f} million pixels even at zoom "
        f"{config.MIN_AUTO_ZOOM}, over this server's budget of {config.MAX_SCENE_PX / 1e6:.0f} million. "
        "Split it into several projects, or raise CANOPY_MAX_SCENE_PX on a machine with more memory.",
    )


def fetch_scene(aoi: Polygon, zoom: int) -> Scene:
    x0, y0, x1, y1 = tile_range(aoi, zoom)
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    n_tiles = nx * ny
    if n_tiles > config.MAX_TILES:
        raise PipelineError(
            "too_many_tiles",
            f"This area needs {n_tiles} imagery tiles at zoom {zoom}; the limit is {config.MAX_TILES}. "
            "Please draw a smaller area or choose zoom 18.",
        )
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    jobs = [(zoom, x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    with ThreadPoolExecutor(max_workers=config.TILE_FETCH_WORKERS) as pool:
        arrays = list(pool.map(lambda a: _fetch_one(*a), jobs))

    ts = geo.TILE_SIZE
    mosaic = np.zeros((ny * ts, nx * ts, 3), dtype=np.uint8)
    for (z, x, y), arr in zip(jobs, arrays):
        r, c = (y - y0) * ts, (x - x0) * ts
        mosaic[r : r + ts, c : c + ts] = arr

    # Affine from the top-left tile origin, in EPSG:3857 units.
    res = geo.mercator_nominal_px(zoom)
    ox, oy = geo.tile_origin_mercator(x0, y0, zoom)

    # Crop to the AOI bounding box in pixel space.
    minx, miny, maxx, maxy = aoi.bounds
    mx0, my1 = geo.lonlat_to_mercator(minx, maxy)
    mx1, my0 = geo.lonlat_to_mercator(maxx, miny)
    c0 = max(0, int(np.floor((mx0 - ox) / res)))
    c1 = min(mosaic.shape[1], int(np.ceil((mx1 - ox) / res)))
    r0 = max(0, int(np.floor((oy - my1) / res)))
    r1 = min(mosaic.shape[0], int(np.ceil((oy - my0) / res)))
    crop = mosaic[r0:r1, c0:c1]
    transform = (res, 0.0, ox + c0 * res, 0.0, -res, oy - r0 * res)

    lat_c = aoi.centroid.y
    m_per_px = geo.mercator_m_per_px(lat_c, zoom)
    audit = {
        "input_type": "boundary",
        "interpreted_as": "RGB, 3 bands, uint8 (Esri World Imagery JPEG tiles)",
        "imagery_source": config.TILE_SOURCE_NAME,
        "tile_url_template": config.TILE_URL_TEMPLATE,
        "tile_zoom": zoom,
        "tile_range": {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "count": n_tiles},
        "tile_fetch_utc": fetched_at,
        "working_crs": "EPSG:3857",
        "resolution_source": "156543.03392804097 * cos(centroid latitude) / 2**zoom",
        "resolution_spread": geo.latitude_resolution_spread(aoi, zoom),
        "crop_px": {"row0": r0, "row1": r1, "col0": c0, "col1": c1},
        "band_normalization_divisors": [255.0, 255.0, 255.0],
    }
    return Scene(
        rgb=crop.astype(np.float32) / 255.0,
        nir=None,
        transform=transform,
        crs="EPSG:3857",
        m_per_px=m_per_px,
        aoi_lonlat=aoi,
        audit=audit,
    )
