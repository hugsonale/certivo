"""The policy engine (docs/spec/base/03-policy-engine.md, ADR 0017).

A policy is a small set of settings. For each participant, each time a valid score packet arrives:

  1. effective confidence = reported confidence - tier penalty - model-version penalty, kept within 0..1000
     (the reported value itself is never altered);
  2. the effective confidence is placed in a band: accept, fallback, or reject (after `drop_consecutive`
     low intervals in a row);
  3. a score from a model version the policy lists as unsupported is refused instead of scored.

Every function here is a pure calculation: the same inputs always give the same answer, which is what makes
the engine testable in a partner's own pipeline. All numeric defaults are PLACEHOLDERS chosen so the
plumbing can be tested; real thresholds come from the edge-model benchmark (P0-33 to P0-40).
"""
from __future__ import annotations

import copy
import re

DEFAULT_USE_CASE = "default_video_call"

TIERS = ("hardware_attested", "platform_authenticated", "software_only")
FALLBACK_BEHAVIORS = ("indicator_only", "flag_for_review")
MAX_MODEL_ENTRIES = 16
_MODEL_VERSION = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

DEFAULT_POLICY_CONFIG: dict = {
    "re_evaluation_interval_ms": 1000,
    "accept_min_milli": 700,      # effective confidence >= this -> accept
    "reject_below_milli": 400,    # effective confidence < this counts toward rejection
    "drop_consecutive": 2,        # consecutive sub-threshold intervals needed to reject
    "fallback_behavior": "indicator_only",  # flag_for_review also sends a webhook on a borderline result
    "tier_penalty_milli": {tier: 0 for tier in TIERS},
    "model_penalties": [],        # [{"model_version": "...", "penalty_milli": 0..1000}], at most 16
    "unsupported_model_versions": [],  # scores from these model versions are refused, at most 16
}
SETTING_NAMES = tuple(DEFAULT_POLICY_CONFIG)


def _is_int(value) -> bool:
    return type(value) is int  # a bool or a float is not a whole number here


def normalize_config(config: dict) -> dict:
    """A complete settings object. Sessions that started before the newer settings existed keep their
    original four settings; the missing ones take their defaults (which change nothing)."""
    full = copy.deepcopy(DEFAULT_POLICY_CONFIG)
    for name, value in config.items():
        if name == "tier_penalty_milli":
            full[name].update(value)
        else:
            full[name] = copy.deepcopy(value)
    return full


