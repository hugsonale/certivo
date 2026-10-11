import pytest

from app.policy import DEFAULT_POLICY_CONFIG as CFG
from app.policy import evaluate, validate_policy_config


def test_accept_and_fallback_bands():
    assert evaluate(CFG, [], 900) == "accept"
    assert evaluate(CFG, [], 700) == "accept"
    assert evaluate(CFG, [], 500) == "fallback"
    assert evaluate(CFG, [], 400) == "fallback"


def test_single_low_interval_is_only_fallback():
    assert evaluate(CFG, [900, 900], 100) == "fallback"


def test_consecutive_low_intervals_reject():
    assert evaluate(CFG, [900, 100], 100) == "reject"


def test_recovery_after_reject():
    assert evaluate(CFG, [100, 100], 900) == "accept"


def test_drop_consecutive_one_rejects_immediately():
    assert evaluate(dict(CFG, drop_consecutive=1), [], 100) == "reject"


def test_config_validation():
    validate_policy_config(CFG)
    with pytest.raises(ValueError):
        validate_policy_config(dict(CFG, reject_below_milli=800))
    with pytest.raises(ValueError):
        validate_policy_config({"accept_min_milli": 1})
