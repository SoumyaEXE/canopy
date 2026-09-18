"""Dataset Preparation & Fine-Tuning Script for YOLO11 Tree Crown Segmentation.

Reads polygons from `C:\\Users\\Soumya\\Desktop\\kml\\Odisha Polygon.kml`, fetches satellite imagery
tiles for each region, auto-labels tree crowns via the CANOPY vegetation pipeline, builds a YOLO
segmentation dataset format, and fine-tunes both `YOLO11s-seg` (main) and `YOLO11n-seg` (fallback).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image
from shapely.geometry import Polygon

# Ensure backend directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline import crowns, tiles, vegetation


def parse_kml_polygons(kml_path: str | Path) -> list[Polygon]:
    """Parse KML file and return a list of Shapely Polygons (lon, lat)."""
    tree = ET.parse(str(kml_path))
    root = tree.getroot()
    ns = {"kml": "http://www.opengis.net/kml/2.2"}

    polygons = []
    for coords_elem in root.findall(".//kml:coordinates", ns):
        text = coords_elem.text.strip() if coords_elem.text else ""
        pts = []
        for coord in text.split():
            parts = [float(p) for p in coord.split(",") if p.strip()]
            if len(parts) >= 2:
                pts.append((parts[0], parts[1]))
        if len(pts) >= 3:
            try:
                poly = Polygon(pts)
                if poly.is_valid and poly.area > 0:
                    polygons.append(poly)
            except Exception:
                continue
    return polygons


def generate_yolo_dataset(
    polygons: list[Polygon],
    dataset_dir: Path,
    zoom: int = 18,
    max_scenes: int = 10,
    val_split: float = 0.2,
) -> Path:
    """Fetch imagery, run auto-annotation using canopy mask + blob markers, and save YOLO dataset."""
    train_img_dir = dataset_dir / "images" / "train"
    val_img_dir = dataset_dir / "images" / "val"
    train_lbl_dir = dataset_dir / "labels" / "train"
    val_lbl_dir = dataset_dir / "labels" / "val"

    for d in [train_img_dir, val_img_dir, train_lbl_dir, val_lbl_dir]:
        d.mkdir(parents=True, exist_ok=True)

    sample_count = 0
    print(f"[*] Processing {len(polygons)} KML polygons to build training dataset...")

    for poly_idx, poly in enumerate(polygons[:max_scenes]):
        try:
            print(f"[*] Fetching scene for polygon {poly_idx + 1}/{min(len(polygons), max_scenes)}...")
            scene = tiles.fetch_scene(poly, zoom=zoom)
            rgb = scene.rgb
            h, w = rgb.shape[:2]
            if h < 64 or w < 64:
                continue

            index = vegetation.compute_index("exg", rgb, scene.nir)
            aoi = vegetation.aoi_mask(poly, scene.transform, scene.crs, (h, w))
            if aoi.sum() == 0:
                continue

            otsu = vegetation.otsu_with_confidence(index[aoi])
            threshold = otsu["otsu_value"]
            canopy, _ = vegetation.canopy_mask(index, aoi, scene.m_per_px, threshold)

            labels, distance, info = crowns.segment_blobs(
                index, rgb, threshold, canopy, scene.m_per_px, 2.0
            )

            # Extract bounding boxes for detected crowns
            from scipy import ndimage as ndi

            label_boxes = []
            for lab in range(1, labels.max() + 1):
                mask_lab = labels == lab
                if not mask_lab.any():
                    continue
                rows, cols = np.where(mask_lab)
                ymin, ymax = rows.min(), rows.max()
                xmin, xmax = cols.min(), cols.max()
                if (xmax - xmin) < 2 or (ymax - ymin) < 2:
                    continue
                # Normalize to [0, 1] for YOLO format: class_id x_center y_center width height
                xc = ((xmin + xmax) / 2.0) / w
                yc = ((ymin + ymax) / 2.0) / h
                bw = (xmax - xmin) / w
                bh = (ymax - ymin) / h
                label_boxes.append((xc, yc, bw, bh))

            if not label_boxes:
                continue

            is_val = (sample_count % int(1 / val_split)) == 0 if val_split > 0 else False
            target_img_dir = val_img_dir if is_val else train_img_dir
            target_lbl_dir = val_lbl_dir if is_val else train_lbl_dir

            file_stem = f"odisha_poly_{poly_idx:03d}"
            img_path = target_img_dir / f"{file_stem}.jpg"
            lbl_path = target_lbl_dir / f"{file_stem}.txt"

            img8 = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
            Image.fromarray(img8).save(img8_path := img_path, quality=95)

            with open(lbl_path, "w", encoding="utf-8") as f:
                for xc, yc, bw, bh in label_boxes:
                    f.write(f"0 {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}\n")

            sample_count += 1
            print(f"    -> Generated sample {file_stem} ({len(label_boxes)} crowns)")

        except Exception as exc:
            print(f"[!] Warning: Failed to process polygon {poly_idx}: {exc}")
            continue

    # Write data.yaml
    yaml_path = dataset_dir / "data.yaml"
    yaml_content = f"""path: {dataset_dir.as_posix()}
