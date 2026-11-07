from __future__ import annotations

import json

import pytest

from certivo_ml import baseline, tracking


@pytest.fixture
def result(workspace):
    baseline.train()
    return baseline.evaluate_model()


def test_a_run_is_recorded_with_the_code_data_and_tool_versions(result, workspace, monkeypatch, tmp_path):
    import mlflow

    monkeypatch.setenv("CERTIVO_MLFLOW_DIR", str(tmp_path / "store"))
    run_id = tracking.log_experiment(result)
    assert run_id
    mlflow.set_tracking_uri(f"sqlite:///{(tmp_path / 'store' / 'mlflow.db').as_posix()}")
    run = mlflow.get_run(run_id)
    assert run.data.tags["data.sha256"] == result["data_sha256"]
    assert run.data.tags["data.kind"] == "synthetic"
    assert "git.commit" in run.data.tags and "git.dirty" in run.data.tags
    assert run.data.tags["numpy"] and run.data.tags["python"]
    assert "synthetic" in run.data.tags["claims"] and "real-world accuracy" in run.data.tags["claims"]
    assert run.data.params["synthetic.seed"] == "20261105"
    assert run.data.params["baseline.threshold"] == "0.5"
    assert run.data.metrics["test.accuracy"] == pytest.approx(result["test"]["accuracy"]["value"])
    assert "test.group_2.accuracy" in run.data.metrics


def test_the_record_lives_outside_git_and_the_pipeline(result, monkeypatch, tmp_path):
    monkeypatch.setenv("CERTIVO_MLFLOW_DIR", str(tmp_path / "store"))
    tracking.log_experiment(result)
    assert (tmp_path / "store" / "mlflow.db").exists()
    assert tracking.tracking_dir() == (tmp_path / "store").resolve()


def test_tracking_can_be_switched_off_for_tests(result, monkeypatch):
    monkeypatch.setenv("CERTIVO_MLFLOW", "off")
    assert tracking.log_experiment(result) is None


def test_two_runs_make_two_records_in_the_same_experiment(result, monkeypatch, tmp_path):
    import mlflow

    monkeypatch.setenv("CERTIVO_MLFLOW_DIR", str(tmp_path / "store"))
    tracking.log_experiment(result)
    tracking.log_experiment(result)
    mlflow.set_tracking_uri(f"sqlite:///{(tmp_path / 'store' / 'mlflow.db').as_posix()}")
    assert len(mlflow.search_runs(experiment_names=[baseline.MODEL])) == 2


def test_flattening_params_gives_readable_names():
    out: dict = {}
    tracking._flatten("", {"a": {"b": 1, "c": [1, 2]}, "d": "x"}, out)
    assert out == {"a.b": 1, "a.c": "[1, 2]", "d": "x"}
    json.dumps(out)
