"""Stage 7: per-crown confidence from four explainable signals."""

from __future__ import annotations

import math

import numpy as np
from scipy.spatial import cKDTree

WEIGHTS = {"shape": 0.30, "size": 0.25, "separation": 0.25, "shadow": 0.20}
HIGH, MEDIUM = 0.70, 0.45
NEIGHBOURS = 8
# Height-to-crown-diameter ratios observed for most trees fall within this band.
PLAUSIBLE_H_TO_D = (0.5, 5.0)

LOW_REASONS = {
    "shape": "Low confidence: the outline is irregular, which usually means two or more merged crowns or a non-tree green patch.",
    "size": "Low confidence: this crown is far larger or smaller than its neighbours, so it is likely merged with, or split from, another crown.",
    "separation": "Low confidence: this region is likely two or more merged crowns.",
    "shadow": "Low confidence: no measurable shadow confirms that this is a tall object rather than low vegetation.",
}


def score(crowns: list[dict], height_enabled: bool) -> dict:
    weights = dict(WEIGHTS)
    if not height_enabled:
        # Shadow agreement cannot be assessed at all; renormalize rather than penalize every crown equally.
        w = weights.pop("shadow")
        total = sum(weights.values())
        weights = {k: v / total for k, v in weights.items()}
        weights["shadow"] = 0.0
        _ = w

    n = len(crowns)
    if n:
        pts = np.array([c["centroid_px"] for c in crowns], dtype=np.float64)
        areas = np.array([c["area_m2"] for c in crowns], dtype=np.float64)
        k = min(NEIGHBOURS + 1, n)
        tree = cKDTree(pts)
        _, idx = tree.query(pts, k=k)
        if k == 1:
            idx = idx.reshape(-1, 1)

    for i, c in enumerate(crowns):
        shape_s = min(1.0, 4.0 * math.pi * c["_area_px"] / (c["_perimeter_px"] ** 2))

        if n > 1:
            neigh = [j for j in np.atleast_1d(idx[i]) if j != i][:NEIGHBOURS]
            na = areas[neigh]
            med = float(np.median(na))
            mad = float(np.median(np.abs(na - med))) * 1.4826
            spread = max(mad, 0.25 * med, 1e-6)
            z = abs(c["area_m2"] - med) / spread
            size_s = max(0.0, 1.0 - z / 3.0)
        else:
            size_s = 0.5

        sep_s = min(1.0, c["_dist_centroid_px"] / max(c["_eq_radius_px"], 1e-6))

        h = c.get("height_m")
        if not height_enabled:
            shadow_s = 0.0
        elif h is None:
            shadow_s = 0.0
        else:
            ratio = h / max(c["equivalent_diameter_m"], 1e-6)
            shadow_s = 1.0 if PLAUSIBLE_H_TO_D[0] <= ratio <= PLAUSIBLE_H_TO_D[1] else 0.4

        signals = {"shape": shape_s, "size": size_s, "separation": sep_s, "shadow": shadow_s}
        total = sum(weights[k] * v for k, v in signals.items())
        bucket = "high" if total >= HIGH else "medium" if total >= MEDIUM else "low"
        c["confidence"] = round(total, 4)
        c["confidence_bucket"] = bucket
        c["signals"] = {k: round(v, 4) for k, v in signals.items()}
        if bucket == "low":
            considered = [k for k in signals if weights[k] > 0]
            worst = min(considered, key=lambda k: (signals[k], k))
            c["low_confidence_reason"] = LOW_REASONS[worst]
        else:
            c["low_confidence_reason"] = None

    counts = {b: sum(1 for c in crowns if c["confidence_bucket"] == b) for b in ("high", "medium", "low")}
    lower = counts["high"] + counts["medium"]
    upper = counts["high"] + counts["medium"] + counts["low"] * 2
    return {
        "weights": {k: round(v, 4) for k, v in weights.items()},
        "buckets": {"high": f">= {HIGH}", "medium": f"{MEDIUM} to {HIGH}", "low": f"< {MEDIUM}"},
        "counts": counts,
        "count_range": [lower, upper],
        "count_range_rule": "lower = high + medium; upper = high + medium + 2 * low (low-confidence regions are usually merged crowns)",
        "size_signal": "1 - |area - median(8 nearest)| / (3 * max(1.4826*MAD, 0.25*median)), floored at 0",
        "separation_signal": "distance-transform value at centroid / equivalent radius, capped at 1",
        "shadow_signal": f"1 if height/diameter in {PLAUSIBLE_H_TO_D}, 0.4 if measured but outside, 0 if not measured",
    }
