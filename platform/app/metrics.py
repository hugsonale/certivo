"""Metrics (P0-13, docs/adr/0019). Prometheus text format, served by GET /metrics (app/observability.py).

Rules for anything added here:
  * Labels must have a SMALL, FIXED set of values. Never put a session ID, partner ID, user-supplied
    text or a raw URL path in a label: each distinct value creates a new time series, and an attacker
    could create millions.
  * Nothing here may describe a person. Counts, timings and fixed code words only.

The names below are referenced by ops/prometheus/alerts.yml and the Grafana dashboard.
tests/test_obs_ops_files.py fails if either refers to a metric that does not exist here.

LIMITATION, stated plainly: these counters live in this process. Run ONE API process per scrape target
(as docker-compose does), or switch to prometheus_client's multiprocess mode first. The Celery worker
exports no metrics yet; its work shows up in the structured logs.
"""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, ProcessCollector

REGISTRY = CollectorRegistry()
ProcessCollector(registry=REGISTRY)  # CPU, memory and open files of this process (Linux)

_KNOWN_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

HTTP_REQUESTS = Counter(
    "certivo_http_requests_total", "HTTP requests handled, by method, route template and status code.",
    ["method", "route", "status"], registry=REGISTRY)
HTTP_DURATION = Histogram(
    "certivo_http_request_duration_seconds", "Time to serve a request, by method and route template.",
    ["method", "route"], registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0))
HTTP_IN_PROGRESS = Gauge(
    "certivo_http_requests_in_progress", "Requests being served right now.", registry=REGISTRY)

# `via` is "live" (a packet sent as it happened) or "batch" (buffered by the SDK during an outage and
# uploaded later). Batch packets are late by nature, so alerts look at live packets only.
PACKETS = Counter(
    "certivo_packets_total", "Score packets received, by how they arrived and what happened to them.",
    ["via", "result"], registry=REGISTRY)           # result: accepted | duplicate | rejected
PACKETS_REJECTED = Counter(
    "certivo_packets_rejected_total", "Score packets refused, by the API error code given.",
    ["via", "code"], registry=REGISTRY)
PACKET_LAG = Histogram(
    "certivo_packet_ingest_lag_seconds",
    "Packet ingestion lag: when we received a packet minus when the interval it describes ended.",
    ["via"], registry=REGISTRY,
    buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1800, 3600))

AUTH_FAILURES = Counter(
    "certivo_auth_failures_total", "Failed credential checks, by reason.", ["reason"], registry=REGISTRY)
RATE_LIMITED = Counter(
    "certivo_rate_limited_total", "Requests refused with 429, by which limit was hit.", ["scope"],
    registry=REGISTRY)
ATTESTATION_SIGN_FAILURES = Counter(
    "certivo_attestation_sign_failures_total",
    "Times the signer could not be reached, so an attestation was queued instead of signed.",
    registry=REGISTRY)
BUILD_INFO = Gauge("certivo_build_info", "Always 1; the labels say which build is running.",
                   ["version", "env"], registry=REGISTRY)


def method_label(method: str) -> str:
    return method if method in _KNOWN_METHODS else "OTHER"


def record_request(method: str, route: str, status: int, duration_s: float) -> None:
    method = method_label(method)
    HTTP_REQUESTS.labels(method, route, str(status)).inc()
    HTTP_DURATION.labels(method, route).observe(duration_s)


def record_packet(via: str, lag_ms: int | None, duplicate: bool = False) -> None:
    """A packet we accepted (or recognised as a duplicate of one we already hold)."""
    PACKETS.labels(via, "duplicate" if duplicate else "accepted").inc()
    if lag_ms is not None and not duplicate:
        # A packet can look "from the future" by up to the allowed clock skew; that is zero lag.
        PACKET_LAG.labels(via).observe(max(lag_ms, 0) / 1000.0)


def record_rejection(via: str, code: str) -> None:
    PACKETS.labels(via, "rejected").inc()
    PACKETS_REJECTED.labels(via, code).inc()


def record_auth_failure(reason: str) -> None:
    AUTH_FAILURES.labels(reason).inc()


def record_rate_limited(scope: str) -> None:
    RATE_LIMITED.labels(scope).inc()


def record_signing_failure() -> None:
    ATTESTATION_SIGN_FAILURES.inc()


def metric_names() -> set[str]:
    """Every metric name this process can export, including the _total/_bucket/_sum/_count forms."""
    names: set[str] = set()
    for family in REGISTRY.collect():
        for sample in family.samples:
            names.add(sample.name)
        names.add(family.name)
    # Samples exist only after a label set has been used, so add the suffixes for every family.
    for family in list(REGISTRY.collect()):
        if family.type == "counter":
            names.add(family.name + "_total")
        elif family.type == "histogram":
            names.update(family.name + s for s in ("_bucket", "_sum", "_count"))
    return names
