"""Stage 5a (hybrid mode): YOLO11 segmentation tree detection, then crown outlines from the canopy mask.

YOLO11 (Ultralytics) provides state-of-the-art instance segmentation / detection for canopy trees.
Main model: YOLO11s-seg (YOLO11 Small Segmentation)
Fallback model: YOLO11n-seg (YOLO11 Nano Segmentation for entry-level CPUs like Core i3)

The classical mask still answers "which pixels are canopy", so each crown is:
    its detector box's inscribed ellipse, competing with neighbouring ellipses for shared pixels,
    intersected with the canopy mask (unless the mask covers too little of it, see MIN_MASK_FILL).

The model is optional. If ultralytics or torch is missing, `available()` is False and the pipeline
falls back to the classical detector and records a warning.
"""

from __future__ import annotations

import math
import os
import threading
from pathlib import Path

import numpy as np
from PIL import Image

MAIN_MODEL_NAME = "yolo11s-seg.pt"
FALLBACK_MODEL_NAME = "yolo11n-seg.pt"
MODEL_GSD_M = 0.10  # target resolution for model domain
MAX_GSD_M = 0.20
MAX_WORK_PX = 36_000_000
MAX_UPSAMPLE = 6.0
PATCH_SIZE = 400
PATCH_OVERLAP = 0.25
IOU_NMS = 0.15
DEFAULT_SCORE_THRESHOLD = 0.25
MIN_MASK_FILL = 0.35
TRIM_TOLERANCE_M = 0.5
MIN_CROWN_DIAMETER_M = 1.0

_lock = threading.Lock()
_cached_model = None
_cached_model_info = {}


def available() -> tuple[bool, str | None]:
    try:
        import torch  # noqa: F401
        import ultralytics  # noqa: F401
    except Exception as exc:  # ImportError or broken torch/ultralytics install
        return False, f"{type(exc).__name__}: {exc}"
    return True, None


def _get_model_weights_path(default_name: str) -> str:
    """Return fine-tuned model path if present under backend/data/models/, else default weights name."""
    data_dir = Path(__file__).resolve().parent.parent.parent / "data" / "models"
    stem = Path(default_name).stem
    custom_weights = [
        data_dir / f"{stem}-odisha.pt",
        data_dir / f"{stem}.pt",
    ]
    for path in custom_weights:
        if path.is_file():
            return str(path)
    return default_name


def _model(force_fallback: bool = False):
    global _cached_model, _cached_model_info
    import torch
    from ultralytics import YOLO

    torch.set_num_threads(max(1, torch.get_num_threads()))

    use_fallback = force_fallback or os.getenv("CANOPY_LOW_SPEC", "0") == "1"

    if _cached_model is not None and _cached_model_info.get("is_fallback") == use_fallback:
        return _cached_model, _cached_model_info

    if not use_fallback:
        try:
            target_path = _get_model_weights_path(MAIN_MODEL_NAME)
            m = YOLO(target_path)
            _cached_model = m
            _cached_model_info = {
                "active_model": target_path,
                "model_variant": "yolo11s-seg",
                "is_fallback": False,
            }
            return _cached_model, _cached_model_info
        except Exception as exc:
            # Fallback to YOLO11n-seg if YOLO11s-seg fails to load or run out of memory
            use_fallback = True

    target_path = _get_model_weights_path(FALLBACK_MODEL_NAME)
    m = YOLO(target_path)
    _cached_model = m
    _cached_model_info = {
        "active_model": target_path,
        "model_variant": "yolo11n-seg",
        "is_fallback": True,
    }
    return _cached_model, _cached_model_info


def model_version() -> dict:
    import torch
    import ultralytics

    return {
        "ultralytics": ultralytics.__version__,
        "torch": torch.__version__,
        "main_model": MAIN_MODEL_NAME,
        "fallback_model": FALLBACK_MODEL_NAME,
    }


