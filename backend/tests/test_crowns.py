import math

import numpy as np
from skimage.draw import disk

from app.pipeline import crowns

M_PER_PX = 0.5
TRANSFORM = (M_PER_PX, 0.0, 0.0, 0.0, -M_PER_PX, 0.0)  # EPSG:3857 near null island


def _run(mask, min_d=3.0):
    labels, distance, _ = crowns.segment(mask, M_PER_PX, min_d)
    aoi = np.ones_like(mask, dtype=bool)
    kept, rejected, _ = crowns.extract(labels, distance, aoi, TRANSFORM, "EPSG:3857", M_PER_PX, min_d)
    return kept, rejected


def test_nine_separate_circles():
    r_px = 8  # 4 m radius
    mask = np.zeros((150, 150), dtype=bool)
    for i in range(3):
        for j in range(3):
            rr, cc = disk((25 + 50 * i, 25 + 50 * j), r_px, shape=mask.shape)
            mask[rr, cc] = True
    kept, _ = _run(mask)
    assert len(kept) == 9
    true_area = math.pi * (r_px * M_PER_PX) ** 2
    for c in kept:
        assert abs(c["area_m2"] - true_area) / true_area < 0.10


def test_two_overlapping_circles_merge():
    """Documents the known merge failure: overlapping crowns closer than a crown radius read as one."""
    mask = np.zeros((80, 100), dtype=bool)
    for cx in (44, 54):
        rr, cc = disk((40, cx), 12, shape=mask.shape)
        mask[rr, cc] = True
    kept, _ = _run(mask, min_d=6.0)
    assert len(kept) == 1


def test_small_region_rejected_not_dropped():
    mask = np.zeros((60, 60), dtype=bool)
    rr, cc = disk((30, 30), 2, shape=mask.shape)  # about 1 m radius, below the 3 m diameter minimum
    mask[rr, cc] = True
    kept, rejected = _run(mask)
    assert len(kept) == 0
    assert len(rejected) == 1 and rejected[0]["reason"] == "too_small"
