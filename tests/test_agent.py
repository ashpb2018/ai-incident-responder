"""The reason-act loop, driven by a scripted fake backend."""

from __future__ import annotations

import json

from incident_sentinel.agent import IncidentAgent
from incident_sentinel.backends.base import LLMBackend, ToolCall, Turn
from incident_sentinel.models import Alert, Severity
from incident_sentinel.tools import Catalogue, ToolSpec


class FakeBackend(LLMBackend):
    def __init__(self, turns: list[Turn], report: dict) -> None:
        self._turns = list(turns)
        self._report = report
        self.sends = 0

    def set_tools(self, tool_schemas):
        self.tools = tool_schemas

    async def send(self, content):
        self.sends += 1
        return self._turns.pop(0)

    def transcript(self):
        return "investigation notes"

    async def summarise_json(self, prompt, schema):
        return json.dumps(self._report)

    @property
    def label(self):
        return "Fake"

    @property
    def model(self):
        return "fake-1"


async def _echo(_a: dict) -> str:
    return "tool output"


def _catalogue() -> Catalogue:
    return Catalogue(
        [
            ToolSpec(
                name="query_prometheus_instant",
                description="d",
                parameters={"query": {"type": "string"}},
                required=("query",),
                handler=_echo,
            )
        ]
    )


def _alert() -> Alert:
    return Alert(id="a1", title="Boom", severity=Severity.HIGH, service="checkout")


_REPORT = {
    "title": "Checkout outage",
    "severity": "high",
    "impact": "5xx spike",
    "hypotheses": [{"statement": "bad deploy", "likelihood": "high"}],
    "immediate_actions": ["roll back"],
}


async def test_loop_runs_tool_then_reports(monkeypatch):
    backend = FakeBackend(
        turns=[
            Turn(text="looking", tool_calls=[ToolCall("c1", "query_prometheus_instant", {"query": "up"})], stop_reason="tool_use"),
            Turn(text="done", stop_reason="end_turn"),
        ],
        report=_REPORT,
    )
    monkeypatch.setattr("incident_sentinel.agent.build_backend", lambda: backend)

    agent = IncidentAgent(catalogue=_catalogue())
    report = await agent.investigate(_alert())

    assert report.title == "Checkout outage"
    assert report.hypotheses[0].statement == "bad deploy"
    assert "query_prometheus_instant" in report.tools_used


async def test_unknown_tool_is_reported_gracefully(monkeypatch):
    backend = FakeBackend(
        turns=[
            Turn(tool_calls=[ToolCall("c1", "nope", {})], stop_reason="tool_use"),
            Turn(text="done", stop_reason="end_turn"),
        ],
        report=_REPORT,
    )
    monkeypatch.setattr("incident_sentinel.agent.build_backend", lambda: backend)
    agent = IncidentAgent(catalogue=_catalogue())
    report = await agent.investigate(_alert())
    assert report.title == "Checkout outage"


async def test_failed_report_extraction_falls_back(monkeypatch):
    class BadReport(FakeBackend):
        async def summarise_json(self, prompt, schema):
            return "not json"

    backend = BadReport(turns=[Turn(text="done", stop_reason="end_turn")], report={})
    monkeypatch.setattr("incident_sentinel.agent.build_backend", lambda: backend)
    agent = IncidentAgent(catalogue=_catalogue())
    report = await agent.investigate(_alert())
    # Fallback report uses the alert's own fields.
    assert report.title == "Boom"
    assert report.severity == "high"


def test_catalogue_schema_is_wellformed():
    schemas = _catalogue().schemas()
    assert schemas[0]["name"] == "query_prometheus_instant"
    assert schemas[0]["input_schema"]["required"] == ["query"]