def work_scale(m_per_px: float, shape: tuple[int, int]) -> float:
    """Upsampling factor that brings the imagery toward the model's 10 cm GSD, within the pixel budget."""
    want = max(1.0, m_per_px / MODEL_GSD_M)
    budget = math.sqrt(MAX_WORK_PX / max(1, shape[0] * shape[1]))
    return float(max(1.0, min(want, MAX_UPSAMPLE, budget)))


def detect(rgb: np.ndarray, m_per_px: float, score_threshold: float = DEFAULT_SCORE_THRESHOLD) -> tuple[np.ndarray, dict]:
    """Return boxes as an (N, 5) array [xmin, ymin, xmax, ymax, score] in the input's pixel grid."""
    h, w = rgb.shape[:2]
    scale = work_scale(m_per_px, (h, w))
    img8 = (np.clip(rgb, 0, 1) * 255).round().astype(np.uint8)
    if scale > 1.0:
        work = np.asarray(Image.fromarray(img8).resize((round(w * scale), round(h * scale)), Image.Resampling.BICUBIC))
    else:
        work = img8
    wh, ww = work.shape[:2]

    with _lock:
        model_instance, model_meta = _model()
        results = model_instance.predict(
            source=work,
            conf=score_threshold,
            iou=IOU_NMS,
            verbose=False,
        )

    all_boxes = []
    if results and len(results) > 0:
        res = results[0]
        if res.boxes is not None and len(res.boxes) > 0:
            xyxy = res.boxes.xyxy.cpu().numpy()
            conf = res.boxes.conf.cpu().numpy()
            for i in range(len(xyxy)):
                all_boxes.append([xyxy[i][0], xyxy[i][1], xyxy[i][2], xyxy[i][3], conf[i]])

    raw_count = len(all_boxes)
    if raw_count == 0:
        boxes = np.zeros((0, 5), dtype=np.float64)
    else:
        boxes = np.array(all_boxes, dtype=np.float64)
        boxes[:, :4] /= scale
        boxes = boxes[boxes[:, 4] >= score_threshold]

    if len(boxes):
        boxes[:, 0:4:2] = np.clip(boxes[:, 0:4:2], 0, w)
        boxes[:, 1:4:2] = np.clip(boxes[:, 1:4:2], 0, h)
        # Deterministic order: row, then column of the box centre
        cy = (boxes[:, 1] + boxes[:, 3]) / 2
        cx = (boxes[:, 0] + boxes[:, 2]) / 2
        boxes = boxes[np.lexsort((np.round(cx, 3), np.round(cy, 3)))]

    info = {
        "model": model_meta.get("active_model", MAIN_MODEL_NAME),
        "model_variant": model_meta.get("model_variant", "yolo11s-seg"),
        "is_fallback": model_meta.get("is_fallback", False),
        "model_gsd_m": MODEL_GSD_M,
        "work_scale": round(scale, 4),
        "work_shape": [int(wh), int(ww)],
        "nms_iou": IOU_NMS,
        "score_threshold": score_threshold,
        "boxes_raw": int(raw_count),
        "boxes_kept": int(len(boxes)),
    }
    return boxes, info


def crowns_from_boxes(boxes: np.ndarray, canopy: np.ndarray, aoi: np.ndarray, m_per_px: float) -> tuple[np.ndarray, np.ndarray, dict]:
    """Label image with one region per box, plus the separation map `crowns.extract` expects."""
    from scipy import ndimage as ndi

    h, w = canopy.shape
    labels = np.zeros((h, w), dtype=np.int32)
    best = np.full((h, w), np.inf, dtype=np.float64)
    for i, (x0, y0, x1, y1, _s) in enumerate(boxes, start=1):
        c0, r0 = max(0, int(math.floor(x0))), max(0, int(math.floor(y0)))
        c1, r1 = min(w, int(math.ceil(x1))), min(h, int(math.ceil(y1)))
        if c1 <= c0 or r1 <= r0:
            continue
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
        "outline_rule": "inscribed ellipse of each box, split between overlapping boxes by normalised elliptical distance, trimmed to the canopy mask",
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
