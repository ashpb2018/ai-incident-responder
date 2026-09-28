"""The incident-investigation agent: a backend-agnostic reason-act loop."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

from .backends import build_backend
from .backends.base import LLMBackend, ToolCall
from .models import Alert, IncidentReport
from .settings import get_settings
from .tools import Catalogue, build_catalogue

logger = logging.getLogger(__name__)

# JSON schema requested from the model when extracting the final report. Keys
# mirror IncidentReport so the parsed object maps straight onto it.
REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
        "impact": {"type": "string"},
        "affected_services": {"type": "array", "items": {"type": "string"}},
        "timeline": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"at": {"type": "string"}, "finding": {"type": "string"}},
                "required": ["at", "finding"],
            },
        },
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "likelihood": {"type": "string", "enum": ["high", "medium", "low"]},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                },
                "required": ["statement", "likelihood"],
            },
        },
        "immediate_actions": {"type": "array", "items": {"type": "string"}},
        "follow_ups": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "severity", "impact", "hypotheses", "immediate_actions"],
}


class IncidentAgent:
    """Runs one investigation per :meth:`investigate` call."""

    def __init__(self, catalogue: Catalogue | None = None) -> None:
        self._catalogue = catalogue or build_catalogue()

    async def investigate(self, alert: Alert) -> IncidentReport:
        settings = get_settings()
        started = time.monotonic()
        logger.info("Investigating %s (%s) via %s", alert.id, alert.severity.value, settings.backend.value)

        backend = build_backend()
        backend.set_tools(self._catalogue.schemas())
        tools_used: list[str] = []

        now = datetime.now(UTC).isoformat()
        turn = await backend.send(
            f"Current UTC time: {now}\n\n{alert.as_briefing()}\n\n"
            "Investigate this incident with the available tools, then explain the "
            "most likely root cause."
        )

        budget = settings.max_agent_steps
        for step in range(budget):
            if not turn.wants_tools:
                break
            results = await self._run_tools(turn.tool_calls, tools_used)
            # On the final permitted step, nudge the model to conclude instead of
            # requesting yet more tools whose results we could not act on.
            if step == budget - 1:
                results.append(
                    {
                        "tool_use_id": "budget-notice",
                        "content": "Investigation step budget reached. Summarise your findings now.",
                    }
                )
            turn = await backend.send(results)

        duration = time.monotonic() - started
        report = await self._extract_report(backend, alert, tools_used, duration)
        logger.info(
            "Report for %s ready in %.1fs (%d hypotheses, %d tools)",
            alert.id, duration, len(report.hypotheses), len(report.tools_used),
        )
        return report

    async def _run_tools(self, calls: list[ToolCall], tools_used: list[str]) -> list[dict]:
        async def run(call: ToolCall) -> dict:
            if call.name not in tools_used:
                tools_used.append(call.name)
            handler = self._catalogue.handler(call.name)
            if handler is None:
                return {"tool_use_id": call.id, "content": f"Unknown tool: {call.name}"}
            try:
                output = await handler(call.arguments)
            except Exception as exc:  # noqa: BLE001 - reported back to the model
                output = f"Tool {call.name} failed: {exc}"
            return {"tool_use_id": call.id, "content": str(output)}

        return list(await asyncio.gather(*(run(c) for c in calls)))

    async def _extract_report(
        self, backend: LLMBackend, alert: Alert, tools_used: list[str], duration: float
    ) -> IncidentReport:
        prompt = (
            "Produce the final incident report as JSON.\n\n"
            f"Alert:\n{alert.as_briefing()}\n\n"
            f"Investigation notes:\n{backend.transcript()}\n\n"
            f"Tools used: {', '.join(tools_used) or 'none'}"
        )
        try:
            raw = await backend.summarise_json(prompt, REPORT_SCHEMA)
            data = json.loads(raw)
            data["tools_used"] = tools_used
            data["duration_seconds"] = round(duration, 2)
            return IncidentReport(**data)
        except Exception as exc:  # noqa: BLE001 - fall back to a minimal report
            logger.error("Report extraction failed for %s: %s", alert.id, exc)
            return IncidentReport(
                title=alert.title,
                severity=alert.severity.value,
                impact=f"Investigation ran for {alert.service}; structured extraction failed.",
                affected_services=[alert.service],
                immediate_actions=["Review the investigation transcript in the logs."],
                tools_used=tools_used,
                duration_seconds=round(duration, 2),
            )
