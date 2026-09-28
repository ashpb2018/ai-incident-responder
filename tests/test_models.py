"""Model behaviour: severity ordering and alert briefing."""

from __future__ import annotations

from incident_sentinel.models import Alert, Severity


def test_severity_ordering():
    assert Severity.CRITICAL.at_least(Severity.HIGH)
    assert Severity.HIGH.at_least(Severity.HIGH)
    assert not Severity.MEDIUM.at_least(Severity.HIGH)
    assert not Severity.LOW.at_least(Severity.CRITICAL)


def test_alert_briefing_includes_key_fields():
    alert = Alert(
        id="a1",
        title="Checkout latency spike",
        severity=Severity.HIGH,
        service="checkout",
        labels={"env": "prod"},
        details={"region": "us-east-1"},
    )
    briefing = alert.as_briefing()
    assert "Checkout latency spike" in briefing
    assert "HIGH" in briefing
    assert "checkout" in briefing
    assert "env=prod" in briefing
    assert "us-east-1" in briefing
