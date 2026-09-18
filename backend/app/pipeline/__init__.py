"""run_pipeline(): the orchestrator. Each stage reports progress by name."""

from __future__ import annotations


import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from .. import config
from . import audit, confidence, crowns, detector, geo, ingest, shadows, tiles, vegetation
from .errors import PipelineError

STAGES = [
    ("validating_input", "Validating input"),
    ("acquiring_imagery", "Fetching imagery tiles"),
    ("computing_index", "Computing vegetation index"),
    ("building_mask", "Building canopy mask"),
    ("segmenting_crowns", "Segmenting crowns"),
    ("measuring_shadows", "Measuring shadows"),
    ("scoring_confidence", "Scoring confidence"),
    ("writing_outputs", "Writing outputs and audit bundle"),
]

LIMITATIONS_MD = (Path(__file__).resolve().parent.parent / "LIMITATIONS.md").read_text(encoding="utf-8")

Progress = Callable[[str, str], None]


def _lib_versions() -> dict:
    import rasterio
    import scipy
    import shapely
    import skimage

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "scikit-image": skimage.__version__,
        "rasterio": rasterio.__version__,
        "gdal": rasterio.__gdal_version__,
        "shapely": shapely.__version__,
    }


def _corners_lonlat(transform: tuple, crs: str, shape: tuple[int, int]) -> list[list[float]]:
    to_ll = crowns._to_lonlat_fn(crs)
    h, w = shape
    out = []
    for col, row in ((0, 0), (w, 0), (w, h), (0, h)):
        x, y = crowns.pixel_to_crs(transform, col, row)
        lon, lat = to_ll(x, y)
        out.append([round(lon, 7), round(lat, 7)])
    return out


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PipelineError("bad_datetime", f"The acquisition time '{s}' is not a valid ISO 8601 date-time.") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def run_pipeline(
    job_id: str,
    job_dir: Path,
    parsed: ingest.ParsedInput,
    params: dict,
    progress: Progress,
    created_utc: str | None = None,
) -> dict:
    job_dir.mkdir(parents=True, exist_ok=True)
    created_utc = created_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    min_d = float(params["min_crown_diameter_m"])
    veg = params["veg_index"]
    zoom = int(params["tile_zoom"])
    warnings: list[str] = []

    # ---- 0. Ingest ----------------------------------------------------------------
    progress("validating_input", "Checking the boundary and file")
    if parsed.aoi_lonlat is not None:
        ingest.validate_aoi(parsed.aoi_lonlat)

    # ---- 1-2. Imagery + grounding -------------------------------------------------
    if parsed.kind == "geotiff":
        progress("acquiring_imagery", "Reading GeoTIFF and grounding pixel size")
        scene = ingest.load_geotiff(parsed, parsed.aoi_lonlat)
    else:
        progress("acquiring_imagery", f"Fetching {config.TILE_SOURCE_NAME} tiles at zoom {zoom}")
        scene = tiles.fetch_scene(parsed.aoi_lonlat, zoom)
        if zoom >= 19:
            warnings.append("Zoom 19 imagery is interpolated in many regions and may not add real detail over zoom 18.")
        spread = scene.audit["resolution_spread"]
        if spread["lat_span_deg"] > 0.05:
            warnings.append(
                f"The area spans {spread['lat_span_deg']:.3f}Â° of latitude, so pixel size varies by "
                f"{spread['relative_variation_pct']:.2f}% across it. Areas use the centroid resolution."
            )
    m = scene.m_per_px
    h, w = scene.rgb.shape[:2]
    if m > 1.0:
        warnings.append(
            f"This imagery is {m:.1f} m per pixel. Individual crowns under about {3 * m:.0f} m across cannot be resolved, "
            "so the crown count is a lower bound; canopy cover is still meaningful."
        )
    aoi = vegetation.aoi_mask(scene.aoi_lonlat, scene.transform, scene.crs, (h, w))
    if aoi.sum() == 0:
        raise PipelineError("aoi_empty_raster", "The boundary covers no pixels of the imagery.")

    # ---- 3. Vegetation index ------------------------------------------------------
    progress("computing_index", f"Computing {veg.upper()}")
    index = vegetation.compute_index(veg, scene.rgb, scene.nir)
    otsu = vegetation.otsu_with_confidence(index[aoi])
    if params["threshold_mode"] == "manual" and params.get("threshold_manual") is not None:
        threshold, mode = float(params["threshold_manual"]), "manual"
    else:
        threshold, mode = otsu["otsu_value"], "otsu"
    if otsu["confidence"] == "low":
        warnings.append("Low threshold confidence: scene may be uniform (mostly canopy or mostly bare), so the Otsu split is weak.")
    idx_vals = index[aoi]
    index_range = [round(float(np.percentile(idx_vals, 1)), 4), round(float(np.percentile(idx_vals, 99)), 4)]

    # ---- 4. Canopy mask -------------------------------------------------------------
    progress("building_mask", "Thresholding and cleaning the canopy mask")
    canopy, mask_info = vegetation.canopy_mask(index, aoi, m, threshold)
    canopy_px = int(canopy.sum())
    aoi_px = int(aoi.sum())
    canopy_area_m2 = canopy_px * m * m
    aoi_area_m2 = aoi_px * m * m
    cover_pct = 100.0 * canopy_px / aoi_px

    # ---- 5. Crowns ------------------------------------------------------------------
    # "hybrid" (shown as Auto): DeepForest where the imagery is fine enough for it, blob markers otherwise.
    wanted = params.get("detector", "hybrid")
    detector_used, boxes, marker_coords, marker_response = "classical", None, None, None
    if wanted == "hybrid":
        ok, why = detector.available()
        if not ok:
            warnings.append(f"The AI tree detector is not installed on this server ({why}), so classical blob detection was used.")
        elif m > detector.MAX_GSD_M:
            warnings.append(
                f"This imagery is {m:.2f} m per pixel. The AI tree detector was trained on 0.1 m imagery and is unreliable "
                f"above {detector.MAX_GSD_M} m, so classical blob detection was used instead (see the Pipeline tab)."
            )
        else:
            progress("segmenting_crowns", "Detecting trees with DeepForest")
            boxes, det_info = detector.detect(scene.rgb, m)
            progress("segmenting_crowns", "Shaping crown outlines from the canopy mask")
            labels, distance, hyb_info = detector.crowns_from_boxes(boxes, canopy, aoi, m)
            det_scores = hyb_info.pop("scores")
            seg_info = {"detector": "hybrid", **det_info, **hyb_info, **detector.model_version()}
            detector_used = "hybrid"
    if detector_used == "classical":
        progress("segmenting_crowns", "Finding crown centres and running watershed")
        labels, distance, seg_info = crowns.segment_blobs(index, scene.rgb, threshold, canopy, m, min_d)
        marker_coords = seg_info.pop("_marker_coords")
        marker_response = seg_info.pop("_response")
        seg_info = {"detector": "classical", **seg_info}
    min_d_filter = min(min_d, detector.MIN_CROWN_DIAMETER_M) if detector_used == "hybrid" else min_d / 2.0
    kept, rejected, filt_info = crowns.extract(labels, distance, aoi, scene.transform, scene.crs, m, min_d_filter)
    if detector_used == "hybrid":
        for c in kept:
            c["detector_score"] = round(det_scores.get(c["label"], 0.0), 4)

    # ---- 6. Shadows -----------------------------------------------------------------
    progress("measuring_shadows", "Tracing shadows for height")
    solar = {"sun_elevation_deg": None, "sun_azimuth_deg": None, "solar_source": None}
    height_reason = None
    shadow_info = None
    meta_sun = ingest.geotiff_solar_metadata(scene.audit.get("tags", {})) if parsed.kind == "geotiff" else None
    dt = _parse_dt(params.get("acquisition_datetime_utc"))
    if not params.get("enable_height", True):
        height_reason = "Height estimation turned off in the controls."
    elif meta_sun is not None:
        solar = {"sun_elevation_deg": meta_sun[0], "sun_azimuth_deg": meta_sun[1], "solar_source": "geotiff_metadata"}
    elif dt is not None:
        c = scene.aoi_lonlat.centroid
        el, az = shadows.solar_position(dt, c.y, c.x)
        solar = {
            "sun_elevation_deg": round(el, 3),
            "sun_azimuth_deg": round(az, 3),
            "solar_source": "computed_from_datetime",
            "acquisition_datetime_utc": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "algorithm": "NOAA solar position (Solar Calculator equations, with refraction)",
        }
    else:
        height_reason = "Height estimation unavailable: acquisition time unknown."

    height_enabled = height_reason is None
    if height_enabled:
        shadow_mask, sm_info = shadows.shadow_mask(scene.rgb, canopy, aoi)
        shadow_info = {**sm_info, **shadows.measure_heights(kept, labels, shadow_mask, m, solar["sun_elevation_deg"], solar["sun_azimuth_deg"])}
        if shadow_info["global_gate"]:
            height_reason = f"Height estimation unavailable: {shadow_info['global_gate']}."
            height_enabled = False
    if not height_enabled:
        for c in kept:
            c["height_m"], c["shadow_length_m"], c["height_reason"] = None, None, "unavailable"

    # ---- 7. Confidence --------------------------------------------------------------
    progress("scoring_confidence", "Scoring per-crown confidence")
    conf_info = confidence.score(kept, height_enabled)

    # ---- 8. Outputs -----------------------------------------------------------------
    progress("writing_outputs", "Writing GeoJSON, CSV, images and audit bundle")
    for i, c in enumerate(kept, start=1):
        c["id"] = i
    for i, r in enumerate(rejected, start=1):
        r["id"] = i
    crown_features = [audit.crown_feature(c) for c in kept]
    audit.write_geojson(job_dir / "crowns.geojson", crown_features)
    audit.write_geojson(job_dir / "rejected.geojson", [audit.rejected_feature(r) for r in rejected])
    audit.write_csv(job_dir / "crowns.csv", kept)
    audit.write_images(job_dir, scene.rgb, canopy, aoi, labels, kept)
    raw_mask = (index > threshold) & aoi
    stage_files = audit.write_stage_images(
        job_dir, index=index, raw=raw_mask, canopy=canopy, aoi=aoi, response=marker_response, markers=marker_coords,
        boxes=boxes, labels=labels, crowns=kept, rejected=rejected,
    )

    n = len(kept)
    areas = [c["area_m2"] for c in kept]
    diams = [c["equivalent_diameter_m"] for c in kept]
    heights = [c["height_m"] for c in kept if c.get("height_m") is not None]
    counts = conf_info["counts"]
    measured = len(heights)

    if rejected:
        warnings.append(f"{len(rejected)} regions were rejected by size or shape filters. Toggle the Rejected layer to see them.")
    if counts["low"]:
        warnings.append(f"{counts['low']} crowns have low confidence; these are most often merged crowns in dense canopy.")
    if height_enabled and n - measured:
        warnings.append(f"Height could not be measured for {n - measured} crowns due to shadow occlusion or unmeasurable shadows.")
    edge_n = sum(1 for c in kept if c["touches_edge"])
    if edge_n:
        warnings.append(f"{edge_n} crowns touch the area boundary; they are counted, but their areas are truncated.")
    if parsed.kind != "geotiff":
        warnings.append("Basemap imagery has no reliable acquisition date; the trees may have changed since capture.")

    summary = {
        "aoi_area_m2": round(aoi_area_m2, 1),
        "aoi_area_ha": round(aoi_area_m2 / 1e4, 2),
        "canopy_area_m2": round(canopy_area_m2, 1),
        "canopy_area_ha": round(canopy_area_m2 / 1e4, 2),
        "canopy_cover_pct": round(cover_pct, 1),
        "crown_count": n,
        "crown_count_range": conf_info["count_range"],
        "confidence_breakdown": counts,
        "rejected_regions": len(rejected),
        "edge_crowns": edge_n,
        "mean_crown_area_m2": round(float(np.mean(areas)), 1) if n else None,
        "median_crown_diameter_m": round(float(np.median(diams)), 1) if n else None,
        "height_available": height_enabled,
        "height_unavailable_reason": height_reason,
        "height_measured_count": measured,
        "height_measured_pct": round(100.0 * measured / n, 1) if n and height_enabled else 0.0,
        "height_mean_m": round(float(np.mean(heights)), 1) if heights else None,
        "height_p90_m": round(float(np.percentile(heights, 90)), 1) if heights else None,
        "heights_m": sorted(heights),
    }
    provenance = {
        "input_type": parsed.kind,
        "interpreted_as": scene.audit.get("interpreted_as"),
        "m_per_px": round(m, 5),
        "resolution_source": scene.audit.get("resolution_source"),
        "working_crs": scene.crs,
        "veg_index": veg,
        "index_p1_p99": index_range,
        "threshold_value": round(threshold, 5),
        "threshold_mode": mode,
        "otsu_value": round(otsu["otsu_value"], 5),
        "threshold_confidence": otsu["confidence"],
        "threshold_bimodality_coefficient": otsu["bimodality_coefficient"],
        "min_crown_diameter_m": min_d,
        "min_crown_area_m2": filt_info["min_crown_area_m2"],
        "max_crown_area_m2": filt_info["max_crown_area_m2"],
        "min_solidity": filt_info["min_solidity"],
        "morph_disk_radius_px": mask_info["morph_disk_radius_px"],
        "imagery_source": scene.audit.get("imagery_source", "Uploaded GeoTIFF"),
        "tile_zoom": scene.audit.get("tile_zoom"),
        "tile_fetch_utc": scene.audit.get("tile_fetch_utc"),
        "confidence_weights": conf_info["weights"],
        **solar,
    }
    result = {
        "job_id": job_id,
        "created_utc": created_utc,
        "summary": summary,
        "provenance": provenance,
        "aoi": geo.shape_to_geojson(scene.aoi_lonlat),
        "image_corners": _corners_lonlat(scene.transform, scene.crs, (h, w)),
        "warnings": warnings,
        "crowns_geojson_url": f"/api/jobs/{job_id}/crowns.geojson",
        "rejected_geojson_url": f"/api/jobs/{job_id}/rejected.geojson",
        "crowns_csv_url": f"/api/jobs/{job_id}/crowns.csv",
        "imagery_png_url": f"/api/jobs/{job_id}/imagery.png",
        "canopy_png_url": f"/api/jobs/{job_id}/canopy_layer.png",
        "overlay_png_url": f"/api/jobs/{job_id}/overlay.png",
        "audit_zip_url": f"/api/jobs/{job_id}/audit.zip",
    }
    result["pipeline"] = _pipeline_view(
        job_id, stage_files, detector_used, scene, parsed, veg, index_range, threshold, mode, otsu, raw_mask, canopy,
        aoi, mask_info, seg_info, filt_info, conf_info, cover_pct, n,
    )

    manifest = {
        "job_id": job_id,
        "created_utc": created_utc,
        "software": {"name": "CANOPY", "version": config.APP_VERSION, "git_sha": config.GIT_SHA},
        "library_versions": _lib_versions(),
        "input": {"type": parsed.kind, "filename": parsed.filename, "sha256": parsed.sha256},
        "aoi_geojson": result["aoi"],
        "aoi_area_m2_pixels": round(aoi_area_m2, 3),
        "aoi_area_m2_polygon_utm": round(geo.polygon_area_m2(scene.aoi_lonlat), 3),
        "raster": {"width": w, "height": h, "crs": scene.crs, "transform": [round(v, 9) for v in scene.transform]},
        "grounding": {k: v for k, v in scene.audit.items() if k != "tags"},
        "m_per_px": m,
        "parameters": params,
        "vegetation_index": {"name": veg, **otsu, "threshold_used": threshold, "threshold_mode": mode},
        "canopy_mask": mask_info,
        "segmentation": {**seg_info, **filt_info},
        "detector_used": detector_used,
        "solar": solar,
        "height": {"enabled": height_enabled, "unavailable_reason": height_reason, **(shadow_info or {})},
        "confidence": conf_info,
        "summary": summary,
        "warnings": warnings,
        "determinism": "No step uses randomness. Crown IDs follow watershed marker order (row, then column). JSON keys are sorted.",
    }
    audit.write_bundle(job_dir, manifest, result, LIMITATIONS_MD)
    (job_dir / "result.json").write_text(audit.dumps_deterministic(result), encoding="utf-8")
    return result


