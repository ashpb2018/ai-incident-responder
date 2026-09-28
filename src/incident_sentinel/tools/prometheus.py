"""Prometheus query tools (instant and range vectors)."""

from __future__ import annotations

import httpx

from ..settings import get_settings
from . import ToolSpec

_TIMEOUT = 20
_MAX_SERIES = 15


async def _query(path: str, params: dict) -> dict:
    base = get_settings().prometheus_url.rstrip("/")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{base}/api/v1/{path}", params=params)
        resp.raise_for_status()
        return resp.json()


def _result_of(body: dict) -> list:
    if body.get("status") != "success":
        raise ValueError(body.get("error", "query was not successful"))
    return (body.get("data") or {}).get("result") or []


async def instant_query(query: str) -> str:
    try:
        series = _result_of(await _query("query", {"query": query}))
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return f"Prometheus query failed: {exc}"
    if not series:
        return f"No data for: {query}"

    lines = [f"Instant query: {query}"]
    for item in series[:_MAX_SERIES]:
        metric = item.get("metric", {})
        label = metric.get("__name__", "") + str({k: v for k, v in metric.items() if k != "__name__"})
        value = (item.get("value") or [None, "?"])[1]
        lines.append(f"  {label}: {value}")
    if len(series) > _MAX_SERIES:
        lines.append(f"  ... ({len(series) - _MAX_SERIES} more series)")
    return "\n".join(lines)


async def range_query(query: str, minutes: int = 60) -> str:
    import time

    end = int(time.time())
    start = end - max(1, minutes) * 60
    params = {"query": query, "start": start, "end": end, "step": max(15, minutes * 60 // 100)}
    try:
        series = _result_of(await _query("query_range", params))
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return f"Prometheus range query failed: {exc}"
    if not series:
        return f"No data for: {query} (last {minutes}m)"

    lines = [f"Range query: {query} (last {minutes}m)"]
    for item in series[:_MAX_SERIES]:
        values = [float(v) for _, v in item.get("values", []) if _is_number(v)]
        if not values:
            continue
        metric = item.get("metric", {})
        label = str({k: v for k, v in metric.items() if k != "__name__"})
        lines.append(
            f"  {label}: min={min(values):.4g} max={max(values):.4g} "
            f"avg={sum(values) / len(values):.4g} latest={values[-1]:.4g}"
        )
    return "\n".join(lines)


def _is_number(value: object) -> bool:
    try:
        float(value)  # type: ignore[arg-type]
        return True
    except (TypeError, ValueError):
        return False


SPECS = [
    ToolSpec(
        name="query_prometheus_instant",
        description="Run an instant PromQL query and return the current value of each series.",
        parameters={"query": {"type": "string", "description": "PromQL expression."}},
        required=("query",),
        handler=lambda a: instant_query(a["query"]),
    ),
    ToolSpec(
        name="query_prometheus_range",
        description="Run a PromQL range query and summarise each series (min/max/avg/latest).",
        parameters={
            "query": {"type": "string", "description": "PromQL expression."},
            "minutes": {"type": "integer", "description": "Look-back window in minutes (default 60)."},
        },
        required=("query",),
        handler=lambda a: range_query(a["query"], a.get("minutes", 60)),
    ),
]
