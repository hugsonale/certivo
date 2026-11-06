from __future__ import annotations

import math

import numpy as np

from certivo_ml import metrics


def test_confusion_counts():
    labels = np.array([1, 1, 1, 0, 0, 0, 0])
    predicted = np.array([1, 1, 0, 1, 0, 0, 0])
    assert metrics.confusion(labels, predicted) == {"true_positive": 2, "false_positive": 1, "true_negative": 3, "false_negative": 1}


def test_wilson_interval_matches_known_values():
    low, high = metrics.wilson_interval(8, 10)
    assert math.isclose(low, 0.4902, abs_tol=1e-3) and math.isclose(high, 0.9433, abs_tol=1e-3)
    low, high = metrics.wilson_interval(0, 10)
    assert low == 0.0 and 0.25 < high < 0.31
    assert all(math.isnan(v) for v in metrics.wilson_interval(0, 0))


def test_wilson_interval_gets_narrower_with_more_data():
    narrow = metrics.wilson_interval(800, 1000)
    wide = metrics.wilson_interval(8, 10)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_rate_reports_the_count_behind_the_number():
    r = metrics.rate(3, 12)
    assert r["value"] == 0.25 and r["count"] == 3 and r["of"] == 12 and r["ci95"][0] < 0.25 < r["ci95"][1]


def test_auc_perfect_reversed_and_chance():
    labels = np.array([0, 0, 1, 1])
    assert metrics.auc(labels, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert metrics.auc(labels, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0
    assert metrics.auc(labels, np.array([0.5, 0.5, 0.5, 0.5])) == 0.5


def test_auc_by_hand_with_a_tie():
    # positives 0.8 and 0.5, negatives 0.5 and 0.3: pairs (0.8>0.5, 0.8>0.3, 0.5=0.5 half, 0.5>0.3) = 3.5 of 4
    assert metrics.auc(np.array([1, 1, 0, 0]), np.array([0.8, 0.5, 0.5, 0.3])) == 0.875


def test_auc_needs_both_labels():
    assert math.isnan(metrics.auc(np.array([1, 1]), np.array([0.2, 0.9])))


def test_log_loss_is_finite_even_for_certain_wrong_answers():
    assert math.isfinite(metrics.log_loss(np.array([1]), np.array([0.0])))
    assert metrics.log_loss(np.array([1, 0]), np.array([0.5, 0.5])) == np.float64(math.log(2))


def test_calibration_error_is_zero_when_probabilities_match_reality():
    probabilities = np.array([0.25] * 4 + [0.75] * 4)
    labels = np.array([1, 0, 0, 0, 1, 1, 1, 0])
    assert metrics.expected_calibration_error(labels, probabilities) == 0.0


def test_calibration_error_by_hand():
    # everything is stated as 90 percent sure, but only half are right: |0.5 - 0.9| = 0.4
    assert metrics.expected_calibration_error(np.array([1, 0, 1, 0]), np.array([0.9] * 4)) == 0.4


def test_evaluate_assembles_everything_and_survives_strict_json():
    import json

    labels = np.array([1, 1, 0, 0, 1, 0])
    scores = np.array([2.0, 1.0, -1.0, 0.5, -0.5, -2.0])
    probabilities = 1 / (1 + np.exp(-scores))
    result = metrics.evaluate(labels, scores, probabilities, 0.5)
    assert result["samples"] == 6 and result["confusion"]["true_positive"] == 2
    json.dumps(result, allow_nan=False)
