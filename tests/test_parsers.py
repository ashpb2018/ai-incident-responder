"""Alert parsing from PagerDuty and OpsGenie payloads."""

from __future__ import annotations

from incident_sentinel.ingest import parse_opsgenie, parse_pagerduty
from incident_sentinel.models import Severity, Source


def test_pagerduty_v3_event_shape():
    alert = parse_pagerduty(
        {
            "event": {
                "data": {
                    "id": "PD123",
                    "title": "High error rate on checkout",
                    "severity": "critical",
                    "service": {"summary": "checkout"},
                }
            }
        }
    )
    assert alert.id == "PD123"
    assert alert.severity is Severity.CRITICAL
    assert alert.service == "checkout"
    assert alert.source is Source.PAGERDUTY


def test_pagerduty_non_string_severity_defaults_high():
    alert = parse_pagerduty({"event": {"data": {"severity": {"weird": "object"}}}})
    assert alert.severity is Severity.HIGH


def test_pagerduty_empty_payload_does_not_crash():
    alert = parse_pagerduty({})
    assert alert.id == "pd-unknown"
    assert alert.source is Source.PAGERDUTY


def test_opsgenie_priority_maps_to_severity():
    alert = parse_opsgenie({"alert": {"alertId": "OG1", "message": "disk full", "priority": "P1"}})
    assert alert.id == "OG1"
    assert alert.severity is Severity.CRITICAL


def test_opsgenie_string_tags_parsed():
    alert = parse_opsgenie(
        {"alert": {"message": "x", "priority": "P2", "tags": ["service:payments", "env:prod"]}}
    )
    assert alert.service == "payments"
    assert alert.labels["env"] == "prod"


def test_opsgenie_object_tags_do_not_crash():
    alert = parse_opsgenie(
        {"alert": {"message": "x", "priority": "P3", "tags": [{"key": "team", "value": "sre"}]}}
    )
    assert alert.labels["team"] == "sre"
    assert alert.severity is Severity.MEDIUM
