"""FastAPI webhook server that turns alerts into investigations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from .agent import IncidentAgent
from .ingest import parse_opsgenie, parse_pagerduty, verify_hmac
from .models import Alert, Severity, Source
from .settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s  %(levelname)-7s  %(message)s",
)
logger = logging.getLogger("sentinel")

agent = IncidentAgent()
app = FastAPI(
    title="Sentinel — Incident Response Agent",
    version="0.1.0",
    description="Receives PagerDuty/OpsGenie alerts and produces root-cause reports.",
)


def _min_severity() -> Severity:
    try:
        return Severity(get_settings().min_severity.lower())
    except ValueError:
        return Severity.HIGH


async def _investigate_in_background(alert: Alert) -> None:
    try:
        report = await agent.investigate(alert)
        logger.info("Report for %s:\n%s", alert.id, report.model_dump_json(indent=2))
    except Exception:  # noqa: BLE001
        logger.exception("Investigation failed for %s", alert.id)


def _accept_or_skip(alert: Alert, background: BackgroundTasks) -> dict:
    if not alert.severity.at_least(_min_severity()):
        return {"status": "skipped", "reason": f"severity {alert.severity.value} below threshold"}
    logger.info("Accepted %s: %s [%s]", alert.id, alert.title, alert.severity.value)
    background.add_task(_investigate_in_background, alert)
    return {"status": "accepted", "alert_id": alert.id, "severity": alert.severity.value}


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok", "time": datetime.now(UTC).isoformat()}


@app.post("/webhook/pagerduty", tags=["webhooks"])
async def pagerduty_webhook(
    request: Request,
    background: BackgroundTasks,
    signature: str | None = Header(default=None, alias="X-PagerDuty-Signature"),
) -> dict:
    body = await request.body()
    if not verify_hmac(get_settings().pagerduty_webhook_secret, body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    return _accept_or_skip(_parse(parse_pagerduty, body), background)


@app.post("/webhook/opsgenie", tags=["webhooks"])
async def opsgenie_webhook(
    request: Request,
    background: BackgroundTasks,
    signature: str | None = Header(default=None, alias="X-OpsGenie-Signature"),
) -> dict:
    body = await request.body()
    if not verify_hmac(get_settings().opsgenie_webhook_secret, body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    return _accept_or_skip(_parse(parse_opsgenie, body), background)


@app.post("/investigate", tags=["investigation"])
async def investigate(request: Request) -> dict:
    """Synchronously investigate a manually-supplied alert and return the report."""
    payload = await _json(request)
    alert = Alert(
        id=str(payload.get("id", f"manual-{int(datetime.now(UTC).timestamp())}")),
        title=payload.get("title", "Manual investigation"),
        description=payload.get("description", ""),
        severity=Severity(payload.get("severity", "high")),
        service=payload.get("service", "unknown"),
        source=Source.MANUAL,
        triggered_at=payload.get("triggered_at", datetime.now(UTC).isoformat()),
        labels=payload.get("labels", {}),
        details=payload.get("details", {}),
    )
    report = await agent.investigate(alert)
    return report.model_dump()


async def _json(request: Request) -> dict:
    try:
        return await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc


def _parse(parser, body: bytes) -> Alert:
    import json

    try:
        payload = json.loads(body)
        return parser(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Cannot parse payload: {exc}") from exc
