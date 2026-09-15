import numpy as np
import pytest

from app.pipeline import vegetation


def test_exg_hand_computed():
    rgb = np.array([[[0.2, 0.6, 0.2], [0.5, 0.5, 0.5]]], dtype=np.float32)
    exg = vegetation.excess_green(rgb)
    # r=0.2, g=0.6, b=0.2 -> 2*0.6 - 0.2 - 0.2 = 0.8 ; grey -> 2/3 - 1/3 - 1/3 = 0
    assert exg[0, 0] == pytest.approx(0.8, abs=1e-5)
    assert exg[0, 1] == pytest.approx(0.0, abs=1e-5)


def test_exg_uses_chromatic_normalization():
    base = np.array([[[0.1, 0.3, 0.1]]], dtype=np.float32)
    bright = base * 3.0
    # Raw 2G-R-B would triple with brightness; chromatic ExG does not change.
    assert vegetation.excess_green(base)[0, 0] == pytest.approx(vegetation.excess_green(bright)[0, 0], abs=1e-5)
    raw = 2 * base[0, 0, 1] - base[0, 0, 0] - base[0, 0, 2]
    assert abs(vegetation.excess_green(base)[0, 0] - raw) > 0.1


def test_otsu_bimodal_synthetic():
    rng = np.random.default_rng(0)
    vals = np.concatenate([rng.normal(-0.1, 0.02, 5000), rng.normal(0.3, 0.02, 5000)]).astype(np.float32)
    res = vegetation.otsu_with_confidence(vals)
    assert -0.05 < res["otsu_value"] < 0.25
    assert res["confidence"] == "high"


def test_otsu_flags_uniform_scene():
    rng = np.random.default_rng(1)
    vals = rng.normal(0.2, 0.05, 10000).astype(np.float32)
    assert vegetation.otsu_with_confidence(vals)["confidence"] == "low"


def test_canopy_mask_removes_speckle():
    idx = np.zeros((60, 60), dtype=np.float32)
    idx[10:30, 10:30] = 1.0
    idx[50, 50] = 1.0  # single pixel, under 1 m² at 0.5 m/px
    aoi = np.ones_like(idx, dtype=bool)
    mask, info = vegetation.canopy_mask(idx, aoi, 0.5, 0.5)
    assert not mask[50, 50]
    assert mask[20, 20]
    assert info["min_object_px"] == 4
