"""Stage 5a (hybrid mode): DeepForest tree detection, then crown outlines from the canopy mask.

DeepForest (Weinstein et al. 2019, weecology/deepforest-tree) is a RetinaNet trained on 10 cm airborne RGB.
It answers "where is each tree" far better than distance-transform peaks, which merge touching crowns
and split elongated ones. The classical mask still answers "which pixels are canopy", so each crown is:

    its detector box's inscribed ellipse, competing with neighbouring ellipses for shared pixels,
    intersected with the canopy mask (unless the mask covers too little of it, see MIN_MASK_FILL).

The model is optional. If torch or deepforest is missing, `available()` is False and the pipeline
falls back to the classical detector and says so in the warnings.
"""

from __future__ import annotations

import math
import threading
from functools import lru_cache

import numpy as np
from PIL import Image

MODEL_NAME = "weecology/deepforest-tree"
MODEL_GSD_M = 0.10  # the resolution the model was trained on
# Above this pixel size the model is out of its domain (F1 falls from 0.76 at 0.1 m to 0.37 at 0.25 m on the
# OSBS_029 benchmark, and to under 0.1 at 0.5 m), so "auto" switches to blob markers instead.
MAX_GSD_M = 0.20
# Imagery coarser than the model's GSD is upsampled toward it, but never beyond this many pixels,
# so a 1 km² area stays tractable on a laptop CPU.
MAX_WORK_PX = 36_000_000
MAX_UPSAMPLE = 6.0
PATCH_SIZE = 400
PATCH_OVERLAP = 0.25
IOU_NMS = 0.15
DEFAULT_SCORE_THRESHOLD = 0.3
# If the canopy mask covers less than this share of a box's ellipse, the mask missed the tree
# (dark crown, shadow side, a threshold that fell on grass), so the ellipse itself is the outline.
MIN_MASK_FILL = 0.35
# Crown edges are darker and less green than crown centres, so the mask under-reaches them. Trimming uses the
# mask grown by this much, which keeps the outline on the real crown edge rather than inside it.
TRIM_TOLERANCE_M = 0.5
# The detector already vouches for each tree, so the size filter only drops slivers left by trimming.
MIN_CROWN_DIAMETER_M = 1.0

_lock = threading.Lock()


def available() -> tuple[bool, str | None]:
    try:
        import deepforest  # noqa: F401
        import torch  # noqa: F401
    except Exception as exc:  # ImportError, or a broken torch install
        return False, f"{type(exc).__name__}: {exc}"
    return True, None


@lru_cache(maxsize=1)
def _model():
    import torch
    from deepforest import main

    torch.set_num_threads(max(1, torch.get_num_threads()))
    torch.use_deterministic_algorithms(True, warn_only=True)
    m = main.deepforest()
    m.load_model(MODEL_NAME)
    m.model.eval()
    return m


def model_version() -> dict:
    import deepforest
    import torch

    return {"deepforest": deepforest.__version__, "torch": torch.__version__, "model": MODEL_NAME}


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
    with _lock:  # torch inference is already multi-threaded; serialise jobs rather than oversubscribe.
        model = _model()
        if max(wh, ww) <= PATCH_SIZE:
            df = model.predict_image(image=work.astype(np.float32))
        else:
            df = model.predict_tile(image=work.astype(np.float32), patch_size=PATCH_SIZE, patch_overlap=PATCH_OVERLAP, iou_threshold=IOU_NMS)
    raw = 0 if df is None else len(df)
    if df is None or not len(df):
        boxes = np.zeros((0, 5), dtype=np.float64)
    else:
        boxes = np.array(df[["xmin", "ymin", "xmax", "ymax", "score"]].to_numpy(dtype=np.float64), copy=True)
        boxes[:, :4] /= scale
        boxes = boxes[boxes[:, 4] >= score_threshold]
    boxes[:, 0:4:2] = np.clip(boxes[:, 0:4:2], 0, w)
    boxes[:, 1:4:2] = np.clip(boxes[:, 1:4:2], 0, h)
    # Deterministic order: row, then column of the box centre (the same rule as watershed markers).
    if len(boxes):
        cy = (boxes[:, 1] + boxes[:, 3]) / 2
        cx = (boxes[:, 0] + boxes[:, 2]) / 2
        boxes = boxes[np.lexsort((np.round(cx, 3), np.round(cy, 3)))]
    info = {
        "model": MODEL_NAME,
        "model_gsd_m": MODEL_GSD_M,
        "work_scale": round(scale, 4),
        "work_shape": [int(wh), int(ww)],
        "patch_size": PATCH_SIZE,
        "patch_overlap": PATCH_OVERLAP,
        "nms_iou": IOU_NMS,
        "score_threshold": score_threshold,
        "boxes_raw": int(raw),
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
        # Normalised elliptical distance: <= 1 inside the inscribed ellipse. Where ellipses overlap,
        # the pixel goes to the box whose centre is relatively nearer (a scale-aware Voronoi split).
        d = ((cc + 0.5 - cx) / ax) ** 2 + ((rr + 0.5 - cy) / ay) ** 2
        inside = d <= 1.0
        sub_best = best[r0:r1, c0:c1]
        win = inside & (d < sub_best)
        sub_best[win] = d[win]
        labels[r0:r1, c0:c1][win] = i

    # Now trim each ellipse to canopy pixels, unless the mask plainly missed that tree.
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
    # Keep only the largest connected piece of each crown, so trimming never yields a multi-part crown.
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