def _pipeline_view(job_id, files, detector_used, scene, parsed, veg, index_range, threshold, mode, otsu, raw_mask,
                   canopy, aoi, mask_info, seg_info, filt_info, conf_info, cover_pct, n) -> dict:
    """Plain-language description of each stage image, with the numbers that stage produced."""
    m = scene.m_per_px
    h, w = canopy.shape
    aoi_px = max(1, int(aoi.sum()))
    lo, hi = conf_info["count_range"]
    src = scene.audit.get("imagery_source", "Uploaded GeoTIFF")
    index_formula = "2g − r − b on chromatic coordinates" if veg == "exg" else veg.upper()
    removed_px = int((raw_mask & ~canopy).sum())
    hybrid = detector_used == "hybrid"
    stages = {
        "stage_index.png": (
            f"{veg.upper()} vegetation index",
            f"p1–p99 {index_range[0]} to {index_range[1]}",
            f"Each pixel's greenness from its colour alone ({index_formula}). "
            "Yellow is greenest, purple least green. Pixels outside the area are dimmed.",
            {"Index": veg.upper(), "Index p1 / p99": f"{index_range[0]} / {index_range[1]}", "Image": f"{w} × {h} px",
             "Resolution": f"{m:.3f} m/px"},
        ),
        "stage_threshold.png": (
            "Threshold",
            f"{mode} at {threshold:.3f}",
            "Pixels above the threshold are green. Otsu's method picks the split that best separates the two populations "
            "of index values; the bimodality coefficient says whether there really are two.",
            {"Threshold": f"{threshold:.4f} ({mode})", "Otsu value": f"{otsu['otsu_value']:.4f}",
             "Bimodality coefficient": otsu["bimodality_coefficient"], "Threshold confidence": otsu["confidence"],
             "Pixels above": f"{int(raw_mask.sum()):,} ({100 * raw_mask.sum() / aoi_px:.1f}% of area)"},
        ),
        "stage_mask.png": (
            "Cleaned canopy mask",
            f"{cover_pct:.1f}% canopy cover",
            "Opening then closing with a small disk removes speckle and fills pinholes; objects and holes under 1 m² go. "
            "Green is canopy, red is what the cleaning removed. Canopy area and cover come from this mask.",
            {"Disk radius": f"{mask_info['morph_disk_radius_px']} px ({mask_info['morph_disk_radius_m']} m)",
             "Canopy pixels": f"{int(canopy.sum()):,}", "Canopy cover": f"{cover_pct:.1f}%",
             "Removed by cleaning": f"{removed_px:,} px"},
        ),
        "stage_detections.png": (
            "AI tree detections",
            f"{seg_info.get('boxes_kept', 0)} trees found",
            "DeepForest, a RetinaNet trained on hand-labelled airborne imagery, draws a box around every tree it sees. "
            "Brighter boxes are more confident. Large images run as 400 px patches with 25% overlap, and duplicates "
            "across patches are merged by non-maximum suppression.",
            {"Model": seg_info.get("model", "—"),
             "Boxes (raw / kept)": f"{seg_info.get('boxes_raw', 0)} / {seg_info.get('boxes_kept', 0)}",
             "Score threshold": seg_info.get("score_threshold", "—"),
             "Upsampling": f"{seg_info.get('work_scale', 1)}×",
             "Working image": " × ".join(str(v) for v in seg_info.get("work_shape", [])[::-1]) + " px"},
        ),
        "stage_markers.png": (
            "Crown centres",
            f"{seg_info.get('markers', 0)} crown centres",
            "Sunlit crowns are brightest and greenest in the middle. A Laplacian-of-Gaussian blob detector, run at every "
            "crown size from half the minimum diameter up to the maximum, finds one peak per crown even where crowns touch. "
            "White dots are the crown centres that fall on canopy; each seeds one watershed region.",
            {"Blob radius range": f"{seg_info.get('blob_min_radius_m')}–{seg_info.get('blob_max_radius_m')} m",
             "Blobs found": seg_info.get("blobs_total", 0), "On canopy (markers)": seg_info.get("markers", 0),
             "Blob threshold": seg_info.get("blob_threshold")},
        ),
        "stage_segments.png": (
            "Crown segments",
            f"{filt_info['regions_total']} regions",
            ("Each detection's inscribed ellipse claims pixels; overlapping ellipses are split by relative distance to "
             "their centres, then each is trimmed to the canopy mask. Where the mask covers under "
             f"{int(100 * seg_info.get('min_mask_fill', 0))}% of an ellipse, the ellipse itself is the outline.")
            if hybrid else
            "Marker-controlled watershed floods outward from each crown centre over the smoothed blob response, inside "
            f"the canopy mask and within {seg_info.get('blob_reach_radii')} blob radii of the centre. Every colour is one region.",
            {"Regions": filt_info["regions_total"],
             **({"Outline from mask": seg_info.get("crowns_mask_trimmed"),
                 "Outline from ellipse": seg_info.get("crowns_ellipse_only")} if hybrid else {})},
        ),
        "stage_crowns.png": (
            "Filtered and scored crowns",
            f"{n} crowns, range {lo}–{hi}",
            "Regions are kept or rejected (grey) by size and solidity, then scored from explainable signals"
            + (", including the detector's own score" if hybrid else "")
            + ". Green is high, amber medium, red low confidence.",
            {"Crowns kept": n, "Rejected": filt_info["regions_rejected"],
             **{f"Rejected: {k.replace('_', ' ')}": v for k, v in filt_info["rejection_reasons"].items() if v},
             "High / medium / low": " / ".join(str(conf_info["counts"][b]) for b in ("high", "medium", "low")),
             "Count range": f"{lo}–{hi}"},
        ),
    }
    out = [{
        "key": "imagery", "title": "Source imagery", "headline": f"{m:.2f} m/px",
        "url": f"/api/jobs/{job_id}/imagery.png",
        "caption": "The input, cropped to the area's bounding box and gridded so each pixel has one true ground size.",
        "stats": {"Source": src, "Resolution": f"{m:.3f} m/px", "Image": f"{w} × {h} px", "CRS": scene.crs},
    }]
    for f in files:
        title, headline, caption, stats = stages[f]
        out.append({"key": f[len("stage_"):-len(".png")], "title": title, "headline": headline, "caption": caption,
                    "url": f"/api/jobs/{job_id}/{f}", "stats": stats})
    label = "DeepForest + canopy mask" if hybrid else "blob markers + watershed"
    return {"detector": detector_used, "detector_label": label, "stages": out}


__all__ = ["run_pipeline", "STAGES", "PipelineError", "LIMITATIONS_MD"]
