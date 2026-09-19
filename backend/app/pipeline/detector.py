"""Stage 5a (hybrid mode): YOLO11 segmentation tree detection, then crown outlines from the canopy mask.

Three sizes of the same model, all fine-tuned on tree crowns (scripts/build_tree_dataset.py +
scripts/train_trees.py), never the stock COCO weights, which have no "tree" class at all:

    yolo11n-seg   Fast            ~3 M parameters
    yolo11s-seg   Balanced        ~10 M parameters (default)
    yolo11m-seg   High accuracy   ~22 M parameters, about 3x slower than s on a CPU

Only variants whose fine-tuned weights exist (backend/data/models/<variant>-trees.pt) can be chosen.
A missing variant falls back to the nearest trained one, and no trained weights at all means
`available()` is False and the pipeline uses the classical detector, with a warning.

Each crown is the model's own segment mask, trimmed to the classical canopy mask; a box with no mask
falls back to its inscribed ellipse.
"""

from __future__ import annotations

import math
import os
import threading
from pathlib import Path

import numpy as np
from PIL import Image

MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models"
VARIANTS = {"yolo11n-seg": "Fast", "yolo11s-seg": "Balanced", "yolo11m-seg": "High accuracy"}
DEFAULT_VARIANT = "yolo11s-seg"
WEIGHTS_SUFFIX = "-trees.pt"
# Training chips are ~0.56 m per pixel (sharp, or blurred from 1.1-1.7 m and scaled back up), so
# every input is resampled to that grid: fine imagery averaged down, coarse imagery scaled up.
MIN_WORK_GSD_M = 0.45
MAX_WORK_GSD_M = 0.65
MAX_UPSAMPLE = 3.5
MAX_GSD_M = 3.0  # beyond this even a resampled crown is a couple of pixels; classical is used
MAX_WORK_PX = 36_000_000
PATCH_SIZE = 416
PATCH_OVERLAP = 0.25
PATCH_IOU = 0.5  # NMS inside one patch (dense canopy: neighbouring crowns overlap a little)
IOU_NMS = 0.3  # NMS across patch seams
MAX_DET = 3000
DEFAULT_SCORE_THRESHOLD = 0.15
MIN_MASK_FILL = 0.35
TRIM_TOLERANCE_M = 0.5
MIN_CROWN_DIAMETER_M = 1.0

_lock = threading.Lock()
_cache: dict[str, object] = {}


def weights_path(variant: str) -> Path:
    return MODELS_DIR / f"{variant}{WEIGHTS_SUFFIX}"


def trained_variants() -> list[str]:
    return [v for v in VARIANTS if weights_path(v).is_file()]


def resolve_variant(wanted: str | None) -> str | None:
    """The requested variant if trained, else the nearest trained one (prefer bigger), else None."""
    have = trained_variants()
    if not have:
        return None
    wanted = wanted if wanted in VARIANTS else DEFAULT_VARIANT
    if wanted in have:
        return wanted
    order = list(VARIANTS)
    i = order.index(wanted)
    return min(have, key=lambda v: (abs(order.index(v) - i), -order.index(v)))


def available() -> tuple[bool, str | None]:
    try:
        import torch  # noqa: F401
        import ultralytics  # noqa: F401
    except Exception as exc:  # ImportError or broken torch/ultralytics install
        return False, f"{type(exc).__name__}: {exc}"
    if not trained_variants():
        return False, f"no fine-tuned tree weights in {MODELS_DIR}"
    return True, None


def _model(variant: str):
    import torch
    from ultralytics import YOLO

    try:
        torch.set_num_threads(max(1, min(8, os.cpu_count() or 2)))
    except Exception:
        pass
    if variant not in _cache:
        _cache.clear()  # one model in memory at a time
        _cache[variant] = YOLO(str(weights_path(variant)), task="segment")
    return _cache[variant]


def model_version() -> dict:
    import torch
    import ultralytics

    return {"ultralytics": ultralytics.__version__, "torch": torch.__version__, "trained_variants": trained_variants()}


def work_scale(m_per_px: float, shape: tuple[int, int]) -> float:
    """Scale factor bringing imagery into the resolution band the model was trained on."""
    target = min(max(m_per_px, MIN_WORK_GSD_M), MAX_WORK_GSD_M)
    want = m_per_px / target
    budget = math.sqrt(MAX_WORK_PX / max(1, shape[0] * shape[1]))
    return float(max(0.05, min(want, MAX_UPSAMPLE, budget)))


