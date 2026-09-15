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
