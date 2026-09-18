"""Compare the crown detectors: classical and every trained YOLO11 size.

1. Hand-labelled ground truth: DeepForest's OSBS_029 tile (61 trees), at 0.1 m and degraded to 0.5 m and 1 m.
2. Held-out Odisha polygons: the validation scores Ultralytics recorded for the best checkpoint.
3. The two sample screenshots: crowns found and seconds taken (no labels exist, so no accuracy claim).

    python scripts/eval_models.py --json ../docs/model_eval.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.pipeline import detector, ingest, run_pipeline  # noqa: E402
from benchmark import ground_truth, run_one, score, variants  # noqa: E402

PNGS = [r"C:\Users\Soumya\Desktop\kml\image(2).png", r"C:\Users\Soumya\Desktop\kml\test png.png"]


def odisha_val(variant: str) -> dict | None:
    f = detector.MODELS_DIR / "runs" / f"{variant}-trees" / "results.csv"
    if not f.is_file():
        return None
    rows = [{k.strip(): v for k, v in r.items()} for r in csv.DictReader(f.open())]
    best = max(rows, key=lambda r: float(r["metrics/mAP50(M)"]))
    return {
        "epochs": len(rows),
        "best_epoch": int(float(best["epoch"])),
        "box_map50": round(float(best["metrics/mAP50(B)"]), 3),
        "mask_map50": round(float(best["metrics/mAP50(M)"]), 3),
        "mask_map50_95": round(float(best["metrics/mAP50-95(M)"]), 3),
        "precision": round(float(best["metrics/precision(M)"]), 3),
        "recall": round(float(best["metrics/recall(M)"]), 3),
    }


def png_run(path: str, det: str, variant: str | None) -> dict:
    raw = Path(path).read_bytes()
    parsed = ingest.ParsedInput(kind="image", aoi_lonlat=None, raster_bytes=raw, sha256=ingest.sha256_bytes(raw), filename=Path(path).name)
    params = {"detector": det, "yolo_variant": variant, "min_crown_diameter_m": 3.0, "veg_index": "exg", "threshold_mode": "otsu",
              "threshold_manual": None, "tile_zoom": 18, "acquisition_datetime_utc": None, "enable_height": False, "image_m_per_px": 0.3}
    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.perf_counter()
        r = run_pipeline("eval", Path(tmp), parsed, params, lambda *_: None)
        return {"crowns": r["summary"]["crown_count"], "seconds": round(time.perf_counter() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path)
    ap.add_argument("--variants", nargs="+", default=["native", "0.5m", "1m"])
    args = ap.parse_args()

    detectors = [("classical", None)] + [("hybrid", v) for v in detector.trained_variants()]
    gt, utm, raw, t = ground_truth()
    out = {"osbs": [], "odisha_val": {}, "png": []}
    for name, spec in variants(raw, gt, args.variants).items():
        for det, v in detectors:
            pred, secs, summary = run_one(spec[0], det, 3.0, utm, yolo_variant=v)
            s = score(pred, spec[1])
            used = summary.get("detector_used", det)
            row = {"variant": name, "detector": v or "classical", "used": used, "seconds": round(secs, 1), **{k: round(x, 3) if isinstance(x, float) else x for k, x in s.items()}}
            out["osbs"].append(row)
            print(f"OSBS {name:5s} {row['detector']:12s} found {s['detected']:3d} matched {s['matched']:3d}/61  P {s['precision']:.2f} R {s['recall']:.2f} F1 {s['f1']:.2f}  {secs:.1f}s", flush=True)
    for v in detector.trained_variants():
        out["odisha_val"][v] = odisha_val(v)
        print("Odisha val", v, out["odisha_val"][v], flush=True)
    for p in PNGS:
        for det, v in detectors:
            r = png_run(p, det, v)
            out["png"].append({"file": Path(p).name, "detector": v or "classical", **r})
            print("PNG", Path(p).name, v or "classical", r, flush=True)
    if args.json:
        args.json.write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
