"""Parse PagerDuty v2/v3 webhook payloads into :class:`Alert`."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..models import Alert, Severity, Source

# PagerDuty priority/urgency vocabulary mapped onto our severity scale.
_SEVERITY_MAP = {
    "critical": Severity.CRITICAL,
    "error": Severity.HIGH,
    "high": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "warn": Severity.MEDIUM,
    "info": Severity.LOW,
    "low": Severity.LOW,
}


def _coerce_severity(value: Any) -> Severity:
    """Map a PagerDuty severity/urgency value to :class:`Severity`, defensively."""
    if isinstance(value, str):
        return _SEVERITY_MAP.get(value.strip().lower(), Severity.HIGH)
    return Severity.HIGH


def parse_pagerduty(payload: dict) -> Alert:
    """Extract an :class:`Alert` from a PagerDuty webhook body.

    Handles both the v3 ``{"event": {...}}`` shape and the older
    ``{"messages": [...]}`` shape, and never assumes a field is present or a
    particular type.
    """
    event = payload.get("event")
    if isinstance(event, dict):
        data = event.get("data", {}) or {}
    else:
        messages = payload.get("messages")
        first = messages[0] if isinstance(messages, list) and messages else payload
        data = first.get("incident", first) if isinstance(first, dict) else {}

    incident_id = str(data.get("id") or payload.get("id") or "pd-unknown")
    title = data.get("title") or data.get("summary") or "PagerDuty incident"

    severity = _coerce_severity(
        data.get("severity") or data.get("urgency") or (data.get("priority") or {}).get("summary")
    )

    service = "unknown"
    service_obj = data.get("service")
    if isinstance(service_obj, dict):
        service = service_obj.get("summary") or service_obj.get("name") or "unknown"

    return Alert(
        id=incident_id,
        title=str(title),
        description=str(data.get("description") or data.get("body") or ""),
        severity=severity,
        service=str(service),
        source=Source.PAGERDUTY,
        triggered_at=str(data.get("created_at") or datetime.now(UTC).isoformat()),
        labels={"provider": "pagerduty"},
        details={k: data[k] for k in ("html_url", "status") if k in data},
    )
