"""Checks the workspace's own configuration, so a typo in dvc.yaml or a missing ignore rule fails here and not on someone's machine."""

from __future__ import annotations

from pathlib import Path

import yaml

from certivo_ml import ROOT

DVC = yaml.safe_load((ROOT / "dvc.yaml").read_text(encoding="utf-8"))
PARAMS = yaml.safe_load((ROOT / "params.yaml").read_text(encoding="utf-8"))


def produced() -> set[str]:
    paths = set()
    for stage in DVC["stages"].values():
        for out in stage.get("outs", []) + stage.get("metrics", []):
            paths.add(next(iter(out)) if isinstance(out, dict) else out)
    return paths


def test_every_dependency_exists_or_is_made_by_an_earlier_stage():
    made = produced()
    for name, stage in DVC["stages"].items():
        for dep in stage.get("deps", []):
            assert dep in made or (ROOT / dep).exists(), f"{name} depends on {dep}, which nothing makes and which does not exist"


def test_every_parameter_a_stage_names_exists_in_params_yaml():
    for name, stage in DVC["stages"].items():
        for key in stage.get("params", []):
            assert key in PARAMS, f"{name} uses {key}, which is not in params.yaml"


def test_every_stage_runs_python_modules_that_exist():
    for stage in DVC["stages"].values():
        parts = stage["cmd"].split()
        assert parts[:2] == ["python", "-m"]
        assert (ROOT / (parts[2].replace(".", "/") + ".py")).exists(), parts[2]


def test_data_and_models_are_ignored_by_git_and_text_outputs_are_not():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for rule in ("/data/", "/models/", "/mlflow/", "/mlruns/", "*.npy", "*.mp4", "*.onnx", "footage/"):
        assert rule in ignore, rule
    assert "/metrics/" not in ignore and "/model_cards/" not in ignore


def test_files_are_checked_out_with_plain_line_endings_everywhere():
    assert "* text eol=lf" in (ROOT / ".gitattributes").read_text(encoding="utf-8")


def test_dvc_sends_nothing_to_anyone():
    config = (ROOT / ".dvc" / "config").read_text(encoding="utf-8")
    assert "analytics = false" in config and "check_update = false" in config


def test_every_dependency_is_pinned_exactly():
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            assert "==" in line, f"{line} is not pinned to an exact version"


def test_the_constraints_file_exists_and_pins_every_line():
    path = ROOT / "constraints.txt"
    assert path.exists()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            assert "==" in line, line
