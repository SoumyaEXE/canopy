"""Stages 3-4: vegetation index, Otsu threshold, morphology, canopy mask."""

from __future__ import annotations

import math

import numpy as np
from rasterio import features
from rasterio.transform import Affine
from shapely.geometry import mapping
from skimage import morphology
from skimage.filters import threshold_otsu

from . import geo

EPS = 1e-10


def excess_green(rgb: np.ndarray) -> np.ndarray:
    """ExG on chromatic coordinates: 2g - r - b where r,g,b = channel / (R+G+B)."""
    total = rgb[..., 0] + rgb[..., 1] + rgb[..., 2] + EPS
    r = rgb[..., 0] / total
    g = rgb[..., 1] / total
    b = rgb[..., 2] / total
    return (2.0 * g - r - b).astype(np.float32)


def vari(rgb: np.ndarray) -> np.ndarray:
    """VARI = (G - R) / (G + R - B). Clipped to [-1, 1]: the denominator can approach zero."""
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    denom = G + R - B
    denom = np.where(np.abs(denom) < 1e-3, np.where(denom < 0, -1e-3, 1e-3), denom)
    return np.clip((G - R) / denom, -1.0, 1.0).astype(np.float32)


def ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    return ((nir - red) / (nir + red + EPS)).astype(np.float32)


def compute_index(name: str, rgb: np.ndarray, nir: np.ndarray | None) -> np.ndarray:
    if name == "exg":
        return excess_green(rgb)
    if name == "vari":
        return vari(rgb)
    if name == "ndvi":
        if nir is None:
            from .errors import PipelineError

            raise PipelineError(
                "ndvi_unavailable",
                "NDVI needs a near-infrared band, and this imagery has only red, green and blue. Choose ExG or VARI.",
            )
        return ndvi(nir, rgb[..., 0])
    raise ValueError(f"unknown index {name}")


BIMODALITY_CUTOFF = 5.0 / 9.0


def otsu_with_confidence(values: np.ndarray) -> dict:
    """Otsu threshold plus a plain bimodality check.

    Otsu always returns a number, even on a uniform scene. Sarle's bimodality
    coefficient BC = (skewness² + 1) / (excess kurtosis + 3(n-1)²/((n-2)(n-3)))
    is 1/3 for a normal distribution and 5/9 for a uniform one; values above 5/9
    suggest two populations. It is conservative for unbalanced mixtures, so it
    errs toward flagging "low" when the split is actually fine, which is the safe
    direction for a warning.
    """
    from scipy.stats import kurtosis, skew

    v = values[np.isfinite(values)].astype(np.float64)
    t = float(threshold_otsu(v, nbins=256))
    lo, hi = v[v <= t], v[v > t]
    n = v.size
    w0, w1 = lo.size / n, hi.size / n
    bc = float((skew(v) ** 2 + 1) / (kurtosis(v) + 3 * (n - 1) ** 2 / ((n - 2) * (n - 3)))) if n > 3 else 0.0
    between = w0 * w1 * (float(lo.mean()) - float(hi.mean())) ** 2 if lo.size and hi.size else 0.0
    sep = between / float(v.var()) if v.var() > 0 else 0.0
    minority = min(w0, w1)
    confident = bc > BIMODALITY_CUTOFF and minority >= 0.05
    return {
        "otsu_value": t,
        "bimodality_coefficient": round(bc, 4),
        "separability": round(sep, 4),
        "minority_class_fraction": round(minority, 4),
        "confidence": "high" if confident else "low",
        "rule": "high if Sarle's bimodality coefficient > 5/9 and each class holds >= 5% of AOI pixels",
    }


def aoi_mask(aoi_lonlat, transform: tuple, crs: str, shape: tuple[int, int]) -> np.ndarray:
    geom = geo.reproject_geom(aoi_lonlat, 4326, crs)
    return features.rasterize(
        [(mapping(geom), 1)], out_shape=shape, transform=Affine(*transform), fill=0, all_touched=False, dtype=np.uint8
    ).astype(bool)


def canopy_mask(
    index: np.ndarray, aoi: np.ndarray, m_per_px: float, threshold: float
) -> tuple[np.ndarray, dict]:
    radius = max(1, round(0.5 / m_per_px))
    disk = morphology.disk(radius)
    min_px = max(1, int(math.ceil(1.0 / (m_per_px**2))))

    raw = (index > threshold) & aoi
    if m_per_px > 1.0:
        # At coarse resolution a single pixel is already more than 1 m² of canopy, so opening would erase real,
        # narrow canopy (hedgerows, single trees) rather than noise. Clean nothing.
        radius = 0
        opened = closed = raw
    else:
        opened = morphology.opening(raw, disk)
        closed = morphology.closing(opened, disk)
    # max_size removes objects/holes of size <= max_size, so pass min_px - 1 to keep exactly-1 m² objects.
    no_small = morphology.remove_small_objects(closed, max_size=min_px - 1) if min_px > 1 else closed
    filled = morphology.remove_small_holes(no_small, max_size=min_px - 1) if min_px > 1 else no_small
    final = filled & aoi

    info = {
        "morph_disk_radius_px": int(radius),
        "morph_disk_radius_m": round(radius * m_per_px, 4),
        "min_object_px": int(min_px),
        "min_hole_px": int(min_px),
        "pixel_counts": {
            "aoi": int(aoi.sum()),
            "above_threshold": int(raw.sum()),
            "after_opening": int(opened.sum()),
            "after_closing": int(closed.sum()),
            "after_remove_small_objects": int(no_small.sum()),
            "after_remove_small_holes_clipped": int(final.sum()),
        },
    }
    return final, info
