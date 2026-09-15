import json

import numpy as np
from skimage.draw import disk

from app.pipeline import audit, confidence, crowns, vegetation


def _pipeline_once() -> str:
    rng = np.random.default_rng(42)  # fixture generation only; the pipeline itself uses no randomness
    h = w = 200
    rgb = np.full((h, w, 3), [0.55, 0.45, 0.35], dtype=np.float32)
    for _ in range(30):
        r, c, rad = rng.integers(15, 185), rng.integers(15, 185), rng.integers(5, 12)
        rr, cc = disk((r, c), rad, shape=(h, w))
        rgb[rr, cc] = [0.15, 0.35, 0.12]
    m = 0.5
    t = (m, 0.0, 0.0, 0.0, -m, 0.0)
    aoi = np.ones((h, w), dtype=bool)
    idx = vegetation.excess_green(rgb)
    thr = vegetation.otsu_with_confidence(idx[aoi])["otsu_value"]
    mask, _ = vegetation.canopy_mask(idx, aoi, m, thr)
    labels, dist, _ = crowns.segment(mask, m, 3.0)
    kept, _, _ = crowns.extract(labels, dist, aoi, t, "EPSG:3857", m, 3.0)
    for c in kept:
        c["height_m"] = None
    confidence.score(kept, height_enabled=False)
    for i, c in enumerate(kept, 1):
        c["id"] = i
    return audit.dumps_deterministic({"type": "FeatureCollection", "features": [audit.crown_feature(c) for c in kept]})


def test_byte_identical_geojson():
    a, b = _pipeline_once(), _pipeline_once()
    assert a == b
    assert len(json.loads(a)["features"]) > 10
