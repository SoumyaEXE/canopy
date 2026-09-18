"""Fine-tune YOLO11-seg on the tree crown dataset from build_tree_dataset.py (CPU friendly).

    python scripts/train_trees.py --variant yolo11s-seg --epochs 40
    python scripts/train_trees.py --variant yolo11n-seg --epochs 60 --time 1.0   # stop after 1 hour

The best checkpoint (by validation mask mAP on held-out polygons) is copied to
backend/data/models/<variant>-trees.pt, which is what the app loads.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline import detector  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=list(detector.VARIANTS), default=detector.DEFAULT_VARIANT)
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "tree_dataset" / "data.yaml")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--time", type=float, default=None, help="hours; overrides epochs when set")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--init", type=Path, help="continue from these weights instead of the COCO checkpoint")
    ap.add_argument("--name", help="run folder name (default <variant>-trees)")
    args = ap.parse_args()

    from ultralytics import YOLO

    for cache in args.data.parent.glob("labels/*.cache"):
        cache.unlink()
    base = ROOT / f"{args.variant}.pt"
    start = args.init or (base if base.is_file() else Path(f"{args.variant}.pt"))  # COCO start unless continuing
    model = YOLO(str(start))
    name = args.name or f"{args.variant}-trees"
    model.train(
        data=str(args.data),
        epochs=args.epochs,
        time=args.time,
        imgsz=detector.PATCH_SIZE,
        batch=args.batch,
        workers=args.workers,
        cache="ram",
        device="cpu",
        single_cls=True,
        max_det=detector.MAX_DET,
        patience=15,
        cos_lr=True,
        close_mosaic=5,
        # aerial imagery has no "up": flips both ways, full rotation, mild colour and scale jitter
        fliplr=0.5,
        flipud=0.5,
        degrees=90,
        scale=0.3,
        hsv_h=0.02,
        hsv_s=0.5,
        hsv_v=0.3,
        mosaic=1.0,
        project=str(detector.MODELS_DIR / "runs"),
        name=name,
        exist_ok=True,
        seed=0,
        deterministic=True,
        plots=True,
        verbose=False,
    )
    best = detector.MODELS_DIR / "runs" / name / "weights" / "best.pt"
    shutil.copy(best, detector.weights_path(args.variant))
    print(f"saved {detector.weights_path(args.variant)}")


if __name__ == "__main__":
    main()
