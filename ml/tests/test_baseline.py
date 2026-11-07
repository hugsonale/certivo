from __future__ import annotations

import json

import numpy as np

from certivo_ml import baseline, synthetic
from certivo_ml.params import load_params


def test_scores_use_exact_integer_arithmetic_and_match_the_plain_formula():
    rng = np.random.default_rng(3)
    images = rng.integers(0, 256, size=(40, 4, 4), dtype=np.uint8)
    labels = np.array([0, 1] * 20, dtype=np.uint8)
    sums, counts = baseline.class_sums(images, labels)
    got = baseline.scores(images, sums, counts)
    flat = images.reshape(40, -1).astype(np.float64)
    mean0, mean1 = flat[labels == 0].mean(axis=0), flat[labels == 1].mean(axis=0)
    expected = (((flat - mean0) ** 2).sum(axis=1) - ((flat - mean1) ** 2).sum(axis=1)) / 16
    assert np.allclose(got, expected, rtol=1e-12)


def test_the_order_of_the_pictures_does_not_change_a_score():
    rng = np.random.default_rng(4)
    images = rng.integers(0, 256, size=(30, 4, 4), dtype=np.uint8)
    labels = np.array([0, 1] * 15, dtype=np.uint8)
    sums, counts = baseline.class_sums(images, labels)
    order = rng.permutation(30)
    assert np.array_equal(baseline.scores(images, sums, counts)[order], baseline.scores(images[order], sums, counts))


def test_probabilities_are_between_zero_and_one_and_never_overflow():
    p = baseline.probabilities(np.array([-1e9, -3.0, 0.0, 3.0, 1e9]), 5.0)
    assert np.all((p >= 0) & (p <= 1)) and p[2] == 0.5 and np.all(np.isfinite(p))


def test_probabilities_are_rounded_so_that_last_bit_differences_between_machines_cannot_show():
    p = baseline.probabilities(np.array([0.123456789, -2.5, 7.0]), 5.0)
    assert np.array_equal(p, np.round(p, 12))


def test_a_softer_temperature_means_less_certain_probabilities():
    s = np.array([4.0])
    assert baseline.probabilities(s, 1.0)[0] > baseline.probabilities(s, 10.0)[0] > 0.5


def test_training_writes_a_model_that_is_the_same_every_time(workspace):
    first = baseline.train()
    text_one = baseline.MODEL_PATH.read_bytes()
    second = baseline.train()
    assert first == second and text_one == baseline.MODEL_PATH.read_bytes()
    assert b"\r" not in text_one


def test_training_never_looks_at_the_test_split(workspace):
    """If the model changed when the test pictures or labels changed, the test result could not be trusted."""
    baseline.train()
    before = baseline.MODEL_PATH.read_bytes()
    directory = workspace / "data" / synthetic.DATASET
    data = synthetic.load_dataset(directory)
    test = data["split"] == synthetic.SPLITS["test"]
    data["labels"][test] ^= 1
    data["images"][test] = 255 - data["images"][test]
    for name, array in data.items():
        np.save(directory / f"{name}.npy", array, allow_pickle=False)
    baseline.train()
    assert baseline.MODEL_PATH.read_bytes() == before


def test_the_temperature_is_chosen_from_the_grid_on_validation_data(workspace):
    model = baseline.train()
    assert model["temperature"] in load_params()["baseline"]["temperature_grid"]
    assert set(model["validation_log_loss_by_temperature"]) == {str(t) for t in load_params()["baseline"]["temperature_grid"]}


def test_evaluation_reports_the_test_split_by_group_and_is_the_same_every_time(workspace):
    baseline.train()
    one = baseline.evaluate_model()
    text_one = baseline.METRICS_PATH.read_bytes()
    two = baseline.evaluate_model()
    assert one == two and text_one == baseline.METRICS_PATH.read_bytes()
    assert one["samples"]["test"] == sum(g["samples"] for g in one["test_by_group"].values())
    assert set(one["test_by_group"]) == {"0", "1", "2"}
    assert json.loads(text_one)["data_sha256"] == synthetic.data_sha256(workspace / "data" / synthetic.DATASET)


def test_the_baseline_does_better_than_guessing_and_the_noisy_group_does_worse(workspace):
    baseline.train()
    result = baseline.evaluate_model()
    assert result["test"]["accuracy"]["value"] > 0.7 and result["test"]["auc"] > 0.8
    by_group = {g: b["accuracy"]["value"] for g, b in result["test_by_group"].items()}
    assert by_group["0"] > by_group["2"]