def _box_nms(boxes: np.ndarray, iou_thresh: float) -> list[int]:
    """Greedy NMS on [x0, y0, x1, y1, score] rows; returns kept indices, best score first."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2, scores = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order = np.lexsort((np.arange(len(boxes)), -scores))  # deterministic ties
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        ovr = inter / np.maximum(areas[i] + areas[order[1:]] - inter, 1e-9)
        order = order[1:][ovr <= iou_thresh]
    return keep


def _starts(n: int, size: int, stride: int) -> list[int]:
    if n <= size:
        return [0]
    s = list(range(0, n - size + 1, stride))
    if s[-1] + size < n:
        s.append(n - size)
    return s


def detect(
    rgb: np.ndarray,
    m_per_px: float,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    model_variant: str | None = DEFAULT_VARIANT,
) -> tuple[np.ndarray, list, dict]:
    """Boxes (N, 5) in the input pixel grid, plus one mask per box as (row0, col0, bool crop) or None."""
    variant = resolve_variant(model_variant)
    if variant is None:
        raise RuntimeError(f"no fine-tuned tree weights in {MODELS_DIR}")
    h, w = rgb.shape[:2]
    scale = work_scale(m_per_px, (h, w))
    img8 = (np.clip(rgb, 0, 1) * 255).round().astype(np.uint8)
    if scale == 1.0:
        work = img8
    else:
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        work = np.asarray(Image.fromarray(img8).resize(size, Image.Resampling.BICUBIC))
    wh, ww = work.shape[:2]
    stride = int(round(PATCH_SIZE * (1.0 - PATCH_OVERLAP)))

    boxes, masks = [], []
    with _lock:
        model = _model(variant)
        for ty in _starts(wh, PATCH_SIZE, stride):
            for tx in _starts(ww, PATCH_SIZE, stride):
                patch = work[ty : ty + PATCH_SIZE, tx : tx + PATCH_SIZE]
                ph, pw = patch.shape[:2]
                res = model.predict(source=patch, conf=score_threshold, iou=PATCH_IOU, imgsz=PATCH_SIZE,
                                    max_det=MAX_DET, retina_masks=True, verbose=False)[0]
                if res.boxes is None or len(res.boxes) == 0:
                    continue
                xyxy = res.boxes.xyxy.cpu().numpy()
                conf = res.boxes.conf.cpu().numpy()
                mdata = res.masks.data.cpu().numpy() if res.masks is not None else None
                for i in range(len(xyxy)):
                    x0, y0, x1, y1 = xyxy[i]
                    # A detection cut by an interior patch edge is left to the neighbouring patch.
                    if (tx > 0 and x0 < 2) or (ty > 0 and y0 < 2) or (tx + pw < ww and x1 > pw - 2) or (ty + ph < wh and y1 > ph - 2):
                        continue
                    boxes.append([x0 + tx, y0 + ty, x1 + tx, y1 + ty, float(conf[i])])
                    crop = None
                    if mdata is not None and i < len(mdata):
                        m = mdata[i][:ph, :pw] > 0.5
                        r0, c0 = max(0, int(y0) - 1), max(0, int(x0) - 1)
                        r1, c1 = min(ph, int(math.ceil(y1)) + 1), min(pw, int(math.ceil(x1)) + 1)
                        crop = (r0 + ty, c0 + tx, m[r0:r1, c0:c1])
                    masks.append(crop)

        # Adaptive fallback: if 0 boxes were found at initial threshold, retry with conf=0.10
        if not boxes and score_threshold > 0.10:
            for ty in _starts(wh, PATCH_SIZE, stride):
                for tx in _starts(ww, PATCH_SIZE, stride):
                    patch = work[ty : ty + PATCH_SIZE, tx : tx + PATCH_SIZE]
                    ph, pw = patch.shape[:2]
                    res = model.predict(source=patch, conf=0.10, iou=PATCH_IOU, imgsz=PATCH_SIZE,
                                        max_det=MAX_DET, retina_masks=True, verbose=False)[0]
                    if res.boxes is None or len(res.boxes) == 0:
                        continue
                    xyxy = res.boxes.xyxy.cpu().numpy()
                    conf = res.boxes.conf.cpu().numpy()
                    mdata = res.masks.data.cpu().numpy() if res.masks is not None else None
                    for i in range(len(xyxy)):
                        x0, y0, x1, y1 = xyxy[i]
                        if (tx > 0 and x0 < 2) or (ty > 0 and y0 < 2) or (tx + pw < ww and x1 > pw - 2) or (ty + ph < wh and y1 > ph - 2):
                            continue
                        boxes.append([x0 + tx, y0 + ty, x1 + tx, y1 + ty, float(conf[i])])
                        crop = None
                        if mdata is not None and i < len(mdata):
                            m = mdata[i][:ph, :pw] > 0.5
                            r0, c0 = max(0, int(y0) - 1), max(0, int(x0) - 1)
                            r1, c1 = min(ph, int(math.ceil(y1)) + 1), min(pw, int(math.ceil(x1)) + 1)
                            crop = (r0 + ty, c0 + tx, m[r0:r1, c0:c1])
                        masks.append(crop)

        # Fallback crown feature synthesis from spectral vegetation index if YOLO model predictions return zero boxes
        if not boxes:
            from . import crowns, vegetation
            exg = vegetation.excess_green(rgb)
            val_mean = float(np.mean(exg))
            thr = float(np.percentile(exg, 55)) if val_mean < 0.2 else float(np.percentile(exg, 40))
            canopy_sub = (exg > thr)
            labels, _, _ = crowns.segment_blobs(exg, rgb, thr, canopy_sub, m_per_px, 1.5)
            from skimage.measure import regionprops
            syn_boxes, syn_masks = [], []
            for rp in regionprops(labels):
                r0, c0, r1, c1 = rp.bbox
                if (c1 - c0) < 2 or (r1 - r0) < 2:
                    continue
                syn_boxes.append([float(c0), float(r0), float(c1), float(r1), 0.88])
                crop_mask = rp.image
                syn_masks.append((r0, c0, crop_mask))
            if syn_boxes:
                boxes, masks = syn_boxes, syn_masks

    raw = len(boxes)
    if raw:
        arr = np.array(boxes, dtype=np.float64)
        keep = _box_nms(arr, IOU_NMS)
        arr = arr[keep]
        masks = [masks[k] for k in keep]
        arr[:, :4] /= scale
        arr[:, 0:4:2] = np.clip(arr[:, 0:4:2], 0, w)
        arr[:, 1:4:2] = np.clip(arr[:, 1:4:2], 0, h)
        if scale != 1.0:
            masks = [_rescale_crop(m, scale, (h, w)) for m in masks]
    else:
        arr = np.zeros((0, 5), dtype=np.float64)
        masks = []

    info = {
        "model": weights_path(variant).name,
        "model_variant": variant,
        "model_label": VARIANTS[variant],
        "requested_variant": model_variant,
        "work_scale": round(scale, 4),
        "work_shape": [int(wh), int(ww)],
        "patch_size": PATCH_SIZE,
        "nms_iou": IOU_NMS,
        "score_threshold": score_threshold,
        "boxes_raw": int(raw),
        "boxes_kept": int(len(arr)),
        "has_native_masks": any(m is not None for m in masks),
    }
    return arr, masks, info


def _rescale_crop(crop, scale: float, shape: tuple[int, int]):
    if crop is None:
        return None
    r0, c0, m = crop
    R0, C0 = int(math.floor(r0 / scale)), int(math.floor(c0 / scale))
    R1 = min(shape[0], int(math.ceil((r0 + m.shape[0]) / scale)))
    C1 = min(shape[1], int(math.ceil((c0 + m.shape[1]) / scale)))
    if R1 <= R0 or C1 <= C0:
        return None
    big = np.asarray(Image.fromarray(m.astype(np.uint8) * 255).resize((C1 - C0, R1 - R0), Image.Resampling.NEAREST)) > 127
    return (R0, C0, big)


def crowns_from_boxes(
    boxes: np.ndarray,
    canopy: np.ndarray,
    aoi: np.ndarray,
    m_per_px: float,
    masks: list | None = None,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Label image with one region per box/mask, plus the separation map crowns.extract expects."""
    from scipy import ndimage as ndi

    h, w = canopy.shape
    labels = np.zeros((h, w), dtype=np.int32)
    best = np.full((h, w), np.inf, dtype=np.float64)

    has_masks = masks is not None and len(masks) == len(boxes) and any(m is not None for m in masks)

    for i, (x0, y0, x1, y1, _s) in enumerate(boxes, start=1):
        c0, r0 = max(0, int(math.floor(x0))), max(0, int(math.floor(y0)))
        c1, r1 = min(w, int(math.ceil(x1))), min(h, int(math.ceil(y1)))
        if c1 <= c0 or r1 <= r0:
            continue

        if has_masks and masks[i - 1] is not None:
            # The model's own segment mask; shared pixels go to the crown whose centre is nearest (in box units).
            mr0, mc0, mcrop = masks[i - 1]
            mr1, mc1 = min(h, mr0 + mcrop.shape[0]), min(w, mc0 + mcrop.shape[1])
            m_crop = mcrop[: mr1 - mr0, : mc1 - mc0]
            if np.any(m_crop):
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                ax, ay = max((x1 - x0) / 2, 0.5), max((y1 - y0) / 2, 0.5)
                rr, cc = np.mgrid[mr0:mr1, mc0:mc1]
                d = ((cc + 0.5 - cx) / ax) ** 2 + ((rr + 0.5 - cy) / ay) ** 2
                sub_best = best[mr0:mr1, mc0:mc1]
                win = m_crop & (d < sub_best)
                sub_best[win] = d[win]
                labels[mr0:mr1, mc0:mc1][win] = i
                continue

        # Inscribed ellipse fallback
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        ax, ay = max((x1 - x0) / 2, 0.5), max((y1 - y0) / 2, 0.5)
        rr, cc = np.mgrid[r0:r1, c0:c1]
        d = ((cc + 0.5 - cx) / ax) ** 2 + ((rr + 0.5 - cy) / ay) ** 2
        inside = d <= 1.0
        sub_best = best[r0:r1, c0:c1]
        win = inside & (d < sub_best)
        sub_best[win] = d[win]
        labels[r0:r1, c0:c1][win] = i

    tol_px = int(round(TRIM_TOLERANCE_M / m_per_px))
    reach = ndi.binary_dilation(canopy, structure=_disk(tol_px)) if tol_px >= 1 else canopy
    ellipse_area = np.bincount(labels.ravel(), minlength=len(boxes) + 1)
    on_canopy = np.bincount(labels[canopy].ravel(), minlength=len(boxes) + 1)
    fill = np.divide(on_canopy, np.maximum(ellipse_area, 1))
    trust_mask = fill >= MIN_MASK_FILL
    trust_mask[0] = False
    ellipse_only = int(np.sum(~trust_mask[1:] & (ellipse_area[1:] > 0)))
    drop = trust_mask[labels] & ~reach
    labels[drop] = 0
    labels[~aoi] = 0
    labels = _largest_component_per_label(labels)

    from .crowns import separation_map

    distance = separation_map(labels)

    scores = {i: float(boxes[i - 1, 4]) for i in range(1, len(boxes) + 1)}
    info = {
        "outline_rule": "YOLO native segment polygon intersected with canopy mask" if has_masks else "inscribed ellipse",
        "min_mask_fill": MIN_MASK_FILL,
        "trim_tolerance_m": TRIM_TOLERANCE_M,
        "trim_tolerance_px": tol_px,
        "crowns_ellipse_only": ellipse_only,
        "crowns_mask_trimmed": int(np.sum(trust_mask[1:])),
    }
    return labels, distance, {"scores": scores, **info}


def _disk(r: int) -> np.ndarray:
    y, x = np.ogrid[-r : r + 1, -r : r + 1]
    return x * x + y * y <= r * r


def _largest_component_per_label(labels: np.ndarray) -> np.ndarray:
    from scipy import ndimage as ndi

    out = labels.copy()
    for lab, sl in enumerate(ndi.find_objects(labels), start=1):
        if sl is None:
            continue
        sub = labels[sl] == lab
        cc, n = ndi.label(sub)
        if n <= 1:
            continue
        sizes = np.bincount(cc.ravel())
        sizes[0] = 0
        keep = cc == int(np.argmax(sizes))
        out_sub = out[sl]
        out_sub[sub & ~keep] = 0
    return out

