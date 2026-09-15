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
            }
        )
    path.write_text(buf.getvalue(), encoding="utf-8")


def write_images(job_dir: Path, rgb: np.ndarray, canopy: np.ndarray, aoi: np.ndarray, labels: np.ndarray, crowns: list[dict]) -> None:
    img8 = (np.clip(rgb, 0, 1) * 255).round().astype(np.uint8)
    Image.fromarray(img8).save(job_dir / "imagery.png", optimize=True)
    Image.fromarray((canopy.astype(np.uint8) * 255)).save(job_dir / "canopy_mask.png", optimize=True)

    layer = np.zeros((*canopy.shape, 4), dtype=np.uint8)
    layer[canopy] = (*EMERALD, 255)
    Image.fromarray(layer, "RGBA").save(job_dir / "canopy_layer.png", optimize=True)

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
    Image.fromarray(overlay).save(job_dir / "overlay.png", optimize=True)


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
