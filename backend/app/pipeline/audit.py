"""Stage 9: output files and the reproducibility bundle."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.segmentation import find_boundaries

BUCKET_RGB = {"high": (34, 197, 94), "medium": (245, 158, 11), "low": (239, 68, 68)}
EMERALD = (16, 185, 129)

CSV_FIELDS = [
    "id",
    "centroid_lon",
    "centroid_lat",
    "area_m2",
    "equivalent_diameter_m",
    "perimeter_m",
    "eccentricity",
    "solidity",
    "touches_edge",
    "height_m",
    "shadow_length_m",
    "height_reason",
    "confidence",
    "confidence_bucket",
    "signal_shape",
    "signal_size",
    "signal_separation",
    "signal_shadow",
    "detector_score",
]


def dumps_deterministic(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def crown_feature(c: dict) -> dict:
    props = {
        "id": c["id"],
        "centroid_px": c["centroid_px"],
        "centroid_lonlat": c["centroid_lonlat"],
        "area_m2": c["area_m2"],
        "equivalent_diameter_m": c["equivalent_diameter_m"],
        "perimeter_m": c["perimeter_m"],
        "eccentricity": c["eccentricity"],
        "solidity": c["solidity"],
        "touches_edge": c["touches_edge"],
        "height_m": c.get("height_m"),
        "shadow_length_m": c.get("shadow_length_m"),
        "height_reason": c.get("height_reason"),
        "confidence": c["confidence"],
        "confidence_bucket": c["confidence_bucket"],
        "signals": c["signals"],
        "detector_score": c.get("detector_score"),
        "low_confidence_reason": c.get("low_confidence_reason"),
    }
    return {"type": "Feature", "id": c["id"], "geometry": c["polygon"], "properties": props}


def rejected_feature(r: dict) -> dict:
    return {
        "type": "Feature",
        "id": r["id"],
        "geometry": r["polygon"],
        "properties": {"id": r["id"], "area_m2": r["area_m2"], "reason": r["reason"], "centroid_lonlat": r["centroid_lonlat"]},
    }


def write_geojson(path: Path, features: list[dict]) -> None:
    fc = {"type": "FeatureCollection", "features": [f for f in features if f["geometry"] is not None]}
    path.write_text(dumps_deterministic(fc), encoding="utf-8")


def write_csv(path: Path, crowns: list[dict]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, lineterminator="\n")
    w.writeheader()
    for c in crowns:
        w.writerow(
            {
                "id": c["id"],
                "centroid_lon": c["centroid_lonlat"][0],
                "centroid_lat": c["centroid_lonlat"][1],
                "area_m2": c["area_m2"],
                "equivalent_diameter_m": c["equivalent_diameter_m"],
                "perimeter_m": c["perimeter_m"],
                "eccentricity": c["eccentricity"],
                "solidity": c["solidity"],
                "touches_edge": c["touches_edge"],
                "height_m": "" if c.get("height_m") is None else c["height_m"],
                "shadow_length_m": "" if c.get("shadow_length_m") is None else c["shadow_length_m"],
                "height_reason": c.get("height_reason") or "",
                "confidence": c["confidence"],
                "confidence_bucket": c["confidence_bucket"],
                "signal_shape": c["signals"]["shape"],
                "signal_size": c["signals"]["size"],
                "signal_separation": c["signals"]["separation"],
                "signal_shadow": c["signals"]["shadow"],
                "detector_score": "" if c.get("detector_score") is None else c["detector_score"],
            }
        )
    path.write_text(buf.getvalue(), encoding="utf-8")


# Images for the map and Pipeline tab are strided down to at most this many pixels on the long side, so a
# large area still renders in a browser (WebGL textures) and stays small on disk. The audit mask stays full size.
DISPLAY_MAX_PX = 6000


def display_step(shape: tuple[int, int]) -> int:
    return max(1, int(np.ceil(max(shape) / DISPLAY_MAX_PX)))


def _save(img: Image.Image, path: Path) -> None:
    # PNG optimisation is slow on very large images and gains little there.
    img.save(path, optimize=img.width * img.height <= 4_000_000)


def write_images(job_dir: Path, rgb: np.ndarray, canopy: np.ndarray, aoi: np.ndarray, labels: np.ndarray, crowns: list[dict]) -> None:
    _save(Image.fromarray((canopy.astype(np.uint8) * 255)), job_dir / "canopy_mask.png")
    k = display_step(canopy.shape)
    rgb, canopy, aoi, labels = rgb[::k, ::k], canopy[::k, ::k], aoi[::k, ::k], labels[::k, ::k]
    img8 = (np.clip(rgb, 0, 1) * 255).round().astype(np.uint8)
    _save(Image.fromarray(img8), job_dir / "imagery.png")

    layer = np.zeros((*canopy.shape, 4), dtype=np.uint8)
    layer[canopy] = (*EMERALD, 255)
    _save(Image.fromarray(layer, "RGBA"), job_dir / "canopy_layer.png")

    overlay = img8.copy()
    bucket_of = np.zeros(int(labels.max()) + 1, dtype=np.uint8)
    for c in crowns:
        bucket_of[c["label"]] = {"high": 1, "medium": 2, "low": 3}[c["confidence_bucket"]]
    kept = bucket_of[labels]
    bounds = find_boundaries(np.where(kept > 0, labels, 0), mode="inner")
    for code, name in ((1, "high"), (2, "medium"), (3, "low")):
        overlay[bounds & (kept == code)] = BUCKET_RGB[name]
    aoi_edge = find_boundaries(aoi, mode="inner")
    overlay[aoi_edge] = (255, 255, 255)
    _save(Image.fromarray(overlay), job_dir / "overlay.png")


def summary_text(result: dict) -> str:
    s, p = result["summary"], result["provenance"]
    lo, hi = s["crown_count_range"]
    cb = s["confidence_breakdown"]
    lines = [
        "CANOPY analysis summary",
        "=======================",
        f"Job: {result['job_id']}",
        f"Created (UTC): {result['created_utc']}",
        "",
        "Most defensible numbers (depend only on the threshold and the resolution):",
        f"  AOI area:        {s['aoi_area_ha']:.1f} ha",
        f"  Canopy area:     {s['canopy_area_ha']:.1f} ha",
        f"  Canopy cover:    {s['canopy_cover_pct']:.1f} %",
        "",
        "Crown count (more assumptions, less certain):",
        f"  {s['crown_count']} crowns detected. Plausible range {lo} to {hi}.",
        f"  Confidence: {cb['high']} high, {cb['medium']} medium, {cb['low']} low.",
        f"  {s['rejected_regions']} regions rejected by size or shape filters (kept in crowns audit, not counted).",
        "",
    ]
    if s["height_available"]:
        lines.append(
            f"Height: estimated for {s['height_measured_count']} of {s['crown_count']} crowns "
            f"({s['height_measured_pct']:.0f} percent). Mean {s['height_mean_m']} m, 90th percentile {s['height_p90_m']} m."
        )
        lines.append("  Remaining crowns had occluded or unmeasurable shadows.")
    else:
        lines.append(f"Height: unavailable. {s['height_unavailable_reason']}")
    lines += [
        "",
        "How these were computed:",
        f"  Resolution: {p['m_per_px']:.4f} m per pixel ({p['resolution_source']}).",
        f"  Vegetation index: {p['veg_index']}; threshold {p['threshold_value']:.4f} ({p['threshold_mode']}, "
        f"threshold confidence {p['threshold_confidence']}).",
        "  Canopy area = canopy pixel count × (m per pixel)².",
        "  Crowns: distance transform + marker-controlled watershed, filtered by size and solidity.",
        "",
        "Warnings:",
        *[f"  - {w}" for w in result["warnings"]],
        "",
        "This tool does not estimate carbon, biomass or credits. See LIMITATIONS.md.",
    ]
    return "\n".join(lines) + "\n"


def write_bundle(job_dir: Path, manifest: dict, result: dict, limitations_md: str) -> Path:
    (job_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (job_dir / "summary.txt").write_text(summary_text(result), encoding="utf-8")
    (job_dir / "LIMITATIONS.md").write_text(limitations_md, encoding="utf-8")
    zpath = job_dir / "audit.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in ["manifest.json", "crowns.geojson", "rejected.geojson", "crowns.csv", "canopy_mask.png", "overlay.png", "summary.txt", "LIMITATIONS.md"]:
            f = job_dir / name
            if f.exists():
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, f.read_bytes())
    return zpath


# ---- pipeline stage images ----------------------------------------------------------------------------
# Every stage image has the imagery's exact pixel grid, so the frontend can stack it over imagery.png.

_VIRIDIS = np.array(
    [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)], dtype=np.float64
)
REJECT_RGB = (148, 163, 184)
BOX_RGB = (250, 204, 21)


def _viridis_lut() -> np.ndarray:
    v = np.linspace(0.0, 1.0, 256) * (len(_VIRIDIS) - 1)
    i = np.minimum(v.astype(np.int64), len(_VIRIDIS) - 2)
    f = (v - i)[:, None]
    return (_VIRIDIS[i] * (1 - f) + _VIRIDIS[i + 1] * f).round().astype(np.uint8)


_LUT = _viridis_lut()


def _ramp(v: np.ndarray) -> np.ndarray:
    """Map [0, 1] to a 5-stop viridis approximation through a 256-entry lookup table (1 byte per pixel of temp)."""
    q = (np.clip(np.nan_to_num(v, nan=0.0), 0.0, 1.0) * 255).astype(np.uint8)
    return _LUT[q]


def _stretch(a: np.ndarray, where: np.ndarray) -> np.ndarray:
    vals = a[where] if where.any() else a.ravel()
    lo, hi = np.percentile(vals, 1), np.percentile(vals, 99)
    return (a - lo) / (hi - lo if hi > lo else 1.0)


def _rgba(rgb: np.ndarray, alpha: np.ndarray | int = 255) -> np.ndarray:
    out = np.zeros((*rgb.shape[:2], 4), dtype=np.uint8)
    out[..., :3] = rgb
    out[..., 3] = alpha
    return out


def _label_colours(n: int) -> np.ndarray:
    """Distinct, deterministic colours per label (golden-angle hue walk)."""
    k = np.arange(n + 1, dtype=np.float64)
    hue = (k * 0.618033988749895) % 1.0
    h6 = hue * 6
    x = 1 - np.abs(h6 % 2 - 1)
    c = np.zeros((n + 1, 3))
    for lo, (r, g, b) in enumerate([(1, "x", 0), ("x", 1, 0), (0, 1, "x"), (0, "x", 1), ("x", 0, 1), (1, 0, "x")]):
        sel = (h6 >= lo) & (h6 < lo + 1)
        for ch, v in enumerate((r, g, b)):
            c[sel, ch] = x[sel] if v == "x" else v
    rgb = (0.35 + 0.6 * c) * 255
    rgb[0] = 0
    return rgb.round().astype(np.uint8)


def _draw_rect(img: np.ndarray, x0: float, y0: float, x1: float, y1: float, colour, t: int) -> None:
    h, w = img.shape[:2]
    c0, r0 = max(0, int(x0)), max(0, int(y0))
    c1, r1 = min(w - 1, int(x1)), min(h - 1, int(y1))
    if c1 <= c0 or r1 <= r0:
        return
    img[r0 : r0 + t, c0 : c1 + 1] = colour
    img[max(r0, r1 - t + 1) : r1 + 1, c0 : c1 + 1] = colour
    img[r0 : r1 + 1, c0 : c0 + t] = colour
    img[r0 : r1 + 1, max(c0, c1 - t + 1) : c1 + 1] = colour


def write_stage_images(
    job_dir: Path,
    *,
    index: np.ndarray,
    raw: np.ndarray,
    canopy: np.ndarray,
    aoi: np.ndarray,
    response: np.ndarray | None,
    markers: np.ndarray | None,
    boxes: np.ndarray | None,
    labels: np.ndarray,
    crowns: list[dict],
    rejected: list[dict],
) -> list[str]:
    """Write stage_*.png and return the file names written, in pipeline order."""
    k = display_step(canopy.shape)
    if k > 1:
        index, raw, canopy, aoi, labels = index[::k, ::k], raw[::k, ::k], canopy[::k, ::k], aoi[::k, ::k], labels[::k, ::k]
        response = response[::k, ::k] if response is not None else None
        markers = markers // k if markers is not None else None
        boxes = np.column_stack([boxes[:, :4] / k, boxes[:, 4]]) if boxes is not None else None
    h, w = canopy.shape
    written: list[str] = []
    dot = max(1, round(min(h, w) / 250))

    def save(name: str, arr: np.ndarray) -> None:
        _save(Image.fromarray(arr, "RGBA"), job_dir / name)
        written.append(name)

    alpha_aoi = np.where(aoi, 255, 60).astype(np.uint8)
    save("stage_index.png", _rgba(_ramp(_stretch(index, aoi)), alpha_aoi))

    thr = np.zeros((h, w, 4), dtype=np.uint8)
    thr[raw] = (*EMERALD, 255)
    thr[~raw & aoi] = (15, 23, 42, 170)
    save("stage_threshold.png", thr)

    msk = np.zeros((h, w, 4), dtype=np.uint8)
    msk[canopy] = (*EMERALD, 255)
    msk[raw & ~canopy] = (239, 68, 68, 255)  # removed by morphology
    msk[~canopy & ~raw & aoi] = (15, 23, 42, 170)
    save("stage_mask.png", msk)

    if boxes is not None:
        det = np.zeros((h, w, 4), dtype=np.uint8)
        t = max(2, round(min(h, w) / 300))
        for x0, y0, x1, y1, s in boxes:
            a = int(110 + 145 * float(s))
            _draw_rect(det, x0, y0, x1, y1, (*BOX_RGB, a), t)
        save("stage_detections.png", det)
    elif response is not None:
        mk = _rgba(_ramp(_stretch(response, canopy)), np.where(canopy, 235, 0).astype(np.uint8))
        for r, c in markers if markers is not None else []:
            mk[max(0, r - dot) : r + dot + 1, max(0, c - dot) : c + dot + 1] = (255, 255, 255, 255)
        save("stage_markers.png", mk)

    lab = _rgba(_label_colours(int(labels.max()))[labels], np.where(labels > 0, 230, 0).astype(np.uint8))
    lab[find_boundaries(labels, mode="inner")] = (15, 23, 42, 255)
    save("stage_segments.png", lab)

    fin = np.zeros((h, w, 4), dtype=np.uint8)
    kept_codes = np.zeros(int(labels.max()) + 1, dtype=np.uint8)
    for c in crowns:
        kept_codes[c["label"]] = {"high": 1, "medium": 2, "low": 3}[c["confidence_bucket"]]
    for r in rejected:
        kept_codes[r["label"]] = 4
    code = kept_codes[labels]
    bounds = find_boundaries(labels, mode="inner")
    for k, rgb in ((1, BUCKET_RGB["high"]), (2, BUCKET_RGB["medium"]), (3, BUCKET_RGB["low"]), (4, REJECT_RGB)):
        fin[(code == k) & ~bounds] = (*rgb, 90)
        fin[(code == k) & bounds] = (*rgb, 255)
    save("stage_crowns.png", fin)
    return written
