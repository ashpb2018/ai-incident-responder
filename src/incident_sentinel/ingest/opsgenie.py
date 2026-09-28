"""Parse OpsGenie webhook payloads into :class:`Alert`."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..models import Alert, Severity, Source

_PRIORITY_MAP = {
    "P1": Severity.CRITICAL,
    "P2": Severity.HIGH,
    "P3": Severity.MEDIUM,
    "P4": Severity.LOW,
    "P5": Severity.INFO,
}


def _coerce_severity(priority: Any) -> Severity:
    if isinstance(priority, str):
        return _PRIORITY_MAP.get(priority.strip().upper(), Severity.HIGH)
    return Severity.HIGH


def _parse_tags(tags: Any) -> dict[str, str]:
    """OpsGenie tags may be ``["k:v", ...]`` or a list of objects; be tolerant."""
    result: dict[str, str] = {}
    if not isinstance(tags, list):
        return result
    for tag in tags:
        if isinstance(tag, str) and ":" in tag:
            key, _, value = tag.partition(":")
            result[key.strip()] = value.strip()
        elif isinstance(tag, dict):
            key = tag.get("key") or tag.get("name")
            if key:
                result[str(key)] = str(tag.get("value", ""))
    return result


def parse_opsgenie(payload: dict) -> Alert:
    """Extract an :class:`Alert` from an OpsGenie webhook body."""
    data = payload.get("alert", payload) if isinstance(payload.get("alert"), dict) else payload

    alert_id = str(data.get("alertId") or data.get("id") or payload.get("alertId") or "og-unknown")
    labels = _parse_tags(data.get("tags"))
    labels.setdefault("provider", "opsgenie")

    # Prefer an explicit service label over the integration "source" heuristic.
    service = labels.get("service") or labels.get("app") or "unknown"

    return Alert(
        id=alert_id,
        title=str(data.get("message") or "OpsGenie alert"),
        description=str(data.get("description") or ""),
        severity=_coerce_severity(data.get("priority")),
        service=service,
        source=Source.OPSGENIE,
        triggered_at=str(data.get("createdAt") or datetime.now(UTC).isoformat()),
        labels=labels,
        details={k: data[k] for k in ("source", "entity", "alias") if k in data},
    )
