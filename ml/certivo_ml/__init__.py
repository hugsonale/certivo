"""The Certivo ML workspace (guide step P0-30)."""

from __future__ import annotations

from pathlib import Path

#: The folder that holds params.yaml, dvc.yaml and the data. Everything is found relative to it.
ROOT = Path(__file__).resolve().parent.parent

DATASET = "synthetic-v0"
MODEL = "baseline-synthetic-v0"


def write_text(path: Path, text: str) -> None:
    """Write a text file with plain line endings on every operating system, so its fingerprint is the same everywhere."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
