"""Build a YOLO segmentation dataset of tree crowns from the Odisha polygons and sample screenshots.

High-resolution teacher, low-resolution student:
    1. Sample windows fully inside each KML polygon and fetch them at zoom 18 (~0.56 m/px in Odisha;
       Esri has no zoom-19 imagery there, only "Map data not yet available" placeholders).
    2. Label every kept crown with the classical crown finder (canopy mask + LoG blob markers + watershed).
    3. Write each chip sharp AND degraded 2x and 3x (averaged down to ~1.1 m and ~1.7 m, blurred,
       JPEG-compressed, then scaled back up), keeping the labels from the sharp image. The student
       learns to find crowns in blurry imagery using answers worked out on the sharper imagery.
       Scaling back up keeps crowns well above YOLO's 8 px stride; inference does the same by
       resampling coarse imagery to ~0.5 m before detection.

Plain screenshots (PNG/JPG, no location) are labelled at their own scale and added the same way.

    python scripts/build_tree_dataset.py                       # default paths
    python scripts/build_tree_dataset.py --windows 6 --out data/tree_dataset
"""

from __future__ import annotations

import argparse
import io
import math
import random
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from shapely.geometry import box
from shapely.ops import transform as shp_transform

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import crowns, geo, ingest, tiles, vegetation  # noqa: E402
from scripts.train_yolo11 import parse_kml_polygons  # noqa: E402

CHIP = 416
WINDOW_PX = 416  # one chip per degradation level per window (~233 m square at zoom 18)
MIN_D_M = 3.0
MIN_LABEL_PX = 6
SEED = 20260918


def teacher(rgb: np.ndarray, aoi: np.ndarray, m: float) -> np.ndarray:
    """Classical crown labels (int32 label image, 0 = background) for one sharp scene."""
    index = vegetation.compute_index("exg", rgb, None)
    thr = vegetation.otsu_with_confidence(index[aoi])["otsu_value"]
    canopy, _ = vegetation.canopy_mask(index, aoi, m, thr)
    labels, distance, _ = crowns.segment_blobs(index, rgb, thr, canopy, m, MIN_D_M)
    kept, _, _ = crowns.extract(labels, distance, aoi, (m, 0, 0, 0, -m, 0), "EPSG:3857", m, MIN_D_M / 2)
    keep = np.zeros(int(labels.max()) + 1, dtype=bool)
    keep[[c["label"] for c in kept]] = True
    return np.where(keep[labels], labels, 0)


