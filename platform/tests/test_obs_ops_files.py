"""The dashboard and the alert rules may only use metrics that really exist (P0-13).

Without this, renaming a metric in the code would leave an alert that silently never fires."""
import json
import re
from pathlib import Path

import pytest
import yaml

from app import metrics

OPS = Path(__file__).resolve().parents[1] / "ops"
ALERTS = OPS / "prometheus" / "alerts.yml"
ALERT_TESTS = OPS / "prometheus" / "alerts_test.yml"
DASHBOARD = OPS / "grafana" / "dashboards" / "certivo-overview.json"

# Metrics Prometheus itself provides, not ours.
PROMETHEUS_OWN = {"up", "ALERTS"}


def our_metric_names(text: str) -> set[str]:
    return set(re.findall(r"\bcertivo_[a-z0-9_]+", text))


def all_expressions():
    rules = yaml.safe_load(ALERTS.read_text())["groups"]
    for group in rules:
        for rule in group["rules"]:
            yield rule["alert"], rule["expr"]


def test_every_metric_in_the_alert_rules_exists():
    known = metrics.metric_names()
    for alert, expr in all_expressions():
        missing = our_metric_names(expr) - known
        assert not missing, f"{alert} uses metrics that do not exist: {sorted(missing)}"


def test_every_metric_in_the_alert_tests_exists():
    missing = our_metric_names(ALERT_TESTS.read_text()) - metrics.metric_names()
    assert not missing, f"alerts_test.yml uses metrics that do not exist: {sorted(missing)}"


def test_every_metric_in_the_dashboard_exists():
    panels = json.loads(DASHBOARD.read_text())["panels"]
    for panel in panels:
        for target in panel["targets"]:
            missing = our_metric_names(target["expr"]) - metrics.metric_names()
            assert not missing, f"panel {panel['title']!r} uses metrics that do not exist: {sorted(missing)}"


def test_the_required_alerts_exist_and_each_explains_itself():
    alerts = {}
    for group in yaml.safe_load(ALERTS.read_text())["groups"]:
        for rule in group["rules"]:
            alerts[rule["alert"]] = rule
    for required in ("CertivoHighErrorRate", "CertivoPacketIngestLagHigh", "CertivoApiDown"):
        assert required in alerts, f"the guide requires an alert named {required}"
    for name, rule in alerts.items():
        assert rule["labels"]["severity"] in {"page", "ticket"}, name
        assert rule["annotations"]["summary"] and rule["annotations"]["description"], name
        assert rule.get("for"), f"{name} has no 'for': one bad moment would page someone"


def test_every_alert_has_a_test_that_makes_it_fire():
    tested = set()
    for case in yaml.safe_load(ALERT_TESTS.read_text())["tests"]:
        for check in case.get("alert_rule_test", []):
            if check.get("exp_alerts"):
                tested.add(check["alertname"])
    declared = {name for name, _ in all_expressions()}
    assert declared <= tested, f"alerts with no test that proves they fire: {sorted(declared - tested)}"


def test_the_dashboard_shows_error_rate_and_packet_lag_and_the_alerts():
    titles = {p["title"] for p in json.loads(DASHBOARD.read_text())["panels"]}
    assert {"Errors by endpoint", "Packet ingestion lag (live)", "Alerts firing now"} <= titles


def test_the_local_scrape_token_matches_the_compose_default():
    compose = yaml.safe_load((OPS.parent / "docker-compose.yml").read_text())
    default = compose["services"]["api"]["environment"]["CERTIVO_METRICS_TOKEN"]
    token = (OPS / "prometheus" / "metrics_token.local").read_text().strip()
    assert default.endswith(f":-{token}}}"), \
        "ops/prometheus/metrics_token.local must equal the compose default"


@pytest.mark.parametrize("path", [ALERTS, ALERT_TESTS, OPS / "prometheus" / "prometheus.yml"])
def test_the_prometheus_files_are_valid_yaml(path):
    assert yaml.safe_load(path.read_text())
