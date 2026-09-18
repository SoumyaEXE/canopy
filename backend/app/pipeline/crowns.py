"""Stage 5: marker-controlled watershed crown segmentation, filtering, polygons."""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage as ndi
from shapely.geometry import Polygon
from skimage.feature import peak_local_max
from skimage.measure import find_contours, regionprops
from skimage.segmentation import watershed

from . import geo

MAX_CROWN_AREA_M2 = 400.0
MIN_SOLIDITY = 0.35
COORD_DECIMALS = 7


def segment(canopy: np.ndarray, m_per_px: float, min_crown_diameter_m: float) -> tuple[np.ndarray, np.ndarray, dict]:
    distance = ndi.distance_transform_edt(canopy)
    sigma_px = max(1.0, (min_crown_diameter_m / 4.0) / m_per_px)
    distance_smooth = ndi.gaussian_filter(distance, sigma=sigma_px)
    min_distance_px = max(2, int((min_crown_diameter_m / 2.0) / m_per_px))
    coords = peak_local_max(
        distance_smooth,
        min_distance=min_distance_px,
        labels=canopy.astype(np.int32),
        exclude_border=False,
    )
    # peak_local_max output order is deterministic, but sort anyway so IDs never depend on library internals.
    coords = coords[np.lexsort((coords[:, 1], coords[:, 0]))] if len(coords) else coords
    markers = np.zeros(distance.shape, dtype=np.int32)
    for i, (row, col) in enumerate(coords, start=1):
        markers[row, col] = i
    labels = watershed(-distance_smooth, markers, mask=canopy)
    info = {
        "distance_sigma_px": round(float(sigma_px), 4),
        "peak_min_distance_px": int(min_distance_px),
        "markers": int(len(coords)),
        "_marker_coords": coords,
    }
    return labels, distance, info


def pixel_to_crs(transform: tuple, col: float, row: float) -> tuple[float, float]:
    a, b, c, d, e, f = transform
    return a * col + b * row + c, d * col + e * row + f


def _to_lonlat_fn(crs: str):
    if crs == "EPSG:3857":
        return geo.mercator_to_lonlat
    from pyproj import Transformer

    t = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    return lambda x, y: t.transform(x, y)


def region_polygon(label_crop: np.ndarray, row0: int, col0: int, transform: tuple, to_lonlat) -> dict | None:
    padded = np.pad(label_crop.astype(np.uint8), 1)
    contours = find_contours(padded, 0.5)
    if not contours:
        return None
    ring = max(contours, key=len)
    # contour (row, col) in padded pixel-index space; pixel centres sit at integer indices.
    poly_px = Polygon([(c - 1 + col0 + 0.5, r - 1 + row0 + 0.5) for r, c in ring])
    poly_px = poly_px.simplify(1.0, preserve_topology=True)
    if poly_px.is_empty or not isinstance(poly_px, Polygon):
        return None
    coords = []
    for cx, ry in poly_px.exterior.coords:
        x, y = pixel_to_crs(transform, cx, ry)
        lon, lat = to_lonlat(x, y)
        coords.append([round(lon, COORD_DECIMALS), round(lat, COORD_DECIMALS)])
    return {"type": "Polygon", "coordinates": [coords]}


