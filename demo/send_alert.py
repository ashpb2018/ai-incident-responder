#!/usr/bin/env python3
"""
Send a demo alert to the incident agent and stream/display the report.

Usage:
  python demo/send_alert.py --issue crashloop
  python demo/send_alert.py --issue oom --service payments
  python demo/send_alert.py --custom '{"title":"...", "severity":"high", "service":"checkout"}'
  python demo/send_alert.py --list
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone


AGENT_URL = "http://localhost:8080"

# Pre-built alert scenarios matching inject_issue.sh
SCENARIOS: dict[str, dict] = {
    "crashloop": {
        "title": "checkout-service: pods in CrashLoopBackOff",
        "description": (
            "3/3 checkout pods are restarting repeatedly. "
            "Error rate is 100%. Last seen 2 minutes ago."
        ),
        "severity": "high",
        "service": "checkout",
        "labels": {"namespace": "demo", "env": "production", "team": "platform"},
        "details": {
            "alert_source": "kube-state-metrics",
            "metric": "kube_pod_container_status_restarts_total",
            "threshold": "5 restarts in 5 minutes",
        },
    },
    "oom": {
        "title": "checkout-service: OOMKilled pods detected",
        "description": (
            "Checkout pods are being terminated by the OOM killer. "
            "Container memory limit is 32Mi. Restarts: 8 in last 10 minutes."
        ),
        "severity": "critical",
        "service": "checkout",
        "labels": {"namespace": "demo", "env": "production"},
        "details": {
            "alert_source": "kube-state-metrics",
            "metric": "kube_pod_container_status_last_terminated_reason",
            "reason": "OOMKilled",
        },
    },
    "imagefail": {
        "title": "checkout-service: image pull failure after deployment",
        "description": (
            "New deployment is stuck. Pods cannot pull image "
            "mycompany/checkout-service:v3.1.4-hotfix-NONEXISTENT. "
            "Rollout has been failing for 5 minutes."
        ),
        "severity": "high",
        "service": "checkout",
        "labels": {"namespace": "demo", "env": "production", "team": "platform"},
        "details": {
            "alert_source": "kube-state-metrics",
            "metric": "kube_pod_container_status_waiting_reason",
            "reason": "ImagePullBackOff",
        },
    },
    "scale0": {
        "title": "checkout-service: 0 pods available",
        "description": (
            "All checkout replicas are gone. Service is returning 503. "
            "Possible accidental scale-down or deployment deletion."
        ),
        "severity": "critical",
        "service": "checkout",
        "labels": {"namespace": "demo", "env": "production"},
        "details": {
            "alert_source": "kube-state-metrics",
            "metric": "kube_deployment_status_replicas_ready",
            "expected": 3,
            "actual": 0,
        },
    },
    "pending": {
        "title": "checkout-service: pods stuck in Pending state",
        "description": (
            "New checkout pods cannot be scheduled. "
            "Cluster may have insufficient resources. "
            "Pods have been Pending for 8 minutes."
        ),
        "severity": "high",
        "service": "checkout",
        "labels": {"namespace": "demo", "env": "production"},
        "details": {
            "alert_source": "kube-state-metrics",
            "metric": "kube_pod_status_phase",
            "phase": "Pending",
            "count": 2,
        },
    },
}


def wait_for_server(url: str, timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.urlopen(f"{url}/health", timeout=2)
            if req.getcode() == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def send_alert(payload: dict, url: str) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{url}/investigate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"\n❌ Agent returned HTTP {e.code}: {body[:500]}", file=sys.stderr)
        sys.exit(1)


def print_report(report: dict) -> None:
    BOLD = "\033[1m"; CYAN = "\033[0;36m"; GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"; RED = "\033[0;31m"; RESET = "\033[0m"

    severity_colour = {
        "critical": RED, "high": YELLOW, "medium": CYAN, "low": GREEN
    }.get(report.get("severity", "medium"), CYAN)

    print(f"\n{'═'*70}")
    print(f"{BOLD}INCIDENT REPORT{RESET}")
    print(f"{'═'*70}")

    print(f"\n{BOLD}Title:{RESET}    {report.get('title', 'N/A')}")
    sev = report.get("severity", "unknown").upper()
    print(f"{BOLD}Severity:{RESET} {severity_colour}{sev}{RESET}")
    print(f"{BOLD}Services:{RESET} {', '.join(report.get('affected_services', []))}")
    dur = report.get("investigation_duration_seconds", 0)
    tools = report.get("tools_used", [])
    print(f"{BOLD}Duration:{RESET} {dur:.1f}s  |  {BOLD}Tools:{RESET} {len(tools)} used ({', '.join(tools[:4])}{'...' if len(tools) > 4 else ''})")

    print(f"\n{BOLD}Impact:{RESET}")
    print(textwrap.fill(report.get("impact_summary", ""), width=68, initial_indent="  "))

    timeline = report.get("investigation_timeline", [])
    if timeline:
        print(f"\n{BOLD}Investigation Timeline:{RESET}")
        for entry in timeline:
            ts = entry.get("timestamp", "")
            finding = entry.get("finding", "")
            print(f"  {CYAN}{ts}{RESET}  {finding}")

    hypotheses = report.get("root_cause_hypotheses", [])
    if hypotheses:
        print(f"\n{BOLD}Root Cause Hypotheses:{RESET}")
        for i, h in enumerate(hypotheses, 1):
            likelihood = h.get("likelihood", "?")
            conf = h.get("confidence_score", 0)
            lcolour = {
                "high": RED, "medium": YELLOW, "low": GREEN
            }.get(likelihood, CYAN)
            print(f"\n  {BOLD}#{i}{RESET} [{lcolour}{likelihood.upper()}{RESET} — {conf:.0%}]")
            print(f"     {h.get('hypothesis', '')}")
            for ev in h.get("supporting_evidence", [])[:3]:
                print(f"       • {ev}")

    actions = report.get("immediate_actions", [])
    if actions:
        print(f"\n{BOLD}Immediate Actions:{RESET}")
        for a in actions:
            print(f"  → {a}")

    recs = report.get("long_term_recommendations", [])
    if recs:
        print(f"\n{BOLD}Long-term Recommendations:{RESET}")
        for r in recs:
            print(f"  ◦ {r}")

    print(f"\n{'═'*70}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a demo alert to the AI incident response agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Examples:
          python demo/send_alert.py --issue crashloop
          python demo/send_alert.py --issue oom --service payments
          python demo/send_alert.py --custom '{"title":"High latency","severity":"high","service":"checkout"}'
          python demo/send_alert.py --list
        """),
    )
    parser.add_argument("--issue", choices=list(SCENARIOS), help="Pre-built scenario to use")
    parser.add_argument("--service", default=None, help="Override the service name in the scenario")
    parser.add_argument("--custom", default=None, help="Raw JSON alert payload (overrides --issue)")
    parser.add_argument("--url", default=AGENT_URL, help=f"Agent base URL (default: {AGENT_URL})")
    parser.add_argument("--list", action="store_true", help="List available scenarios and exit")
    args = parser.parse_args()

    if args.list:
        print("Available demo scenarios:\n")
        for name, s in SCENARIOS.items():
            print(f"  {name:12s}  {s['severity'].upper():8s}  {s['title']}")
        print()
        return

    if args.custom:
        try:
            payload = json.loads(args.custom)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in --custom: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.issue:
        payload = dict(SCENARIOS[args.issue])
        if args.service:
            payload["service"] = args.service
            payload["title"] = payload["title"].replace("checkout", args.service)
        payload["triggered_at"] = datetime.now(timezone.utc).isoformat()
    else:
        parser.print_help()
        sys.exit(1)

    print(f"\n🔍 Connecting to agent at {args.url}...")
    if not wait_for_server(args.url, timeout=10):
        print(f"❌ Agent not reachable at {args.url}/health. Is the server running?", file=sys.stderr)
        print("   Start it with:  source .venv/bin/activate && python main.py", file=sys.stderr)
        sys.exit(1)

    print(f"✅ Agent is up")
    print(f"📨 Sending alert: [{payload.get('severity','?').upper()}] {payload.get('title','')}")
    print(f"⏳ Investigating... (this may take 1–5 minutes with a local model)\n")

    t0 = time.time()
    report = send_alert(payload, args.url)
    elapsed = time.time() - t0

    print_report(report)
    print(f"Total wall-clock time: {elapsed:.1f}s")

    # Write report to file
    out = f"demo/report_{payload.get('service','unknown')}_{int(t0)}.json"
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved to: {out}\n")


if __name__ == "__main__":
    main()
