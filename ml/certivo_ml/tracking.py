"""Experiment tracking with MLflow (guide P0-30). Records are kept on this machine, under ml/mlflow, and never committed.

Every run is stamped with what is needed to say later "which code and which data made this": the git commit, whether the
working copy had uncommitted changes, the dataset fingerprint, and the exact tool versions.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import DATASET, MODEL, ROOT
from .params import load_params


def tracking_dir() -> Path:
    return Path(os.environ.get("CERTIVO_MLFLOW_DIR", ROOT / "mlflow")).resolve()


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def _flatten(prefix: str, value: Any, into: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), inner, into)
    else:
        into[prefix] = value if isinstance(value, (int, float, str, bool)) else str(value)


def log_experiment(result: dict[str, Any], experiment: str = MODEL) -> str | None:
    """Writes one MLflow run for an evaluated model and returns its id. Set CERTIVO_MLFLOW=off to skip (tests only)."""
    if os.environ.get("CERTIVO_MLFLOW", "on") == "off":
        return None
    import mlflow
    import numpy

    directory = tracking_dir()
    directory.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{(directory / 'mlflow.db').as_posix()}")
    if mlflow.get_experiment_by_name(experiment) is None:
        mlflow.create_experiment(experiment, artifact_location=(directory / "artifacts").as_uri())
    mlflow.set_experiment(experiment)

    params: dict[str, Any] = {}
    _flatten("", load_params(), params)
    metrics: dict[str, float] = {}
    for split in ("validation", "test"):
        block = result[split]
        metrics[f"{split}.accuracy"] = block["accuracy"]["value"]
        metrics[f"{split}.auc"] = block["auc"]
        metrics[f"{split}.false_positive_rate"] = block["false_positive_rate"]["value"]
        metrics[f"{split}.false_negative_rate"] = block["false_negative_rate"]["value"]
        metrics[f"{split}.log_loss"] = block["log_loss"]
        metrics[f"{split}.expected_calibration_error"] = block["expected_calibration_error"]
    for group, block in result["test_by_group"].items():
        metrics[f"test.group_{group}.accuracy"] = block["accuracy"]["value"]

    with mlflow.start_run(run_name=f"{MODEL}-{_git('rev-parse', '--short', 'HEAD')}") as run:
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        mlflow.set_tags(
            {
                "git.commit": _git("rev-parse", "HEAD"),
                "git.dirty": str(bool(_git("status", "--porcelain", "--", "."))).lower(),
                "data.name": DATASET,
                "data.sha256": result["data_sha256"],
                "data.kind": "synthetic",
                "python": platform.python_version(),
                "numpy": numpy.__version__,
                "mlflow": mlflow.__version__,
                "os": f"{platform.system()} {platform.release()}",
                "claims": "none: synthetic data, says nothing about real-world accuracy",
            }
        )
        for artifact in (ROOT / "metrics" / f"{MODEL}.json", ROOT / "models" / MODEL / "model.json", ROOT / "params.yaml"):
            if artifact.exists():
                mlflow.log_artifact(str(artifact))
        print(f"experiment record: {experiment} run {run.info.run_id} (in {directory})", file=sys.stderr)
        return run.info.run_id
