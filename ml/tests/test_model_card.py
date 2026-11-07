from __future__ import annotations

import json

from certivo_ml import baseline, model_card


def test_a_generated_card_is_acceptable_and_says_what_it_is(workspace):
    baseline.train()
    metrics = baseline.evaluate_model()
    text = model_card.render(metrics)
    assert model_card.validate(text) == []
    assert "SYNTHETIC" in text and "Not promoted" in text
    assert metrics["data_sha256"] in text
    assert f"{metrics['test']['accuracy']['value'] * 100:.1f}%" in text


def test_the_card_comes_out_identical_every_time(workspace):
    baseline.train()
    metrics = baseline.evaluate_model()
    assert model_card.render(metrics) == model_card.render(json.loads(json.dumps(metrics)))
    assert "\r" not in model_card.render(metrics)


def test_a_missing_section_is_caught(workspace):
    baseline.train()
    text = model_card.render(baseline.evaluate_model()).replace("## Limits and risks", "## Something else")
    assert any("Limits and risks" in p for p in model_card.validate(text))


def test_an_unfilled_placeholder_is_caught():
    problems = model_card.validate("## Model details\n{{name}}\n")
    assert any("placeholder" in p for p in problems)


def test_boasting_is_caught():
    for phrase in ("state of the art", "production-ready", "human-level", "guaranteed", "best-in-class"):
        problems = model_card.validate(f"## Model details\nThis is {phrase}.\n")
        assert any("claim-making" in p for p in problems), phrase


def test_synthetic_data_without_the_warning_is_caught(workspace):
    baseline.train()
    text = model_card.render(baseline.evaluate_model()).replace("says nothing about how well", "is great at")
    assert any("synthetic" in p.lower() for p in model_card.validate(text))


def test_a_card_that_does_not_state_promotion_is_caught(workspace):
    baseline.train()
    text = model_card.render(baseline.evaluate_model()).replace("**Not promoted.**", "Unknown.")
    assert any("promotion" in p for p in model_card.validate(text))


def test_the_committed_template_has_every_required_heading():
    template = (model_card.TEMPLATE).read_text(encoding="utf-8")
    for heading in model_card.REQUIRED_HEADINGS:
        assert f"## {heading}" in template