def extract(
    labels: np.ndarray,
    distance: np.ndarray,
    aoi: np.ndarray,
    transform: tuple,
    crs: str,
    m_per_px: float,
    min_crown_diameter_m: float,
) -> tuple[list[dict], list[dict], dict]:
    """Measure every watershed region, split into kept crowns and rejected regions. Nothing is dropped silently."""
    to_lonlat = _to_lonlat_fn(crs)
    px_area = m_per_px**2
    min_area_m2 = math.pi * (min_crown_diameter_m / 2.0) ** 2
    # A crown "touches the edge" if it is adjacent to a pixel outside the AOI (or the raster border).
    outside = ~aoi
    outside_grown = ndi.binary_dilation(np.pad(outside, 1, constant_values=True), iterations=1)[1:-1, 1:-1]

    crowns, rejected = [], []
    reasons = {"too_small": 0, "too_large": 0, "low_solidity": 0}
    for rp in regionprops(labels):
        area_m2 = rp.area * px_area
        r0, c0, r1, c1 = rp.bbox
        crop = rp.image
        solidity = float(rp.solidity)
        reason = None
        if area_m2 < min_area_m2:
            reason = "too_small"
        elif area_m2 > MAX_CROWN_AREA_M2:
            reason = "too_large"
        elif solidity < MIN_SOLIDITY:
            reason = "low_solidity"
        cy, cx = rp.centroid
        x, y = pixel_to_crs(transform, cx + 0.5, cy + 0.5)
        lon, lat = to_lonlat(x, y)
        poly = region_polygon(crop, r0, c0, transform, to_lonlat)
        if poly is None:
            reason = reason or "too_small"
        base = {
            "label": int(rp.label),
            "centroid_px": [round(float(cx), 3), round(float(cy), 3)],
            "centroid_lonlat": [round(lon, COORD_DECIMALS), round(lat, COORD_DECIMALS)],
            "area_m2": round(area_m2, 3),
            "polygon": poly,
        }
        if reason:
            reasons[reason] += 1
            rejected.append({**base, "reason": reason})
            continue
        perimeter_px = float(rp.perimeter) if rp.perimeter > 0 else 1.0
        eq_diam_px = float(rp.equivalent_diameter_area)
        ry, rx = int(round(cy)), int(round(cx))
        inside = 0 <= ry < labels.shape[0] and 0 <= rx < labels.shape[1] and labels[ry, rx] == rp.label
        # If the centroid falls outside a concave region, use the region's deepest point: it is still a
        # separation measure, and it is recorded as such.
        dist_at_centroid = float(distance[ry, rx]) if inside else float(distance[r0:r1, c0:c1][crop].max())
        touches = bool(outside_grown[r0:r1, c0:c1][crop].any())
        crowns.append(
            {
                **base,
                "equivalent_diameter_m": round(eq_diam_px * m_per_px, 3),
                "perimeter_m": round(perimeter_px * m_per_px, 3),
                "eccentricity": round(float(rp.eccentricity), 4),
                "solidity": round(solidity, 4),
                "touches_edge": touches,
                "_perimeter_px": perimeter_px,
                "_area_px": int(rp.area),
                "_eq_radius_px": eq_diam_px / 2.0,
                "_dist_centroid_px": dist_at_centroid,
                "_centroid_inside": inside,
            }
        )
    crowns.sort(key=lambda c: c["label"])
    rejected.sort(key=lambda c: c["label"])
    info = {
        "min_crown_area_m2": round(min_area_m2, 4),
        "max_crown_area_m2": MAX_CROWN_AREA_M2,
        "min_solidity": MIN_SOLIDITY,
        "regions_total": len(crowns) + len(rejected),
        "regions_kept": len(crowns),
        "regions_rejected": len(rejected),
        "rejection_reasons": reasons,
    }
    return crowns, rejected, info


# ---- scale-aware blob markers ---------------------------------------------------------------------------
# The distance transform only finds a crown centre where the canopy mask has a waist, so touching crowns
# merge. Sunlit crowns are also brighter and greener at the centre than at the edge, so a
# Laplacian-of-Gaussian blob detector on "greenness above threshold × brightness" finds one blob per crown
# at the right scale, even inside a continuous mask. Blob radii run from half the minimum crown diameter
# up to BLOB_MAX_RADIUS_M.

BLOB_MAX_RADIUS_M = 6.0
BLOB_NUM_SIGMA = 12
BLOB_THRESHOLD = 0.02
BLOB_OVERLAP = 0.3
# Each crown may extend this many blob radii from its blob centre, so one blob cannot flood a whole stand.
BLOB_REACH = 1.4


# blob_log builds a (scales x H x W) stack, so large scenes are searched in overlapping windows. Scenes up to one
# window are searched in one pass, exactly as before.
BLOB_WINDOW = 2048


def blob_response(index: np.ndarray, rgb: np.ndarray, threshold: float) -> np.ndarray:
    img = np.clip(index - threshold, 0.0, None).astype(np.float32)
    img *= (0.5 + rgb.mean(axis=-1, dtype=np.float32))
    lo, span = float(img.min()), float(np.ptp(img))
    if span <= 0:
        return np.zeros_like(img)
    img -= lo
    img /= span
    return img


