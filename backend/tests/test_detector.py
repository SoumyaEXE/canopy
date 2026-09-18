"""Hybrid outline construction, blob markers, and YOLO11 segmentation detector tests."""

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


def test_variant_resolution_prefers_requested_then_nearest(monkeypatch):
    monkeypatch.setattr(detector, "trained_variants", lambda: ["yolo11n-seg", "yolo11m-seg"])
    assert detector.resolve_variant("yolo11m-seg") == "yolo11m-seg"
    assert detector.resolve_variant("yolo11s-seg") == "yolo11m-seg"  # nearest, bigger wins the tie
    assert detector.resolve_variant("bogus") == "yolo11m-seg"
    monkeypatch.setattr(detector, "trained_variants", lambda: [])
    assert detector.resolve_variant("yolo11s-seg") is None


def test_untrained_server_reports_unavailable(monkeypatch):
    monkeypatch.setattr(detector, "trained_variants", lambda: [])
    ok, why = detector.available()
    assert ok is False and why


def test_work_scale_keeps_training_band():
    assert detector.work_scale(0.56, (1000, 1000)) == 1.0
    assert abs(detector.work_scale(0.1, (1000, 1000)) - 0.1 / detector.MIN_WORK_GSD_M) < 1e-9
    assert abs(detector.work_scale(1.12, (1000, 1000)) - 1.12 / detector.MAX_WORK_GSD_M) < 1e-9
    assert detector.work_scale(10.0, (1000, 1000)) == detector.MAX_UPSAMPLE


def test_mask_crops_feed_crowns():
    canopy = np.ones((60, 60), dtype=bool)
    aoi = np.ones_like(canopy)
    crop = np.zeros((22, 22), dtype=bool)
    crop[4:18, 4:18] = True
    labels, _, info = detector.crowns_from_boxes(np.array([[10, 10, 30, 30, 0.9]]), canopy, aoi, 0.5, masks=[(9, 9, crop)])
    assert (labels == 1).sum() == 14 * 14
    assert "segment" in info["outline_rule"]


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
    assert (labels == 1).sum() > 250


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
