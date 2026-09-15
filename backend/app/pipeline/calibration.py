"""Small local calibration model trained from a user's validation patch."""

from __future__ import annotations

import math

import numpy as np


FEATURE_NAMES = ("log_area", "diameter", "solidity", "confidence", "separation", "size", "shape")


def _features(properties: dict) -> list[float]:
    signals = properties.get("signals") or {}
    return [
        math.log1p(max(0.0, float(properties.get("area_m2") or 0.0))),
        float(properties.get("equivalent_diameter_m") or 0.0),
        float(properties.get("solidity") or 0.0),
        float(properties.get("confidence") or 0.0),
        float(signals.get("separation") or 0.0),
        float(signals.get("size") or 0.0),
        float(signals.get("shape") or 0.0),
    ]


def _fit_logistic(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-6] = 1.0
    z = (x - mean) / scale
    design = np.column_stack((np.ones(len(z)), z))
    weights = np.zeros(design.shape[1], dtype=np.float64)
    for _ in range(240):
        logits = np.clip(design @ weights, -30.0, 30.0)
        probs = 1.0 / (1.0 + np.exp(-logits))
        gradient = (design.T @ (probs - y)) / len(y)
        gradient[1:] += 0.08 * weights[1:]
        weights -= 0.35 * gradient
    return weights, mean, scale


def calibrate(crowns: list[dict], matched_ids: set[int], recall: float, total_count: int) -> dict:
    """Estimate the count after learning which local detections match human marks.

    The model is intentionally conservative: fewer than four positive and four
    negative examples produces no model output rather than a fabricated estimate.
    """
    labelled = [c for c in crowns if c.get("properties", {}).get("id") is not None]
    positives = [c for c in labelled if int(c["properties"]["id"]) in matched_ids]
    negatives = [c for c in labelled if int(c["properties"]["id"]) not in matched_ids]
    if len(positives) < 4 or len(negatives) < 4:
        return {
            "available": False,
            "reason": "Mark at least 4 matched and 4 unmatched detections for a local model.",
            "training_examples": len(labelled),
        }

    x = np.asarray([_features(c["properties"]) for c in positives + negatives], dtype=np.float64)
    y = np.asarray([1.0] * len(positives) + [0.0] * len(negatives), dtype=np.float64)
    weights, mean, scale = _fit_logistic(x, y)
    all_x = np.asarray([_features(c["properties"]) for c in labelled], dtype=np.float64)
    all_z = (all_x - mean) / scale
    logits = np.clip(np.column_stack((np.ones(len(all_z)), all_z)) @ weights, -30.0, 30.0)
    probabilities = 1.0 / (1.0 + np.exp(-logits))
    usable_recall = max(0.25, min(1.0, recall))
    # The patch teaches us the likely precision of the detector. Scale that
    # local precision to the full raw detector count, then correct for recall.
    precision_estimate = float(probabilities.mean())
    estimate = float(total_count * precision_estimate / usable_recall)
    precision_variance = precision_estimate * (1.0 - precision_estimate) / max(1, len(labelled))
    recall_variance = usable_recall * (1.0 - usable_recall) / max(1, len(matched_ids))
    relative_variance = precision_variance / max(precision_estimate**2, 1e-6) + recall_variance / max(usable_recall**2, 1e-6)
    margin = 1.96 * estimate * math.sqrt(max(0.0, relative_variance))
    return {
        "available": True,
        "method": "regularized logistic regression",
        "features": list(FEATURE_NAMES),
        "training_examples": len(labelled),
        "positive_examples": len(positives),
        "negative_examples": len(negatives),
        "precision_estimate": round(precision_estimate, 3),
        "estimated_count": round(estimate),
        "estimated_range": [max(0, round(estimate - margin)), round(estimate + margin)],
        "note": "Scaled from this validation patch to the full raw detector count; the raw detector count remains the primary result.",
    }