def _blob_log_windowed(resp: np.ndarray, min_sigma: float, max_sigma: float, overlap: float = BLOB_OVERLAP) -> np.ndarray:
    from skimage.feature import blob_log

    kw = dict(min_sigma=min_sigma, max_sigma=max_sigma, num_sigma=BLOB_NUM_SIGMA, threshold=BLOB_THRESHOLD,
              overlap=overlap, exclude_border=False)
    h, w = resp.shape
    if h <= BLOB_WINDOW and w <= BLOB_WINDOW:
        return blob_log(resp, **kw)
    pad = int(np.ceil(4 * max_sigma)) + 2
    found = []
    for r0 in range(0, h, BLOB_WINDOW):
        for c0 in range(0, w, BLOB_WINDOW):
            r1, c1 = min(h, r0 + BLOB_WINDOW), min(w, c0 + BLOB_WINDOW)
            pr0, pc0 = max(0, r0 - pad), max(0, c0 - pad)
            sub = resp[pr0 : min(h, r1 + pad), pc0 : min(w, c1 + pad)]
            if not sub.any():
                continue
            b = blob_log(sub, **kw)
            if len(b):
                b[:, 0] += pr0
                b[:, 1] += pc0
                # Keep only blobs centred in this window's core, so overlaps never double-count.
                core = (b[:, 0] >= r0) & (b[:, 0] < r1) & (b[:, 1] >= c0) & (b[:, 1] < c1)
                found.append(b[core])
    return np.concatenate(found) if found else np.zeros((0, 3))


def segment_blobs(
    index: np.ndarray, rgb: np.ndarray, threshold: float, canopy: np.ndarray, m_per_px: float, min_crown_diameter_m: float
) -> tuple[np.ndarray, np.ndarray, dict]:
    resp = blob_response(index, rgb, threshold)
    min_sigma = max(0.7, (min_crown_diameter_m / 2.0) / m_per_px / math.sqrt(2))
    max_sigma = max(min_sigma + 0.5, BLOB_MAX_RADIUS_M / m_per_px / math.sqrt(2))
    blobs = _blob_log_windowed(resp, min_sigma, max_sigma)
    h, w = canopy.shape
    keep = []
    for r, c, s in blobs:
        ri, ci = int(round(r)), int(round(c))
        if 0 <= ri < h and 0 <= ci < w and canopy[ri, ci]:
            keep.append((ri, ci, float(s) * math.sqrt(2)))
    keep.sort(key=lambda b: (b[0], b[1]))

    markers = np.zeros((h, w), dtype=np.int32)
    reach = np.zeros((h, w), dtype=bool)
    for i, (r, c, rad) in enumerate(keep, start=1):
        markers[r, c] = i
        R = int(math.ceil(rad * BLOB_REACH))
        r0, r1, c0, c1 = max(0, r - R), min(h, r + R + 1), max(0, c - R), min(w, c + R + 1)
        yy, xx = np.ogrid[r0 - r : r1 - r, c0 - c : c1 - c]
        reach[r0:r1, c0:c1] |= yy * yy + xx * xx <= (rad * BLOB_REACH) ** 2
    smooth = ndi.gaussian_filter(resp, sigma=max(1.0, min_sigma / 2))
    labels = watershed(-smooth, markers, mask=canopy & reach) if keep else np.zeros((h, w), dtype=np.int32)
    info = {
        "marker_source": "Laplacian-of-Gaussian blobs on clip(index - threshold, 0) x (0.5 + brightness)",
        "blob_min_radius_m": round(min_sigma * math.sqrt(2) * m_per_px, 3),
        "blob_max_radius_m": round(max_sigma * math.sqrt(2) * m_per_px, 3),
        "blob_threshold": BLOB_THRESHOLD,
        "blob_overlap": BLOB_OVERLAP,
        "blob_reach_radii": BLOB_REACH,
        "blobs_total": int(len(blobs)),
        "markers": len(keep),
        "_marker_coords": np.array([(r, c) for r, c, _ in keep], dtype=np.int64).reshape(-1, 2),
        "_response": resp,
    }
    return labels.astype(np.int32), separation_map(labels), info


DENSE_MIN_CROWN_M = 5.0  # closed-canopy crowns: smaller blobs are leaf clusters, not trees
DENSE_SMOOTH_M = 0.5
DENSE_BLOB_OVERLAP = 0.5


