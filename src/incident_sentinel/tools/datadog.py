"""Datadog query tools (metrics, logs, monitors).

All tools no-op with a clear message when Datadog credentials are absent, so
the agent can run in environments where only some integrations are configured.
"""

from __future__ import annotations

import time

import httpx

from ..settings import get_settings
from . import ToolSpec

_TIMEOUT = 20


def _credentials() -> tuple[str, str, str] | None:
    s = get_settings()
    if s.datadog_api_key and s.datadog_app_key:
        return s.datadog_api_key, s.datadog_app_key, s.datadog_site
    return None


def _headers(api_key: str, app_key: str) -> dict:
    return {"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key}


async def query_metrics(query: str, minutes: int = 60) -> str:
    creds = _credentials()
    if creds is None:
        return "Datadog is not configured (set DATADOG_API_KEY and DATADOG_APP_KEY)."
    api_key, app_key, site = creds
    now = int(time.time())
    params = {"query": query, "from": now - max(1, minutes) * 60, "to": now}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"https://api.{site}/api/v1/query",
                headers=_headers(api_key, app_key),
                params=params,
            )
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as exc:
        return f"Datadog metrics query failed: {exc}"

    series = body.get("series") or []
    if not series:
        return f"No Datadog series for: {query}"
    lines = [f"Datadog metrics: {query} (last {minutes}m)"]
    for s in series[:10]:
        points = [p[1] for p in s.get("pointlist", []) if p and p[1] is not None]
        scope = s.get("scope", "")
        if points:
            lines.append(
                f"  {scope}: min={min(points):.4g} max={max(points):.4g} latest={points[-1]:.4g}"
            )
    return "\n".join(lines)


async def search_logs(query: str, minutes: int = 30, limit: int = 20) -> str:
    creds = _credentials()
    if creds is None:
        return "Datadog is not configured (set DATADOG_API_KEY and DATADOG_APP_KEY)."
    api_key, app_key, site = creds
    now_ms = int(time.time() * 1000)
    payload = {
        "filter": {"query": query, "from": now_ms - max(1, minutes) * 60_000, "to": now_ms},
        "page": {"limit": min(limit, 50)},
        "sort": "-timestamp",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"https://api.{site}/api/v2/logs/events/search",
                headers=_headers(api_key, app_key),
                json=payload,
            )
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as exc:
        return f"Datadog log search failed: {exc}"

    events = body.get("data") or []
    if not events:
        return f"No Datadog logs for: {query}"
    lines = [f"Datadog logs: {query} ({len(events)} shown)"]
    for event in events:
        attrs = event.get("attributes", {})
        message = str(attrs.get("message", "")).replace("\n", " ")[:200]
        lines.append(f"  [{attrs.get('status', '?')}] {message}")
    return "\n".join(lines)


SPECS = [
    ToolSpec(
        name="query_datadog_metrics",
        description="Query a Datadog metric over a time window and summarise each series.",
        parameters={
            "query": {"type": "string", "description": "Datadog metric query."},
            "minutes": {"type": "integer", "description": "Look-back window (default 60)."},
        },
        required=("query",),
        handler=lambda a: query_metrics(a["query"], a.get("minutes", 60)),
    ),
    ToolSpec(
        name="search_datadog_logs",
        description="Search Datadog logs with a query string over a recent window.",
        parameters={
            "query": {"type": "string", "description": "Datadog log search query."},
            "minutes": {"type": "integer", "description": "Look-back window (default 30)."},
            "limit": {"type": "integer", "description": "Max events (default 20, max 50)."},
        },
        required=("query",),
        handler=lambda a: search_logs(a["query"], a.get("minutes", 30), a.get("limit", 20)),
    ),
]
