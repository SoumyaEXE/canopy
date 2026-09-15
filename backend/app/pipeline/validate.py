"""Stage 8: compare detections against a user's hand-marked trees in a sample patch."""

from __future__ import annotations

import math

from shapely.geometry import Point, box, shape

MIN_CLICKS = 15


def _metres(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Equirectangular distance; exact enough at the scale of a validation patch."""
    k = math.cos(math.radians((lat1 + lat2) / 2.0))
    dx = math.radians(lon2 - lon1) * 6371008.8 * k
    dy = math.radians(lat2 - lat1) * 6371008.8
    return math.hypot(dx, dy)


def validate(features: list[dict], bbox: list[float], clicks: list[list[float]], total_count: int) -> dict:
    from . import calibration, geo

    if len(clicks) < MIN_CLICKS:
        return {
            "ok": False,
            "message": f"Please mark at least {MIN_CLICKS} trees. You have marked {len(clicks)}.",
            "min_clicks": MIN_CLICKS,
        }
    w, s, e, n = bbox
    patch = box(w, s, e, n)
    patch_ha = geo.polygon_area_m2(patch) / 1e4

    dets = []
    for f in features:
        p = f["properties"]
        lon, lat = p["centroid_lonlat"]
        if patch.contains(Point(lon, lat)):
            dets.append({"id": p["id"], "lon": lon, "lat": lat, "radius": p["equivalent_diameter_m"] / 2.0, "polygon": shape(f["geometry"]), "properties": p})

    pairs = []
    for ci, (clon, clat) in enumerate(clicks):
        pt = Point(clon, clat)
        for di, det in enumerate(dets):
            d = _metres(clon, clat, det["lon"], det["lat"])
            if det["polygon"].contains(pt) or d <= 1.5 * det["radius"]:
                pairs.append((d, ci, di))
    pairs.sort()
    used_c, used_d, matches = set(), set(), []
    for d, ci, di in pairs:
        if ci in used_c or di in used_d:
            continue
        used_c.add(ci)
        used_d.add(di)
        matches.append({"click": ci, "crown_id": dets[di]["id"], "distance_m": round(d, 2)})

    tp = len(matches)
    fp = len(dets) - tp
    fn = len(clicks) - tp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    cf = (tp + fn) / (tp + fp) if tp + fp else None
    corrected = round(total_count * cf) if cf is not None else None
    missing_pct = round(100 * (1 - recall))
    matched_ids = {int(dets[di]["id"]) for _, _, di in matches}
    model = calibration.calibrate(dets, matched_ids, recall, total_count)

    sentence = (
        f"On your {patch_ha:.2f} hectare sample you marked {len(clicks)} trees. "
        f"The tool found {len(dets)}, of which {tp} matched. "
        f"Precision {precision:.2f}, recall {recall:.2f}. "
        f"The tool is missing roughly {missing_pct} percent of the crowns you marked"
        + (f" and {fp} of its detections had no matching mark. " if fp else ". ")
        + (
            f"Applying that correction to the full area suggests about {corrected} trees rather than {total_count}."
            if corrected is not None
            else "No correction can be computed because the tool found no crowns in this patch."
        )
    )
    return {
        "ok": True,
        "patch_bbox": bbox,
        "patch_area_ha": round(patch_ha, 3),
        "clicks": len(clicks),
        "detections_in_patch": len(dets),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "correction_factor": round(cf, 3) if cf is not None else None,
        "corrected_count": corrected,
        "local_model": model,
        "matches": matches,
        "summary": sentence,
        "caveat": (
            f"This is a small sample ({len(clicks)} marked trees in {patch_ha:.2f} ha) marked by one person on the same imagery "
            "the tool used. The correction is indicative, not rigorous, and assumes the patch is representative of the whole area."
        ),
        "matching_rule": "click matches a detection if inside its polygon or within 1.5x its equivalent radius of the centroid; greedy nearest-first, one-to-one",
    }
