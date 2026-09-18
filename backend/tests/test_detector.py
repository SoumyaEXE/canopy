"""Hybrid outline construction and blob markers. Neither test needs torch: boxes are given, not predicted."""

import numpy as np
from skimage.draw import disk

from app.pipeline import audit, crowns, detector, vegetation


def _scene(n=12, seed=7):
    rng = np.random.default_rng(seed)  # fixture generation only
    h = w = 160
    rgb = np.full((h, w, 3), [0.55, 0.45, 0.35], dtype=np.float32)
    centres = []
    for _ in range(n):
        r, c, rad = int(rng.integers(15, 145)), int(rng.integers(15, 145)), int(rng.integers(5, 10))
        rr, cc = disk((r, c), rad, shape=(h, w))
        rgb[rr, cc] = [0.15, 0.35, 0.12]
        centres.append((r, c, rad))
    return rgb, centres


def test_crowns_from_boxes_one_region_per_box_and_trimmed_to_mask():
    rgb, centres = _scene()
    idx = vegetation.excess_green(rgb)
    aoi = np.ones(idx.shape, dtype=bool)
    canopy, _ = vegetation.canopy_mask(idx, aoi, 0.1, vegetation.otsu_with_confidence(idx[aoi])["otsu_value"])
    # Boxes 30% larger than the true crowns: trimming to the mask must pull the outline back in.
    boxes = np.array([[c - 1.3 * r, rr - 1.3 * r, c + 1.3 * r, rr + 1.3 * r, 0.9] for rr, c, r in centres])
    labels, distance, info = detector.crowns_from_boxes(boxes, canopy, aoi, m_per_px=0.1)
    assert set(np.unique(labels)) - {0} <= set(range(1, len(boxes) + 1))
    from scipy import ndimage as ndi

    reach = ndi.binary_dilation(canopy, structure=detector._disk(info["trim_tolerance_px"]))
    # Only crowns that fell back to their ellipse (mask fill too low) may extend past the mask's reach.
    outside = set(np.unique(labels[~reach])) - {0}
    assert len(outside) <= info["crowns_ellipse_only"]
    assert info["crowns_mask_trimmed"] >= len(boxes) // 2
    assert distance.shape == labels.shape and distance.min() >= 0
    assert set(info["scores"]) == set(range(1, len(boxes) + 1))


def test_ellipse_fallback_when_mask_misses_tree():
    canopy = np.zeros((50, 50), dtype=bool)
    aoi = np.ones_like(canopy)
    labels, _, info = detector.crowns_from_boxes(np.array([[10, 10, 30, 30, 0.8]]), canopy, aoi, m_per_px=0.1)
    assert info["crowns_ellipse_only"] == 1
    assert (labels == 1).sum() > 250  # close to the inscribed circle's pi * 10^2


def test_blob_segmentation_is_deterministic_and_finds_crowns():
    rgb, centres = _scene(n=15)
    idx = vegetation.excess_green(rgb)
    aoi = np.ones(idx.shape, dtype=bool)
    thr = vegetation.otsu_with_confidence(idx[aoi])["otsu_value"]
    canopy, _ = vegetation.canopy_mask(idx, aoi, 0.5, thr)
    a = crowns.segment_blobs(idx, rgb, thr, canopy, 0.5, 3.0)
    b = crowns.segment_blobs(idx, rgb, thr, canopy, 0.5, 3.0)
    assert np.array_equal(a[0], b[0])
    assert a[2]["markers"] >= 8


def test_stage_images_written(tmp_path):
    rgb, _ = _scene()
    idx = vegetation.excess_green(rgb)
    aoi = np.ones(idx.shape, dtype=bool)
    thr = vegetation.otsu_with_confidence(idx[aoi])["otsu_value"]
    canopy, _ = vegetation.canopy_mask(idx, aoi, 0.5, thr)
    labels, dist, info = crowns.segment_blobs(idx, rgb, thr, canopy, 0.5, 3.0)
    t = (0.5, 0.0, 0.0, 0.0, -0.5, 0.0)
    kept, rejected, _ = crowns.extract(labels, dist, aoi, t, "EPSG:3857", 0.5, 1.5)
    for c in kept:
        c["confidence_bucket"] = "high"
    files = audit.write_stage_images(
        tmp_path, index=idx, raw=idx > thr, canopy=canopy, aoi=aoi, response=info["_response"],
        markers=info["_marker_coords"], boxes=None, labels=labels, crowns=kept, rejected=rejected,
    )
    assert files == ["stage_index.png", "stage_threshold.png", "stage_mask.png", "stage_markers.png", "stage_segments.png", "stage_crowns.png"]
    assert all((tmp_path / f).stat().st_size > 0 for f in files)