def polygons_for(lab: np.ndarray, factor: int) -> list[str]:
    """YOLO-seg label lines for every crown in a label crop, after shrinking it by `factor`."""
    from skimage.measure import find_contours, regionprops

    h, w = lab.shape
    oh, ow = h // factor, w // factor
    lines = []
    for rp in regionprops(lab):
        if rp.area < MIN_LABEL_PX * factor * factor:
            continue
        r0, c0, _, _ = rp.bbox
        cs = find_contours(np.pad(rp.image, 1).astype(np.uint8), 0.5)
        if not cs:
            continue
        ring = max(cs, key=len)
        step = max(1, len(ring) // 20)
        pts = ring[::step] - 1 + np.array([r0, c0])
        if len(pts) < 3:
            continue
        xy = []
        for r, c in pts:
            xy += [f"{min(max(c / factor / ow, 0), 1):.5f}", f"{min(max(r / factor / oh, 0), 1):.5f}"]
        lines.append("0 " + " ".join(xy))
    return lines


def degrade(img8: np.ndarray, factor: int, rng: random.Random) -> Image.Image:
    im = Image.fromarray(img8)
    size = im.size
    if factor > 1:
        im = im.resize((max(1, im.width // factor), max(1, im.height // factor)), Image.Resampling.BOX)
        im = im.resize(size, Image.Resampling.BICUBIC)
    if rng.random() < 0.5:
        im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.9)))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=rng.randint(55, 90))
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def write_chips(stem: str, img8: np.ndarray, lab: np.ndarray, out: Path, split: str, rng: random.Random, factors=(1, 2, 3)) -> int:
    n = 0
    h, w = lab.shape
    for f in factors:
        size = CHIP
        if h < size // 2 or w < size // 2:
            continue
        for r in range(0, max(1, h - size // 2), size):
            for c in range(0, max(1, w - size // 2), size):
                sl = (slice(r, min(h, r + size)), slice(c, min(w, c + size)))
                sub = lab[sl]
                lines = polygons_for(sub, 1)
                if len(lines) < 3:
                    continue
                name = f"{stem}_x{f}_{r}_{c}"
                degrade(img8[sl], f, rng).save(out / "images" / split / f"{name}.jpg", quality=95)
                (out / "labels" / split / f"{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
                n += 1
    return n


def windows_in(poly, zoom: int, k: int, rng: random.Random) -> list:
    """Up to k square windows (lon/lat polygons) of WINDOW_PX pixels lying fully inside the polygon."""
    to_m = lambda x, y, z=None: geo.lonlat_to_mercator(x, y)  # noqa: E731
    to_ll = lambda x, y, z=None: geo.mercator_to_lonlat(x, y)  # noqa: E731
    pm = shp_transform(to_m, poly)
    side = WINDOW_PX * geo.mercator_nominal_px(zoom)
    minx, miny, maxx, maxy = pm.bounds
    out, tries = [], 0
    while len(out) < k and tries < 1500:
        tries += 1
        x, y = rng.uniform(minx, maxx - side), rng.uniform(miny, maxy - side)
        b = box(x, y, x + side, y + side)
        if pm.intersection(b).area >= 0.8 * b.area and not any(b.intersects(o) for o in out):
            out.append(b)
    return [shp_transform(to_ll, b) for b in out]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kml", default=r"C:\Users\Soumya\Desktop\kml\Odisha Polygon.kml")
    ap.add_argument("--images", nargs="*", default=[r"C:\Users\Soumya\Desktop\kml\image(2).png", r"C:\Users\Soumya\Desktop\kml\test png.png"])
    ap.add_argument("--image-m", type=float, default=0.3, help="assumed ground resolution of the plain images")
    ap.add_argument("--windows", type=int, default=5, help="windows per polygon")
    ap.add_argument("--zoom", type=int, default=18)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "tree_dataset")
    args = ap.parse_args()

    rng = random.Random(SEED)
    if args.out.exists():
        shutil.rmtree(args.out)
    for s in ("train", "val"):
        (args.out / "images" / s).mkdir(parents=True)
        (args.out / "labels" / s).mkdir(parents=True)

    polys = parse_kml_polygons(args.kml)
    print(f"{len(polys)} polygons")
    total = {"train": 0, "val": 0}
    for i, poly in enumerate(polys):
        split = "val" if i % 6 == 5 else "train"  # whole polygons held out, so val is unseen ground
        for j, win in enumerate(windows_in(poly, args.zoom, args.windows, rng)):
            try:
                scene = tiles.fetch_scene(win, args.zoom)
            except Exception as exc:  # a missing tile skips one window, not the build
                print(f"  poly {i} win {j}: {exc}")
                continue
            h, w = scene.rgb.shape[:2]
            if tiles.placeholder_fraction(scene.rgb) > 0.02:
                print(f"  poly {i} win {j}: no imagery (placeholder tiles), skipped")
                continue
            aoi = np.ones((h, w), dtype=bool)
            lab = teacher(scene.rgb, aoi, scene.m_per_px)
            img8 = (np.clip(scene.rgb, 0, 1) * 255).round().astype(np.uint8)
            n = write_chips(f"od{i:02d}w{j}", img8, lab, args.out, split, rng, factors=(1, 2, 3))
            total[split] += n
            print(f"  poly {i:2d} win {j}: {int(lab.max() and len(np.unique(lab)) - 1)} crowns -> {n} chips ({split})", flush=True)

    for k, p in enumerate(args.images):
        raw = Path(p).read_bytes()
        parsed = ingest.ParsedInput(kind="image", aoi_lonlat=None, raster_bytes=raw, sha256=ingest.sha256_bytes(raw), filename=Path(p).name)
        scene = ingest.load_image(parsed, args.image_m)
        h, w = scene.rgb.shape[:2]
        lab = teacher(scene.rgb, np.ones((h, w), dtype=bool), scene.m_per_px)
        img8 = (np.clip(scene.rgb, 0, 1) * 255).round().astype(np.uint8)
        n = write_chips(f"png{k}", img8, lab, args.out, "train", rng, factors=(1, 2))
        total["train"] += n
        print(f"  {Path(p).name}: {len(np.unique(lab)) - 1} crowns -> {n} chips", flush=True)

    (args.out / "data.yaml").write_text(f"path: {args.out.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n  0: tree\n", encoding="utf-8")
    print(f"done: {total}")


if __name__ == "__main__":
    main()
