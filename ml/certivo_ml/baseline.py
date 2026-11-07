"""The baseline model of the workspace: a nearest-class-average classifier with a calibrated probability.

It is deliberately plain. Its job is to give the experiment machinery (data versioning, tracking, model cards, reproduction)
a real train, calibrate and evaluate loop to run, not to be a good model. All the arithmetic that decides a label is done on
whole numbers, so it gives the same answer on every machine; only the final probabilities use floating point, and the reported
numbers that depend on them are rounded.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

from . import DATASET, MODEL, ROOT, write_text
from .metrics import evaluate, log_loss
from .params import load_params
from .synthetic import SPLITS, data_sha256, load_dataset

MODEL_PATH = ROOT / "models" / MODEL / "model.json"
METRICS_PATH = ROOT / "metrics" / f"{MODEL}.json"


def class_sums(images: np.ndarray, labels: np.ndarray) -> tuple[dict[int, np.ndarray], dict[int, int]]:
    flat = images.reshape(images.shape[0], -1).astype(np.int64)
    sums = {c: flat[labels == c].sum(axis=0) for c in (0, 1)}
    counts = {c: int((labels == c).sum()) for c in (0, 1)}
    return sums, counts


def scores(images: np.ndarray, sums: dict[int, np.ndarray], counts: dict[int, int]) -> np.ndarray:
    """Positive when a picture is closer to the average label-1 picture than to the average label-0 picture.

    The distance to an average is computed as an exact whole number (n*x - sum)^2, then divided once by n^2.
    """
    flat = images.reshape(images.shape[0], -1).astype(np.int64)
    dimension = flat.shape[1]
    distance = {}
    for c in (0, 1):
        n = counts[c]
        distance[c] = ((n * flat - sums[c][None, :]) ** 2).sum(axis=1).astype(np.float64) / float(n * n)
    return (distance[0] - distance[1]) / dimension


def probabilities(score: np.ndarray, temperature: float) -> np.ndarray:
    """A probability from a score. Rounded to 12 places: different systems can compute exp() differently in the very last bit,
    and rounding keeps that out of every number that is reported."""
    return np.round(1.0 / (1.0 + np.exp(-np.clip(score / temperature, -50.0, 50.0))), 12)


def train(config: dict[str, Any] | None = None) -> dict[str, Any]:
    params = load_params()
    grid = params["baseline"]["temperature_grid"]
    data = load_dataset(ROOT / "data" / DATASET)
    train_mask = data["split"] == SPLITS["train"]
    val_mask = data["split"] == SPLITS["val"]

    sums, counts = class_sums(data["images"][train_mask], data["labels"][train_mask])
    val_scores = scores(data["images"][val_mask], sums, counts)
    val_labels = data["labels"][val_mask]
    # the softness of the probability is chosen on the validation split only: the test split is not touched here
    losses = [round(log_loss(val_labels, probabilities(val_scores, float(t))), 9) for t in grid]
    temperature = grid[int(np.argmin(losses))]

    model = {
        "kind": "nearest-class-average with a calibrated temperature",
        "dataset": DATASET,
        "dimension": int(sums[0].shape[0]),
        "class_counts": {str(c): counts[c] for c in (0, 1)},
        "class_sums": {str(c): [int(v) for v in sums[c]] for c in (0, 1)},
        "temperature": temperature,
        "validation_log_loss_by_temperature": {str(t): loss for t, loss in zip(grid, losses)},
    }
    write_text(MODEL_PATH, json.dumps(model, indent=2, sort_keys=True) + "\n")
    print(f"trained on {counts[0] + counts[1]} pictures; temperature {temperature}")
    return model


def load_model(path: Path | None = None) -> tuple[dict[int, np.ndarray], dict[int, int], float]:
    # MODEL_PATH is looked up when this runs, not when the module loads, so tests can point it somewhere else
    model = json.loads((path or MODEL_PATH).read_text(encoding="utf-8"))
    sums = {int(c): np.asarray(v, dtype=np.int64) for c, v in model["class_sums"].items()}
    counts = {int(c): int(n) for c, n in model["class_counts"].items()}
    return sums, counts, float(model["temperature"])


def evaluate_model() -> dict[str, Any]:
    params = load_params()
    threshold = float(params["baseline"]["threshold"])
    data = load_dataset(ROOT / "data" / DATASET)
    sums, counts, temperature = load_model()

    def report(mask: np.ndarray) -> dict[str, Any]:
        s = scores(data["images"][mask], sums, counts)
        return evaluate(data["labels"][mask], s, probabilities(s, temperature), threshold)

    test = data["split"] == SPLITS["test"]
    result = {
        "model": MODEL,
        "dataset": DATASET,
        "data_sha256": data_sha256(ROOT / "data" / DATASET),
        "threshold": threshold,
        "temperature": temperature,
        "samples": {name: int((data["split"] == index).sum()) for name, index in SPLITS.items()},
        "validation": report(data["split"] == SPLITS["val"]),
        "test": report(test),
        "test_by_group": {str(g): report(test & (data["groups"] == g)) for g in sorted(set(int(v) for v in data["groups"]))},
    }
    write_text(METRICS_PATH, json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    t = result["test"]
    print(f"test accuracy {t['accuracy']['value']}  auc {t['auc']}  ({t['samples']} pictures)")
    return result


def main(argv: list[str]) -> None:
    command = argv[1] if len(argv) > 1 else ""
    if command == "train":
        train()
    elif command == "evaluate":
        from .tracking import log_experiment  # imported here: MLflow is slow to load and the other commands do not need it

        result = evaluate_model()
        log_experiment(result)
    else:
        raise SystemExit("usage: python -m certivo_ml.baseline train | evaluate")


if __name__ == "__main__":
    main(sys.argv)
