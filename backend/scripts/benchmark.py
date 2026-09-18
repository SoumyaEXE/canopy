"""Measured accuracy against hand-labelled trees, not just a count.

Uses DeepForest's OSBS_029 benchmark tile (NEON, Florida; 400x400 px at 0.1 m; 61 hand-drawn crown boxes)
and runs the full CANOPY pipeline on it and on degraded copies that mimic other inputs:

    native      the tile as shipped (UTM, 0.1 m)
    wgs84       the same pixels re-gridded to EPSG:4326 (tests the reprojection path)
    0.5m        downsampled to 0.5 m, the resolution of zoom-18 satellite basemaps
    1m          downsampled to 1 m
    3x3 mosaic  nine copies side by side (tests patching and the NMS across patch seams)

A detection matches a label when their boxes overlap with IoU >= 0.4 (DeepForest's own evaluation rule),
one-to-one, greedily by IoU. Boxes are compared in metres in the tile's UTM zone, so every variant is
scored against the same ground truth.

    python scripts/benchmark.py                 # both detectors, all variants
    python scripts/benchmark.py --detector hybrid --variants native 1m
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import Affine
from rasterio.warp import Resampling, calculate_default_transform, reproject
from shapely.geometry import box, shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import ingest, run_pipeline  # noqa: E402

IOU = 0.4


def data_dir() -> Path:
    import deepforest

    return Path(os.path.dirname(deepforest.__file__)) / "data"


def ground_truth() -> tuple[list, str, bytes, Affine]:
    import pandas as pd

    d = data_dir()
    tif = d / "OSBS_029.tif"
    with rasterio.open(tif) as src:
        t, crs = src.transform, src.crs.to_string()
    df = pd.read_csv(d / "OSBS_029.csv")
    gt = []
    for r in df.itertuples():
        x0, y0 = t * (r.xmin, r.ymin)
        x1, y1 = t * (r.xmax, r.ymax)
        gt.append(box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
    return gt, crs, tif.read_bytes(), t


def _write(arr: np.ndarray, crs: str, transform: Affine) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "v.tif"
        with rasterio.open(p, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=3, dtype="uint8",
                           crs=crs, transform=transform) as dst:
            dst.write(arr)
        return p.read_bytes()


def variants(raw: bytes, gt: list, names: list[str]) -> dict[str, tuple[bytes, list]]:
    with rasterio.MemoryFile(raw) as mf, mf.open() as src:
        arr, crs, t = src.read(), src.crs, src.transform
    out = {}
    if "native" in names:
        out["native"] = (raw, gt)
    for name, res in (("0.5m", 0.5), ("1m", 1.0)):
        if name not in names:
            continue
        f = int(res / t.a)
        h, w = arr.shape[1] // f, arr.shape[2] // f
        small = arr[:, : h * f, : w * f].reshape(3, h, f, w, f).astype(np.float64).mean(axis=(2, 4)).round().astype(np.uint8)
        out[name] = (_write(small, crs.to_string(), t * Affine.scale(f)), gt)
    if "wgs84" in names:
        bounds = rasterio.transform.array_bounds(arr.shape[1], arr.shape[2], t)
        dt, dw, dh = calculate_default_transform(crs, "EPSG:4326", arr.shape[2], arr.shape[1], *bounds)
        dst = np.zeros((3, dh, dw), dtype=np.uint8)
        reproject(arr, dst, src_transform=t, src_crs=crs, dst_transform=dt, dst_crs="EPSG:4326", resampling=Resampling.bilinear)
        out["wgs84"] = (_write(dst, "EPSG:4326", dt), gt)
    # Plain PNGs, no location: CANOPY is told only the ground resolution, as a user would enter it.
    from PIL import Image

    for name, res in (("png", 0.1), ("png 0.5m", 0.5), ("png 1m", 1.0)):
        if name not in names:
            continue
        f = int(round(res / t.a))
        h, w = arr.shape[1] // f, arr.shape[2] // f
        small = arr[:, : h * f, : w * f].reshape(3, h, f, w, f).astype(np.float64).mean(axis=(2, 4)).round().astype(np.uint8)
        buf = io.BytesIO()
        Image.fromarray(np.moveaxis(small, 0, -1)).save(buf, format="PNG")
        out[name] = (buf.getvalue(), gt, "image", res)
    if "3x3 mosaic" in names:
        big = np.tile(arr, (1, 3, 3))
        W, H = arr.shape[2] * t.a, arr.shape[1] * -t.e
        tiled_gt = [shape({"type": "Polygon", "coordinates": [[(x + i * W, y - j * H) for x, y in g.exterior.coords]]})
                    for i in range(3) for j in range(3) for g in gt]
        out["3x3 mosaic"] = (_write(big, crs.to_string(), t), tiled_gt)
    return out


def score(pred: list, gt: list) -> dict:
    pairs = []
    for i, p in enumerate(pred):
        for j, g in enumerate(gt):
            if p.intersects(g):
                iou = p.intersection(g).area / p.union(g).area
                if iou >= IOU:
                    pairs.append((iou, i, j))
    pairs.sort(reverse=True)
    used_p, used_g = set(), set()
    for _, i, j in pairs:
        if i not in used_p and j not in used_g:
            used_p.add(i)
            used_g.add(j)
    tp = len(used_p)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(gt) if gt else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"detected": len(pred), "labelled": len(gt), "matched": tp, "precision": precision, "recall": recall, "f1": f1}


def run_deepforest_direct(tif_bytes: bytes, utm: str) -> tuple[list, float]:
    from deepforest import main as df_main
    import torch
    
    try:
        torch.set_num_threads(max(1, min(4, os.cpu_count() or 2)))
    except Exception:
        pass

    model = df_main.deepforest()
    model.use_release()

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "eval.tif"
        p.write_bytes(tif_bytes)
        t0 = time.perf_counter()
        boxes_df = model.predict_tile(str(p), patch_size=400, patch_overlap=0.25)
        secs = time.perf_counter() - t0

        with rasterio.open(p) as src:
            t = src.transform

        boxes = []
        if boxes_df is not None and not boxes_df.empty:
            for r in boxes_df.itertuples():
                x0, y0 = t * (r.xmin, r.ymin)
                x1, y1 = t * (r.xmax, r.ymax)
                boxes.append(box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
        return boxes, secs


def run_one(tif: bytes, detector: str, min_d: float, utm: str, kind: str = "geotiff", image_m: float | None = None,
            origin: tuple[float, float] | None = None, yolo_variant: str = "yolo11s-seg") -> tuple[list, float, dict]:
    parsed = ingest.ParsedInput(kind=kind, aoi_lonlat=None, raster_bytes=tif, sha256=ingest.sha256_bytes(tif),
                                filename="v.png" if kind == "image" else "v.tif")
    params = {"detector": detector, "min_crown_diameter_m": min_d, "veg_index": "exg", "threshold_mode": "otsu",
              "threshold_manual": None, "tile_zoom": 18, "acquisition_datetime_utc": None, "enable_height": False,
              "image_m_per_px": image_m, "yolo_variant": yolo_variant}
    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.perf_counter()
        result = run_pipeline("bench", Path(tmp), parsed, params, lambda *_: None)
        secs = time.perf_counter() - t0
        fc = json.loads((Path(tmp) / "crowns.geojson").read_text(encoding="utf-8"))
    if kind == "image":
        to_utm = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        shift = origin or (0.0, 0.0)
    else:
        to_utm = Transformer.from_crs("EPSG:4326", utm, always_xy=True)
        shift = (0.0, 0.0)
    boxes = []
    for f in fc["features"]:
        xs, ys = zip(*((a + shift[0], b + shift[1]) for a, b in (to_utm.transform(x, y) for x, y in f["geometry"]["coordinates"][0])))
        boxes.append(box(min(xs), min(ys), max(xs), max(ys)))
    return boxes, secs, {**result["summary"], "detector_used": result.get("pipeline", {}).get("detector")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detector", choices=["hybrid", "classical", "deepforest", "both", "all"], default="all")
    ap.add_argument("--yolo-variant", choices=["yolo11n-seg", "yolo11s-seg", "yolo11m-seg", "yolo11l-seg"], default="yolo11s-seg")
    ap.add_argument("--variants", nargs="+", default=["native", "wgs84", "0.5m", "1m", "3x3 mosaic", "png", "png 0.5m", "png 1m"])
    ap.add_argument("--min-crown", type=float, default=3.0)
    ap.add_argument("--json", type=Path, help="also write the results table as JSON")
    args = ap.parse_args()

    gt, utm, raw, t = ground_truth()
    
    if args.detector == "all":
        dets = ["hybrid", "classical", "deepforest"]
    elif args.detector == "both":
        dets = ["hybrid", "classical"]
    else:
        dets = [args.detector]

    rows = []
    print("\n=================== FLORA CANOPY BENCHMARK SUITE ===================")
    print(f"Ground truth target: {len(gt)} hand-labelled crowns (OSBS_029 NEON Florida)")
    print(f"YOLO Model Variant: {args.yolo_variant}")
    print("--------------------------------------------------------------------\n")

    for name, spec in variants(raw, gt, args.variants).items():
        tif, truth = spec[0], spec[1]
        kind, image_m = (spec[2], spec[3]) if len(spec) > 2 else ("geotiff", None)
        
        for det in dets:
            if det == "deepforest":
                pred, secs = run_deepforest_direct(tif, utm)
                summary_count = {"crown_count_range": [len(pred), len(pred)]}
            else:
                pred, secs, summary = run_one(tif, det, args.min_crown, utm, kind, image_m, (t.c, t.f), args.yolo_variant)
                summary_count = summary

            s = score(pred, truth)
            count_err = abs(len(pred) - len(truth))
            rows.append({
                "variant": name,
                "detector": f"YOLO-{args.yolo_variant}" if det == "hybrid" else det,
                "seconds": round(secs, 2),
                "count_error": count_err,
                **s
            })
            model_lbl = f"YOLO-{args.yolo_variant.split('-')[0]}" if det == "hybrid" else det
            print(f"{name:11s} {model_lbl:15s} found {s['detected']:4d}/{s['labelled']:<4d} matched {s['matched']:4d}  "
                  f"P {s['precision']:.2f}  R {s['recall']:.2f}  F1 {s['f1']:.2f}  Err {count_err:2d}  ({secs:.2f}s)", flush=True)

    if args.json:
        args.json.write_text(json.dumps({"iou_threshold": IOU, "min_crown_diameter_m": args.min_crown, "rows": rows}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

