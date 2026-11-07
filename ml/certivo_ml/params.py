from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import ROOT


def load_params(path: Path | None = None) -> dict[str, Any]:
    with open(path or ROOT / "params.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)
