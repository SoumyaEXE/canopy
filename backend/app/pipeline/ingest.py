"""Stage 0: parse GeoTIFF / KML / KMZ / GeoJSON input and validate the AOI."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field

import numpy as np
from lxml import etree
from shapely.geometry import MultiPolygon, Polygon, box, shape
from shapely.ops import unary_union
from shapely.validation import explain_validity, make_valid

from .. import config
from . import geo
from .errors import PipelineError


@dataclass
class Scene:
    """An RGB(+NIR) raster on a metric-ish pixel grid, plus everything needed to georeference it."""

    rgb: np.ndarray  # float32, HxWx3, [0, 1]
    nir: np.ndarray | None  # float32, HxW, [0, 1]
    transform: tuple  # affine (a, b, c, d, e, f): x = a*col + b*row + c, y = d*col + e*row + f
    crs: str  # e.g. "EPSG:3857" or "EPSG:32645"
    m_per_px: float  # ground metres per pixel
    aoi_lonlat: Polygon | MultiPolygon
    audit: dict = field(default_factory=dict)


@dataclass
class ParsedInput:
    kind: str  # geotiff | kml | kmz | geojson | drawn
    aoi_lonlat: Polygon | MultiPolygon | None
    raster_bytes: bytes | None
    sha256: str
    filename: str | None
    selection: list[int] | None = None


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _repair(geom):
    if geom.is_empty:
        raise PipelineError("empty_geometry", "The boundary you provided is empty. Please draw or upload an area.")
    if not geom.is_valid:
        reason = explain_validity(geom)
        fixed = make_valid(geom)
        polys = [p for g in getattr(fixed, "geoms", [fixed]) for p in getattr(g, "geoms", [g]) if isinstance(p, Polygon)]
        if not polys and "Too few points" in reason:
            raise PipelineError("too_few_points", "The boundary has too few points to enclose an area. A polygon needs at least three corners.")
        if not polys:
            raise PipelineError(
                "invalid_polygon",
                f"The boundary crosses over itself and could not be repaired ({reason}). Please redraw it.",
            )
        geom = polys[0] if len(polys) == 1 else MultiPolygon(polys)
    return geom


def _single_polygon(geom) -> Polygon:
    """A drawn boundary: exactly one enclosed area."""
    geom = _repair(geom)
    if isinstance(geom, MultiPolygon):
        if len(geom.geoms) != 1:
            raise PipelineError(
                "multipolygon",
                f"Your boundary has {len(geom.geoms)} separate parts. Please draw one area at a time.",
            )
        geom = geom.geoms[0]
    if not isinstance(geom, Polygon):
        raise PipelineError("not_polygon", "The boundary must be a polygon (an enclosed area), not a line or point.")
    return Polygon(geom.exterior.coords)  # drop holes: an AOI is outer rings only


def _area(geom) -> Polygon | MultiPolygon:
    """An uploaded area: one polygon, or several analysed together. Holes are dropped, overlaps merged."""
    geom = _repair(geom)
    parts = [p for p in getattr(geom, "geoms", [geom]) if isinstance(p, Polygon) and not p.is_empty]
    if not parts:
        raise PipelineError("not_polygon", "The boundary must be a polygon (an enclosed area), not a line or point.")
    merged = unary_union([Polygon(p.exterior.coords) for p in parts])
    outer = [Polygon(p.exterior.coords) for p in getattr(merged, "geoms", [merged]) if isinstance(p, Polygon)]
    return outer[0] if len(outer) == 1 else MultiPolygon(outer)


def validate_aoi(poly: Polygon | MultiPolygon) -> float:
    minx, miny, maxx, maxy = poly.bounds
    if not (-180 <= minx <= 180 and -180 <= maxx <= 180 and -85 <= miny <= 85 and -85 <= maxy <= 85):
        raise PipelineError(
            "bad_coordinates",
            "The boundary coordinates are not valid longitude/latitude values. Coordinates must be in WGS84 (EPSG:4326).",
        )
    area_m2 = geo.polygon_area_m2(poly)
    km2 = area_m2 / 1e6
    if km2 > config.MAX_AOI_KM2:
        raise PipelineError(
            "aoi_too_large",
            f"Your area is {km2:.2f} square kilometres; the limit on this server is {config.MAX_AOI_KM2:.0f} km². "
            "Split it into several projects, or raise CANOPY_MAX_AOI_KM2 on a machine with more memory.",
        )
    if area_m2 < 100:
        raise PipelineError("aoi_too_small", f"Your area is only {area_m2:.0f} m². Please draw an area of at least 100 m².")
    return area_m2


def tiles_needed(geom, zoom: int = 18) -> int:
    """Imagery tiles covering the bounding box: scattered areas cost their whole extent, not just their area."""
    minx, miny, maxx, maxy = geom.bounds
    x0, y0 = geo.lonlat_to_tile(minx, maxy, zoom)
    x1, y1 = geo.lonlat_to_tile(maxx, miny, zoom)
    return (x1 - x0 + 1) * (y1 - y0 + 1)


def validate_extent(geom, zoom: int = config.MIN_AUTO_ZOOM) -> None:
    n = tiles_needed(geom, zoom)
    if n > config.MAX_TILES:
        minx, miny, maxx, maxy = geom.bounds
        span_km = max(maxx - minx, maxy - miny) * 111.32
        raise PipelineError(
            "extent_too_large",
            f"The selected areas are spread over about {span_km:.1f} km and need {n} imagery tiles at zoom {zoom}; "
            f"the limit is {config.MAX_TILES}. Choose areas that sit closer together, or split them into separate projects.",
        )


@dataclass
class AreaFeature:
    index: int
    name: str | None
    geom: Polygon | MultiPolygon


def _geojson_features(obj: dict) -> list[AreaFeature]:
    t = obj.get("type")
    if t == "FeatureCollection":
        items = [(f.get("geometry"), (f.get("properties") or {})) for f in (obj.get("features") or [])]
    elif t == "Feature":
        items = [(obj.get("geometry"), obj.get("properties") or {})]
    else:
        items = [(obj, {})]
    out: list[AreaFeature] = []
    for geometry, props in items:
        if not geometry:
            continue
        try:
            geom = shape(geometry)
        except Exception as exc:  # noqa: BLE001
            raise PipelineError(
                "bad_geojson",
                "The GeoJSON polygon is malformed. Each ring needs at least four numeric [longitude, latitude] points, "
                "with the last point equal to the first.",
            ) from exc
        if geom.geom_type not in ("Polygon", "MultiPolygon") or geom.is_empty:
            continue
        name = next((str(props[k]) for k in ("name", "Name", "NAME", "title", "id", "ID") if props.get(k) not in (None, "")), None)
        out.append(AreaFeature(len(out), name, geom))
    if not out:
        raise PipelineError("bad_geojson", "No polygon was found in the GeoJSON. It must contain Polygon or MultiPolygon geometry.")
    return out


def _ring(el) -> list[tuple[float, float]]:
    pts = []
    for tok in (el.text or "").split():
        parts = tok.split(",")
        if len(parts) >= 2:
            pts.append((float(parts[0]), float(parts[1])))
    return pts


def _kml_features(data: bytes) -> list[AreaFeature]:
    try:
        root = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    except etree.XMLSyntaxError as exc:
        raise PipelineError("bad_kml", f"The KML file is not valid XML: {exc}") from exc
    out: list[AreaFeature] = []
    # One feature per Placemark; a Placemark with several polygons (MultiGeometry) stays one feature.
    placemarks = root.xpath("//*[local-name()='Placemark']") or [root]
    for pm in placemarks:
        polys = []
        for poly_el in pm.xpath(".//*[local-name()='Polygon']"):
            rings = poly_el.xpath(".//*[local-name()='outerBoundaryIs']//*[local-name()='coordinates']") or poly_el.xpath(
                ".//*[local-name()='coordinates']"
            )
            if rings:
                pts = _ring(rings[0])
                if len(pts) >= 3:
                    polys.append(Polygon(pts))
        if not polys:
            continue
        names = pm.xpath("./*[local-name()='name']/text()")
        name = names[0].strip() if names and names[0].strip() else None
        out.append(AreaFeature(len(out), name, polys[0] if len(polys) == 1 else MultiPolygon(polys)))
    if not out:
        raise PipelineError("kml_no_polygon", "No polygon was found in the KML file. It must contain a <Polygon> boundary.")
    return out


def _kmz_bytes(data: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
            name = "doc.kml" if "doc.kml" in names else (names[0] if names else None)
            if name is None:
                raise PipelineError("kmz_no_kml", "The KMZ archive does not contain a .kml file.")
            return zf.read(name)
    except zipfile.BadZipFile as exc:
        raise PipelineError("bad_kmz", "The KMZ file is not a valid zip archive.") from exc


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
# Plain images carry no location or scale. Their scale is entered by the user; this is the fallback, the
# resolution of NEON airborne imagery, which is what DeepForest's own sample images (e.g. OSBS_029.png) are.
DEFAULT_IMAGE_M_PER_PX = 0.1


def read_features(filename: str, data: bytes) -> tuple[str, list[AreaFeature]]:
    """Every area in a vector upload, in file order. GeoTIFFs have none."""
    name = filename.lower()
    if name.endswith((".tif", ".tiff")):
        return "geotiff", []
    if name.endswith(IMAGE_EXTENSIONS):
        return "image", []
    if name.endswith(".kmz"):
        return "kmz", _kml_features(_kmz_bytes(data))
    if name.endswith(".kml"):
        return "kml", _kml_features(data)
    if name.endswith((".geojson", ".json")):
        try:
            obj = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PipelineError("bad_geojson", "The GeoJSON file is not valid JSON.") from exc
        return "geojson", _geojson_features(obj)
    raise PipelineError(
        "unsupported_file",
        "Unsupported file type. Upload a GeoTIFF, a plain image (PNG, JPG, WebP, BMP), or a KML, KMZ or GeoJSON boundary.",
    )


def combine(features: list[AreaFeature], selection: list[int] | None):
    """The chosen areas as one AOI. A file with several areas must say which; one area is used as is."""
    if selection is None:
        if len(features) > 1:
            raise PipelineError(
                "multiple_areas",
                f"This file contains {len(features)} areas. Choose which ones to analyse.",
            )
        selection = [0]
    chosen = sorted(set(selection))
    if not chosen:
        raise PipelineError("no_selection", "Select at least one area to analyse.")
    if chosen[0] < 0 or chosen[-1] >= len(features):
        raise PipelineError("bad_selection", "The selected areas do not exist in this file. Please upload it again.")
    return _area(unary_union([_repair(features[i].geom) for i in chosen]))


def parse_geojson(obj: dict) -> Polygon:
    """A drawn or API-submitted boundary: exactly one polygon."""
    feats = _geojson_features(obj)
    if len(feats) != 1:
        raise PipelineError("multipolygon", f"The GeoJSON contains {len(feats)} features. Please submit one area at a time.")
    return _single_polygon(feats[0].geom)


def parse_area_geojson(obj: dict) -> Polygon | MultiPolygon:
    """A stored project area: one polygon or a multipolygon."""
    return _area(shape(obj))


def parse_kml(data: bytes) -> Polygon | MultiPolygon:
    return combine(_kml_features(data), None)


def parse_kmz(data: bytes) -> Polygon | MultiPolygon:
    return parse_kml(_kmz_bytes(data))


def parse_upload(filename: str, data: bytes, selection: list[int] | None = None) -> ParsedInput:
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise PipelineError("file_too_large", f"The file is {len(data) / 1e6:.0f} MB. The maximum is 100 MB.")
    digest = sha256_bytes(data)
    kind, features = read_features(filename, data)
    if kind in ("geotiff", "image"):
        return ParsedInput(kind, None, data, digest, filename, selection)
    return ParsedInput(kind, combine(features, selection), None, digest, filename, selection)


# --------------------------------------------------------------------------- GeoTIFF


def _band_interpretation(src) -> tuple[dict, str]:
    """Decide which bands are R, G, B, NIR. Never silently assume: the decision is returned as text."""
    count, dtype = src.count, src.dtypes[0]
    desc = [(d or "").lower() for d in src.descriptions]
    ci = [str(c).lower() for c in src.colorinterp]
    if count == 1:
        raise PipelineError(
            "grayscale",
            "This GeoTIFF has a single band (grayscale). Vegetation indices need at least red, green and blue bands.",
        )
    if count == 2:
        raise PipelineError("two_bands", "This GeoTIFF has 2 bands. CANOPY needs RGB (3 bands) or RGB+NIR (4 bands).")
    if count == 3:
        return {"r": 1, "g": 2, "b": 3, "nir": None}, f"RGB, 3 bands, {dtype}"
    if count == 4 and dtype == "uint8":
        return {"r": 1, "g": 2, "b": 3, "nir": None}, "RGBA, 4 bands, uint8 (alpha dropped, treated as RGB)"
    if count == 4:
        if any("alpha" in c for c in ci):
            return {"r": 1, "g": 2, "b": 3, "nir": None}, f"RGBA, 4 bands, {dtype} (alpha dropped, treated as RGB)"
        return {"r": 1, "g": 2, "b": 3, "nir": 4}, f"RGB+NIR, 4 bands, {dtype} (band 4 assumed near-infrared)"

    def find(*keys):
        for i, d in enumerate(desc, start=1):
            if any(k in d for k in keys):
                return i
        return None

    r, g, b, nir = find("red"), find("green"), find("blue"), find("nir", "near")
    if r and g and b:
        note = f"{count} bands, {dtype}; bands matched by description: R={r} G={g} B={b}" + (f" NIR={nir}" if nir else "")
        return {"r": r, "g": g, "b": b, "nir": nir}, note
    raise PipelineError(
        "unknown_bands",
        f"This GeoTIFF has {count} bands but their descriptions do not say which is red, green and blue. "
        "Please export an RGB or RGB+NIR GeoTIFF.",
    )


def _normalize(arr: np.ndarray, dtype: str, nodata_mask: np.ndarray) -> tuple[np.ndarray, float]:
    arr = arr.astype(np.float32)
    if dtype == "uint8":
        scale = 255.0
    else:
        valid = arr[~nodata_mask]
        scale = float(valid.max()) if valid.size else 1.0
        scale = scale if scale > 0 else 1.0
    return np.clip(arr / scale, 0.0, 1.0), scale


def load_geotiff(parsed: ParsedInput, aoi_lonlat: Polygon | MultiPolygon | None, image_m_per_px: float | None = None) -> Scene:
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

    with MemoryFile(parsed.raster_bytes) as mem:
        try:
            src = mem.open()
        except Exception as exc:  # noqa: BLE001
            raise PipelineError("bad_geotiff", "The file could not be opened as a GeoTIFF.") from exc
        with src:
            if src.crs is None:
                # No location: analyse it like a plain image, at the resolution the user entered.
                if src.count < 3:
                    raise PipelineError("grayscale", "This image has fewer than 3 bands. CANOPY needs red, green and blue.")
                arr = src.read([1, 2, 3])
                return _image_scene(np.moveaxis(arr, 0, -1), str(arr.dtype), parsed, image_m_per_px, "GeoTIFF without a CRS")  # noqa: E501
            bands, interp = _band_interpretation(src)
            w, s, e, n = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
            footprint = box(w, s, e, n)
            if aoi_lonlat is None:
                aoi_lonlat = footprint
                aoi_note = "AOI = full raster footprint (no boundary supplied)"
            else:
                if not aoi_lonlat.intersects(footprint):
                    raise PipelineError("aoi_outside_raster", "The boundary you drew does not overlap the uploaded image.")
                aoi_lonlat = _area(aoi_lonlat.intersection(footprint))
                aoi_note = "AOI = supplied boundary clipped to raster footprint"
            validate_aoi(aoi_lonlat)

            c = aoi_lonlat.centroid
            dst_epsg = geo.utm_epsg(c.x, c.y)
            src_is_metric_true = src.crs.is_projected and not src.crs.to_epsg() == 3857
            unit = (src.crs.linear_units or "").lower()
            if src_is_metric_true and unit in ("metre", "meter", "m"):
                dst_crs = src.crs
                transform = src.transform
                width, height = src.width, src.height
                reprojected = False
            else:
                dst_crs = rasterio.crs.CRS.from_epsg(dst_epsg)
                transform, width, height = calculate_default_transform(src.crs, dst_crs, src.width, src.height, *src.bounds)
                reprojected = True

            # Rasters over the pixel budget are averaged down by a whole factor so memory stays bounded.
            decimate = 1
            if width * height > config.MAX_SCENE_PX:
                decimate = int(np.ceil(np.sqrt(width * height / config.MAX_SCENE_PX)))
                transform = transform * rasterio.Affine.scale(decimate)
                width, height = int(np.ceil(width / decimate)), int(np.ceil(height / decimate))
                reprojected = True  # resampled onto a new grid, so it goes through reproject()

            nodata = src.nodata
            wanted = [bands["r"], bands["g"], bands["b"]] + ([bands["nir"]] if bands["nir"] else [])
            out = np.zeros((len(wanted), height, width), dtype=src.dtypes[0])
            valid = np.ones((height, width), dtype=bool)
            for i, bidx in enumerate(wanted):
                if reprojected:
                    reproject(
                        source=rasterio.band(src, bidx),
                        destination=out[i],
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=transform,
                        dst_crs=dst_crs,
                        resampling=Resampling.average if decimate > 1 else Resampling.nearest,
                        src_nodata=nodata,
                        dst_nodata=0,
                    )
                else:
                    out[i] = src.read(bidx)
            if nodata is not None:
                valid &= ~np.all(out[:3] == (0 if reprojected else nodata), axis=0)
            elif reprojected:
                valid &= ~np.all(out[:3] == 0, axis=0)
            dtype = src.dtypes[0]

            m_per_px_x, m_per_px_y = abs(transform.a), abs(transform.e)
            if abs(m_per_px_x - m_per_px_y) / max(m_per_px_x, m_per_px_y) > 0.01:
                raise PipelineError(
                    "non_square_pixels",
                    f"Pixels are not square ({m_per_px_x:.3f} × {m_per_px_y:.3f} m). Please resample the image first.",
                )
            rgb = np.zeros((height, width, 3), dtype=np.float32)
            scales = []
            for i in range(3):
                rgb[..., i], sc = _normalize(out[i], dtype, ~valid)
                scales.append(sc)
            nir = None
            if bands["nir"]:
                nir, sc = _normalize(out[3], dtype, ~valid)
                scales.append(sc)

            audit = {
                "input_type": "geotiff",
                "interpreted_as": interp,
                "source_crs": src.crs.to_string(),
                "working_crs": dst_crs.to_string(),
                "reprojected": reprojected,
                "reprojection_resampling": ("average" if decimate > 1 else "nearest") if reprojected else None,
                "decimation_factor": decimate,
                "band_normalization_divisors": [round(float(s), 4) for s in scales],
                "aoi_note": aoi_note,
                "resolution_source": "affine transform pixel size" + (" after reprojection to UTM" if reprojected else ""),
                "nodata_pixels": int((~valid).sum()),
                "tags": {k: v for k, v in src.tags().items() if len(str(v)) < 200},
            }
            return Scene(
                rgb=rgb,
                nir=nir,
                transform=tuple(transform)[:6],
                crs=dst_crs.to_string(),
                m_per_px=float((m_per_px_x + m_per_px_y) / 2.0),
                aoi_lonlat=aoi_lonlat,
                audit=audit,
            )


def geotiff_solar_metadata(tags: dict) -> tuple[float, float] | None:
    """Sun elevation/azimuth from common acquisition tags, if the file carries them."""
    low = {k.lower(): v for k, v in tags.items()}
    el_keys = ["sun_elevation", "sunelevation", "sun_elev", "meansunel", "sun_elevation_angle"]
    az_keys = ["sun_azimuth", "sunazimuth", "sun_az", "meansunaz", "sun_azimuth_angle"]
    el = next((low[k] for k in el_keys if k in low), None)
    az = next((low[k] for k in az_keys if k in low), None)
    try:
        return (float(el), float(az)) if el is not None and az is not None else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- plain images (PNG, JPG, ...)


def image_info(data: bytes) -> dict:
    """Size and mode of a plain image, for the upload review step. Raises a PipelineError if unreadable."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as im:
            return {"width": im.width, "height": im.height, "mode": im.mode, "format": im.format}
    except (UnidentifiedImageError, OSError) as exc:
        raise PipelineError("bad_image", "The file could not be opened as an image.") from exc