def segment_dense(
    rgb: np.ndarray, canopy: np.ndarray, aoi: np.ndarray, m_per_px: float, min_crown_diameter_m: float
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Closed-canopy crowns: sunlit crown tops are bright domes, and the gaps between crowns are shadow.

    Greenness cannot separate touching crowns (everything is green), so inside the canopy the darker
    Otsu class of brightness is treated as inter-crown shadow, and crowns are brightness blobs on what is
    left, grown by watershed and stopped at the shadow gaps.
    """
    from skimage.filters import threshold_otsu

    lum = rgb.mean(axis=-1, dtype=np.float32)
    inside = canopy & aoi
    shade_t = float(threshold_otsu(lum[inside])) if inside.sum() > 100 else 0.0
    from .vegetation import canopy_mask

    # Same clean-up as the canopy mask (opening, closing, small objects and holes), so crowns are solid.
    sunlit, _ = canopy_mask((inside & (lum >= shade_t)).astype(np.float32), aoi, m_per_px, 0.5)
    min_d = max(min_crown_diameter_m, DENSE_MIN_CROWN_M)
    resp = ndi.gaussian_filter(lum, DENSE_SMOOTH_M / m_per_px) * sunlit
    top = float(resp.max())
    resp = (resp / top).astype(np.float32) if top > 0 else resp.astype(np.float32)
    min_sigma = max(0.7, (min_d / 2.0) / m_per_px / math.sqrt(2))
    max_sigma = max(min_sigma + 0.5, BLOB_MAX_RADIUS_M / m_per_px / math.sqrt(2))
    blobs = _blob_log_windowed(resp, min_sigma, max_sigma, overlap=DENSE_BLOB_OVERLAP)
    h, w = canopy.shape
    keep = sorted((int(round(a)), int(round(b)), float(s) * math.sqrt(2)) for a, b, s in blobs
                  if 0 <= int(round(a)) < h and 0 <= int(round(b)) < w and sunlit[int(round(a)), int(round(b))])
    markers = np.zeros((h, w), dtype=np.int32)
    reach = np.zeros((h, w), dtype=bool)
    for i, (rr, cc, rad) in enumerate(keep, start=1):
        markers[rr, cc] = i
        R = int(math.ceil(rad * BLOB_REACH))
        r0, r1, c0, c1 = max(0, rr - R), min(h, rr + R + 1), max(0, cc - R), min(w, cc + R + 1)
        yy, xx = np.ogrid[r0 - rr : r1 - rr, c0 - cc : c1 - cc]
        reach[r0:r1, c0:c1] |= yy * yy + xx * xx <= (rad * BLOB_REACH) ** 2
    smooth = ndi.gaussian_filter(resp, sigma=max(1.0, min_sigma / 2))
    labels = watershed(-smooth, markers, mask=sunlit & reach) if keep else np.zeros((h, w), dtype=np.int32)
    info = {
        "marker_source": "dense canopy: Laplacian-of-Gaussian blobs on brightness, inter-crown shadow removed",
        "shadow_brightness_threshold": round(shade_t, 5),
        "sunlit_canopy_fraction": round(float(sunlit.sum()) / max(1, int(inside.sum())), 4),
        "blob_min_radius_m": round(min_sigma * math.sqrt(2) * m_per_px, 3),
        "blob_max_radius_m": round(max_sigma * math.sqrt(2) * m_per_px, 3),
        "dense_min_crown_m": min_d,
        "blob_threshold": BLOB_THRESHOLD,
        "blob_reach_radii": BLOB_REACH,
        "blobs_total": int(len(blobs)),
        "markers": len(keep),
        "_marker_coords": np.array([(a, b) for a, b, _ in keep], dtype=np.int64).reshape(-1, 2),
        "_response": resp,
    }
    return labels.astype(np.int32), separation_map(labels), info


def separation_map(labels: np.ndarray) -> np.ndarray:
    """Distance to the nearest pixel that is not this crown (background or a neighbouring crown)."""
    edges = np.zeros(labels.shape, dtype=bool)
    dv = labels[:-1, :] != labels[1:, :]
    dh = labels[:, :-1] != labels[:, 1:]
    edges[:-1, :] |= dv
    edges[1:, :] |= dv
    edges[:, :-1] |= dh
    edges[:, 1:] |= dh
    return ndi.distance_transform_edt((labels > 0) & ~edges).astype(np.float32)
