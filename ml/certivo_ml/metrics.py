"""The numbers an experiment reports. Counts are exact; the few that need floating point are rounded so every machine agrees."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

ROUND = 6


def confusion(labels: np.ndarray, predicted: np.ndarray) -> dict[str, int]:
    labels = labels.astype(bool)
    predicted = predicted.astype(bool)
    return {
        "true_positive": int(np.sum(labels & predicted)),
        "false_positive": int(np.sum(~labels & predicted)),
        "true_negative": int(np.sum(~labels & ~predicted)),
        "false_negative": int(np.sum(labels & ~predicted)),
    }


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """A 95 percent interval for a proportion that stays sensible for small counts (Wilson)."""
    if total == 0:
        return (math.nan, math.nan)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return (round(max(0.0, centre - margin), ROUND), round(min(1.0, centre + margin), ROUND))


def rate(successes: int, total: int) -> dict[str, Any]:
    low, high = wilson_interval(successes, total)
    return {"value": round(successes / total, ROUND) if total else math.nan, "count": successes, "of": total, "ci95": [low, high]}


def auc(labels: np.ndarray, scores: np.ndarray) -> float:
    """The chance that a random positive scores higher than a random negative (ties count half). Exact: it only counts."""
    labels = labels.astype(bool)
    positives = scores[labels]
    negatives = np.sort(scores[~labels])
    if positives.size == 0 or negatives.size == 0:
        return math.nan
    below = np.searchsorted(negatives, positives, side="left")
    up_to = np.searchsorted(negatives, positives, side="right")
    wins = int(below.sum())
    ties = int((up_to - below).sum())
    return round((wins + 0.5 * ties) / (positives.size * negatives.size), ROUND)


def log_loss(labels: np.ndarray, probabilities: np.ndarray) -> float:
    p = np.clip(probabilities, 1e-12, 1 - 1e-12)
    y = labels.astype(np.float64)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def expected_calibration_error(labels: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    """How far the stated probabilities are from what actually happened, averaged over ten equal slices of probability."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.clip(np.digitize(probabilities, edges[1:-1]), 0, bins - 1)
    total = labels.shape[0]
    error = 0.0
    for b in range(bins):
        mask = index == b
        count = int(mask.sum())
        if count:
            error += (count / total) * abs(float(labels[mask].mean()) - float(probabilities[mask].mean()))
    return round(error, 4)


def evaluate(labels: np.ndarray, scores: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict[str, Any]:
    predicted = probabilities >= threshold
    counts = confusion(labels, predicted)
    positives = counts["true_positive"] + counts["false_negative"]
    negatives = counts["false_positive"] + counts["true_negative"]
    return {
        "samples": int(labels.shape[0]),
        "confusion": counts,
        "accuracy": rate(counts["true_positive"] + counts["true_negative"], int(labels.shape[0])),
        "false_positive_rate": rate(counts["false_positive"], negatives),
        "false_negative_rate": rate(counts["false_negative"], positives),
        "auc": auc(labels, scores),
        "log_loss": round(log_loss(labels, probabilities), 4),
        "expected_calibration_error": expected_calibration_error(labels, probabilities),
    }
