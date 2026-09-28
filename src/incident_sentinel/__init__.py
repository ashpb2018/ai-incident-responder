"""Sentinel — an autonomous incident-response agent.

Sentinel receives an alert (PagerDuty, OpsGenie, or a manual trigger), then
investigates the incident with live observability tools — Prometheus, Datadog,
Kubernetes, and host diagnostics — before writing a structured root-cause
report. The reasoning is driven by a pluggable LLM backend (Anthropic, AWS
Bedrock, or any OpenAI-compatible/Ollama server).
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
