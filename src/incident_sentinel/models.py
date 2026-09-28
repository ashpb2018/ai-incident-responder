"""Domain models: the inbound alert and the outbound incident report."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
        return order[self.value]

    def at_least(self, floor: Severity) -> bool:
        return self.rank >= floor.rank


class Source(str, Enum):
    PAGERDUTY = "pagerduty"
    OPSGENIE = "opsgenie"
    MANUAL = "manual"


class Alert(BaseModel):
    id: str
    title: str
    description: str = ""
    severity: Severity = Severity.MEDIUM
    service: str = "unknown"
    source: Source = Source.MANUAL
    triggered_at: str = ""
    labels: dict[str, str] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)

    def as_briefing(self) -> str:
        """Render the alert as a Markdown briefing for the investigating agent."""
        lines = [
            "## Incident alert",
            f"- **ID:** {self.id}",
            f"- **Title:** {self.title}",
            f"- **Severity:** {self.severity.value.upper()}",
            f"- **Service:** {self.service}",
            f"- **Source:** {self.source.value}",
            f"- **Triggered at:** {self.triggered_at or 'unknown'}",
        ]
        if self.description:
            lines += ["", f"**Description:** {self.description}"]
        if self.labels:
            rendered = ", ".join(f"{k}={v}" for k, v in self.labels.items())
            lines += ["", f"**Labels:** {rendered}"]
        if self.details:
            lines += ["", "**Details:**", "```json", json.dumps(self.details, indent=2), "```"]
        return "\n".join(lines)


class Hypothesis(BaseModel):
    statement: str = Field(description="The hypothesised root cause")
    likelihood: str = Field(description="high, medium, or low")
    evidence: list[str] = Field(default_factory=list, description="Evidence supporting it")
    confidence: float = Field(default=0.0, description="Confidence between 0.0 and 1.0")


class TimelineEntry(BaseModel):
    at: str = Field(description="Approximate time of the finding")
    finding: str = Field(description="What was observed")


class IncidentReport(BaseModel):
    title: str
    severity: str
    impact: str = ""
    affected_services: list[str] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    immediate_actions: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