def load_image(parsed: ParsedInput, image_m_per_px: float | None) -> Scene:
    from PIL import Image, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = max(config.MAX_SCENE_PX * 4, 200_000_000)
    try:
        im = Image.open(io.BytesIO(parsed.raster_bytes))
        im.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise PipelineError("bad_image", "The file could not be opened as an image.") from exc
    if im.mode in ("L", "LA", "1", "I", "I;16", "F"):
        raise PipelineError(
            "grayscale", "This image is grayscale. Vegetation indices need colour (red, green and blue) channels."
        )
    alpha = None
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        alpha = np.asarray(im.convert("RGBA"))[..., 3]
    arr = np.asarray(im.convert("RGB"))
    if alpha is not None:
        arr = arr.copy()
        arr[alpha == 0] = 0
    return _image_scene(arr, "uint8", parsed, image_m_per_px, f"{im.format or 'image'} {im.mode}")


def _image_scene(arr: np.ndarray, dtype: str, parsed: ParsedInput, image_m_per_px: float | None, what: str) -> Scene:
    """A located-nowhere raster: placed at 0°N 0°E in Web Mercator, where 1 map unit is 1 ground metre."""
    assumed = image_m_per_px is None
    m = float(image_m_per_px or DEFAULT_IMAGE_M_PER_PX)
    h, w = arr.shape[:2]
    if h < 8 or w < 8:
        raise PipelineError("image_too_small", f"The image is only {w} x {h} pixels. CANOPY needs at least 8 x 8.")
    decimate = 1
    if h * w > config.MAX_SCENE_PX:
        decimate = int(np.ceil(np.sqrt(h * w / config.MAX_SCENE_PX)))
        from PIL import Image

        arr = np.asarray(Image.fromarray(arr.astype(np.uint8) if dtype == "uint8" else arr).reduce(decimate))
        h, w = arr.shape[:2]
        m *= decimate
    valid = ~np.all(arr == 0, axis=-1)
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    scales = []
    for i in range(3):
        rgb[..., i], sc = _normalize(arr[..., i], dtype, ~valid)
        scales.append(sc)
    area_m2 = h * w * m * m
    if area_m2 < 100:
        raise PipelineError(
            "aoi_too_small",
            f"At {m:g} m per pixel this image covers only {area_m2:.0f} m². Check the ground resolution you entered.",
        )
    transform = (m, 0.0, 0.0, 0.0, -m, 0.0)
    (lon0, lat0), (lon1, lat1) = geo.mercator_to_lonlat(0.0, 0.0), geo.mercator_to_lonlat(w * m, -h * m)
    footprint = box(min(lon0, lon1), min(lat0, lat1), max(lon0, lon1), max(lat0, lat1))
    audit = {
        "input_type": "image",
        "interpreted_as": f"RGB from {what}, no georeference",
        "working_crs": "EPSG:3857 (placed at 0°N 0°E, where 1 unit = 1 m)",
        "resolution_source": ("assumed default" if assumed else "entered by the user") + f": {m:g} m per pixel",
        "resolution_assumed": assumed,
        "band_normalization_divisors": [round(float(s), 4) for s in scales],
        "decimation_factor": decimate,
        "georeferenced": False,
        "nodata_pixels": int((~valid).sum()),
        "tags": {},
    }
    return Scene(rgb=rgb, nir=None, transform=transform, crs="EPSG:3857", m_per_px=m, aoi_lonlat=footprint, audit=audit)