def validate_policy_settings(settings) -> list[dict]:
    """Every problem with a partner's submitted settings, not just the first. Empty means valid."""
    problems: list[dict] = []

    def bad(setting: str, text: str) -> None:
        problems.append({"setting": setting, "problem": text})

    if not isinstance(settings, dict):
        return [{"setting": "settings", "problem": "must be an object"}]
    for name in settings:
        if name not in SETTING_NAMES:
            bad(str(name)[:64], "unknown setting")

    merged = normalize_config({k: v for k, v in settings.items()
                               if k in SETTING_NAMES and k != "tier_penalty_milli"})
    ok_int: dict[str, bool] = {}
    for name, low, high in (("re_evaluation_interval_ms", 100, None), ("accept_min_milli", 0, 1000),
                            ("reject_below_milli", 0, 1000), ("drop_consecutive", 1, None)):
        if name not in settings:
            ok_int[name] = True
            continue
        value = settings[name]
        ok_int[name] = _is_int(value) and value >= low and (high is None or value <= high)
        if not _is_int(value):
            bad(name, "must be a whole number")
        elif value < low:
            bad(name, f"must be at least {low}")
        elif high is not None and value > high:
            bad(name, f"must be at most {high}")
    if ok_int["accept_min_milli"] and ok_int["reject_below_milli"] \
            and merged["reject_below_milli"] > merged["accept_min_milli"]:
        bad("reject_below_milli", "must not be above accept_min_milli")

    if "fallback_behavior" in settings and settings["fallback_behavior"] not in FALLBACK_BEHAVIORS:
        bad("fallback_behavior", f"must be one of: {', '.join(FALLBACK_BEHAVIORS)}")

    if "tier_penalty_milli" in settings:
        tiers = settings["tier_penalty_milli"]
        if not isinstance(tiers, dict):
            bad("tier_penalty_milli", "must be an object")
        else:
            for tier, penalty in tiers.items():
                if tier not in TIERS:
                    bad("tier_penalty_milli", f"unknown trust tier {str(tier)[:40]!r}; use {', '.join(TIERS)}")
                elif not _is_int(penalty) or not 0 <= penalty <= 1000:
                    bad("tier_penalty_milli", f"{tier} must be a whole number from 0 to 1000")

    if "model_penalties" in settings:
        entries = settings["model_penalties"]
        if not isinstance(entries, list):
            bad("model_penalties", "must be a list")
        elif len(entries) > MAX_MODEL_ENTRIES:
            bad("model_penalties", f"at most {MAX_MODEL_ENTRIES} entries")
        else:
            seen: set[str] = set()
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != {"model_version", "penalty_milli"}:
                    bad("model_penalties", "each entry needs exactly model_version and penalty_milli")
                    continue
                version, penalty = entry["model_version"], entry["penalty_milli"]
                if not isinstance(version, str) or not _MODEL_VERSION.match(version):
                    bad("model_penalties", "model_version must be 1 to 64 letters, digits, '.', '_' or '-'")
                elif version in seen:
                    bad("model_penalties", f"{version} is listed twice")
                else:
                    seen.add(version)
                if not _is_int(penalty) or not 0 <= penalty <= 1000:
                    bad("model_penalties", "penalty_milli must be a whole number from 0 to 1000")

    if "unsupported_model_versions" in settings:
        versions = settings["unsupported_model_versions"]
        if not isinstance(versions, list):
            bad("unsupported_model_versions", "must be a list")
        elif len(versions) > MAX_MODEL_ENTRIES:
            bad("unsupported_model_versions", f"at most {MAX_MODEL_ENTRIES} entries")
        elif any(not isinstance(v, str) or not _MODEL_VERSION.match(v) for v in versions):
            bad("unsupported_model_versions",
                "each model version must be 1 to 64 letters, digits, '.', '_' or '-'")
        elif len(set(versions)) != len(versions):
            bad("unsupported_model_versions", "a model version is listed twice")
    return problems


def build_config(settings: dict) -> dict:
    """The full, explicit settings stored for a new policy version: defaults, then the partner's values.
    Call only after validate_policy_settings returned no problems."""
    return normalize_config(settings)


def validate_policy_config(config: dict) -> None:
    problems = validate_policy_settings(config)
    if problems:
        raise ValueError("; ".join(f"{p['setting']}: {p['problem']}" for p in problems))


def effective_confidence(config: dict, tier: str, model_version: str, reported_milli: int) -> int:
    """The reported confidence, minus the penalty for the device's trust tier, minus the penalty for this
    packet's model version (if listed). Never below 0 or above 1000. An unrecognised tier is treated as the
    least trusted one, so a device can never gain trust by having an odd label."""
    cfg = normalize_config(config)
    tiers = cfg["tier_penalty_milli"]
    tier_penalty = tiers.get(tier, tiers["software_only"])
    model_penalty = next((m["penalty_milli"] for m in cfg["model_penalties"]
                          if m["model_version"] == model_version), 0)
    return max(0, min(1000, reported_milli - tier_penalty - model_penalty))


def is_model_supported(config: dict, model_version: str) -> bool:
    return model_version not in normalize_config(config)["unsupported_model_versions"]


def evaluate(config: dict, prior_milli: list[int], new_milli: int) -> str:
    """Return accept | fallback | reject for one participant.

    prior_milli / new_milli are EFFECTIVE confidences; prior is that participant's earlier ones, oldest first.
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


def outcome_to_report(config: dict, previous: str | None, outcome: str) -> str | None:
    """Which outcome, if any, must be reported to the partner for this transition (FR-C.8).

    * entering `reject` is ALWAYS reported, and no setting turns that off;
    * entering `fallback` from `accept` (or on a participant's first score) is reported only when the policy
      says `flag_for_review`; moving from `reject` down to `fallback` is not a new flag;
    * staying in the same state reports nothing again.
    """
    if outcome == "reject" and previous != "reject":
        return "reject"
    if (outcome == "fallback" and previous in (None, "accept")
            and normalize_config(config)["fallback_behavior"] == "flag_for_review"):
        return "fallback"
    return None
