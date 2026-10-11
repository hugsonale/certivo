"""Policy evaluation. The thresholds below are PLACEHOLDERS chosen for Phase 0 plumbing.
They are not validated against any model; real values come from the edge benchmark."""
from __future__ import annotations

DEFAULT_USE_CASE = "default_video_call"
DEFAULT_POLICY_CONFIG = {
    "re_evaluation_interval_ms": 1000,
    "accept_min_milli": 700,      # confidence >= this -> accept
    "reject_below_milli": 400,    # confidence < this counts toward rejection
    "drop_consecutive": 2,        # consecutive sub-threshold intervals needed to reject
}


def validate_policy_config(config: dict) -> None:
    keys = set(DEFAULT_POLICY_CONFIG)
    if set(config) != keys or not all(isinstance(config[k], int) for k in keys):
        raise ValueError(f"policy config must have exactly integer keys {sorted(keys)}")
    if not 0 <= config["reject_below_milli"] <= config["accept_min_milli"] <= 1000:
        raise ValueError("require 0 <= reject_below_milli <= accept_min_milli <= 1000")
    if config["drop_consecutive"] < 1 or config["re_evaluation_interval_ms"] < 100:
        raise ValueError("drop_consecutive >= 1 and re_evaluation_interval_ms >= 100")


def evaluate(config: dict, prior_milli: list[int], new_milli: int) -> str:
    """Return accept | fallback | reject for one participant.

    prior_milli: that participant's earlier confidences, oldest first.
    """
    if new_milli >= config["accept_min_milli"]:
        return "accept"
    if new_milli >= config["reject_below_milli"]:
        return "fallback"
    n = config["drop_consecutive"]
    window = (prior_milli[-(n - 1):] if n > 1 else []) + [new_milli]
    if len(window) == n and all(c < config["reject_below_milli"] for c in window):
        return "reject"
    return "fallback"
