from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from certivo_ml import ROOT, baseline, model_card, params, synthetic, tracking  # noqa: E402


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throw-away copy of the workspace with a small dataset, so tests never touch the real data, models or metrics."""
    shutil.copy(ROOT / "params.yaml", tmp_path / "params.yaml")
    for folder in ("model_cards", "datasheets"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    text = (tmp_path / "params.yaml").read_text(encoding="utf-8").replace("samples: 2400", "samples: 600")
    (tmp_path / "params.yaml").write_text(text, encoding="utf-8")

    for module in (params, baseline, model_card, tracking):
        monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(baseline, "MODEL_PATH", tmp_path / "models" / baseline.MODEL / "model.json")
    monkeypatch.setattr(baseline, "METRICS_PATH", tmp_path / "metrics" / f"{baseline.MODEL}.json")
    monkeypatch.setattr(model_card, "TEMPLATE", tmp_path / "model_cards" / "TEMPLATE.md")
    monkeypatch.setattr(model_card, "CARD", tmp_path / "model_cards" / f"{baseline.MODEL}.md")
    monkeypatch.setattr(model_card, "METRICS", tmp_path / "metrics" / f"{baseline.MODEL}.json")

    config = params.load_params()["synthetic"]
    synthetic.write_dataset(synthetic.generate(config), tmp_path / "data" / synthetic.DATASET, config)
    return tmp_path