train: images/train
val: images/val
names:
  0: tree
"""
    yaml_path.write_text(yaml_content, encoding="utf-8")
    print(f"[+] Dataset created at {dataset_dir} with {sample_count} samples.")
    return yaml_path


def train_yolo_models(
    data_yaml: Path,
    output_models_dir: Path,
    epochs: int = 5,
    imgsz: int = 400,
    batch: int = 4,
):
    """Train YOLO11s-seg and YOLO11n-seg using ultralytics."""
    from ultralytics import YOLO

    output_models_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = output_models_dir / "runs"

    models_to_train = [
        ("yolo11s-seg.pt", "yolo11s-seg-odisha.pt"),
        ("yolo11n-seg.pt", "yolo11n-seg-odisha.pt"),
    ]

    for base_weights, target_filename in models_to_train:
        print(f"\n=======================================================")
        print(f"[*] Starting fine-tuning for {base_weights} -> {target_filename}...")
        print(f"=======================================================")
        try:
            model = YOLO(base_weights)
            res = model.train(
                data=str(data_yaml),
                epochs=epochs,
                imgsz=imgsz,
                batch=batch,
                project=str(runs_dir),
                name=target_filename.replace(".pt", ""),
                verbose=True,
            )
            # Find best.pt and copy to output_models_dir
            save_path = runs_dir / target_filename.replace(".pt", "") / "weights" / "best.pt"
            dest_path = output_models_dir / target_filename
            if save_path.is_file():
                shutil.copy(save_path, dest_path)
                print(f"[+] Saved fine-tuned weights to {dest_path}")
            else:
                print(f"[!] Warning: best.pt not found at {save_path}")
        except Exception as exc:
            print(f"[!] Error fine-tuning {base_weights}: {exc}")


def main():
    parser = argparse.ArgumentParser(description="Train YOLO11 tree detection models using KML polygons.")
    parser.add_argument(
        "--kml-path",
        default=r"C:\Users\Soumya\Desktop\kml\Odisha Polygon.kml",
        help="Path to Odisha Polygon.kml file",
    )
    parser.add_argument(
        "--dataset-dir",
        default=str(Path(__file__).resolve().parent.parent / "data" / "odisha_dataset"),
        help="Directory to generate dataset",
    )
    parser.add_argument(
        "--models-dir",
        default=str(Path(__file__).resolve().parent.parent / "data" / "models"),
        help="Directory to save trained model weights",
    )
    parser.add_argument("--epochs", type=int, default=3, help="Number of training epochs")
    parser.add_argument("--imgsz", type=int, default=400, help="Image size for training")
    parser.add_argument("--batch", type=int, default=2, help="Batch size")
    parser.add_argument("--max-scenes", type=int, default=5, help="Max polygons to process for dataset")

    args = parser.parse_args()

    polygons = parse_kml_polygons(args.kml_path)
    if not polygons:
        print(f"[!] No valid polygons found in {args.kml_path}")
        sys.exit(1)

    print(f"[+] Loaded {len(polygons)} polygons from {args.kml_path}")

    dataset_path = Path(args.dataset_dir)
    models_path = Path(args.models_dir)

    data_yaml = generate_yolo_dataset(
        polygons,
        dataset_path,
        zoom=18,
        max_scenes=args.max_scenes,
    )

    train_yolo_models(
        data_yaml,
        models_path,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
    )


if __name__ == "__main__":
    main()
