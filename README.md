# Sentinel — Autonomous Incident Response Agent

[![CI](https://github.com/ashpb2018/ai-incident-responder/actions/workflows/ci.yml/badge.svg)](https://github.com/ashpb2018/ai-incident-responder/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**Sentinel receives a production alert, investigates it with live observability data, and writes a structured root-cause report — no human in the loop.**

When a PagerDuty or OpsGenie alert fires (or you trigger one manually), Sentinel drives an LLM through a reason-act loop: it queries Prometheus and Datadog, inspects Kubernetes workloads, runs host diagnostics, correlates what it finds, and returns ranked root-cause hypotheses with immediate actions and follow-ups.

Any of three LLM backends works behind one interface — **Anthropic**, **AWS Bedrock**, or an **OpenAI-compatible/Ollama** server — so you can run fully local or fully hosted without touching the agent code.

---

## Contents

- [Highlights](#highlights)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Backends](#backends)
- [Security model](#security-model)
- [Development](#development)
- [Demo](#demo)
- [License](#license)

---

## Highlights

- **Alert-driven** — signed PagerDuty/OpsGenie webhooks, plus a synchronous `/investigate` endpoint for manual runs.
- **Real investigation tools** — Prometheus (instant + range), Datadog (metrics + logs), Kubernetes (`kubectl` pods/describe/logs/events/top), and host diagnostics (ping, DNS, HTTP checks).
- **Provider-agnostic** — one `LLMBackend` contract; swap models via config.
- **Safe by construction** — see [Security](#security-model) below.
- **Structured output** — every investigation yields a typed `IncidentReport` (impact, timeline, ranked hypotheses, actions).

---

## Architecture

```
src/incident_sentinel/
├── settings.py         # env-driven configuration
├── models.py           # Alert + IncidentReport domain models
├── ingest/             # webhook parsing + HMAC signature verification
│   ├── pagerduty.py
│   ├── opsgenie.py
│   └── signature.py
├── tools/              # investigation tools the agent can call
│   ├── prometheus.py
│   ├── datadog.py
│   ├── kubernetes.py
│   ├── diagnostics.py
│   └── netguard.py     # SSRF protection for network tools
├── backends/           # LLM backends behind one interface
│   ├── base.py         #   LLMBackend contract (Turn, ToolCall)
│   ├── anthropic_backend.py
│   ├── bedrock_backend.py
│   ├── ollama_backend.py
│   └── registry.py
├── agent.py            # the reason-act loop + report extraction
├── app.py              # FastAPI webhook server
└── cli.py              # `sentinel` entry point
```

The agent speaks only in terms of a tool **catalogue** (name → schema → async handler) and a backend **contract**, so tools and providers evolve independently. Each tool advertises an Anthropic-style schema, which the Bedrock and OpenAI-compatible backends convert to their own formats.

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[anthropic]'      # or '.[bedrock]', or '.[all]'

cp .env.example .env               # set LLM_BACKEND and credentials

sentinel                           # starts the server on http://127.0.0.1:8080
```

Trigger a manual investigation:

```bash
curl -X POST http://127.0.0.1:8080/investigate \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "checkout-service: high 5xx error rate",
    "severity": "high",
    "service": "checkout",
    "description": "Error rate jumped from 0.1% to 15% at 14:32 UTC",
    "labels": {"namespace": "production"}
  }'
```

The response is a structured `IncidentReport` JSON. Interactive API docs live at `/docs`.

### Local model (no API key)

```bash
ollama pull qwen2.5:7b
# .env: LLM_BACKEND=ollama  OLLAMA_MODEL=qwen2.5:7b
sentinel
```

---

## Backends

| `LLM_BACKEND` | Auth | Notes |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | Claude via the Messages API with tool use |
| `bedrock` | `BEDROCK_API_KEY` **or** IAM | Converse API; bearer token or boto3 credential chain |
| `ollama` | none | Any OpenAI-compatible server (Ollama, vLLM, LM Studio, llama.cpp) |

---

## Security model

Because tool arguments originate from an LLM (which an attacker may influence via a crafted alert), the network- and shell-facing tools are locked down:

- **SSRF protection** — `check_http_endpoint` and hostname tools refuse any target that resolves to a private, loopback, link-local, or reserved address, which blocks cloud metadata endpoints (`169.254.169.254`). Non-`http(s)` schemes are rejected and redirects are not followed.
- **No shell exfiltration** — the diagnostic shell whitelist excludes `curl`/`wget` and any file-reading command; only read-only network/host probes are allowed, with metacharacters rejected.
- **kubectl flag-injection guard** — resource names and namespaces that start with `-` or contain unexpected characters are refused, so a model cannot smuggle in flags like `--kubeconfig` or `--as`.
- **Webhook signatures** — PagerDuty/OpsGenie bodies are verified with HMAC-SHA256 when a secret is configured.
- **Loopback by default** — the server binds `127.0.0.1`; expose it only behind a trusted gateway.

---

## Development

```bash
pip install -e '.[all,dev]'
pytest                 # test suite
ruff check src tests   # lint
```

Tests cover the pure-logic core — parsers, signature verification, the SSRF guard, kubectl argument validation, JSON extraction, models, and the agent loop (with a scripted fake backend) — without needing a cluster, LLM credentials, or network access.

## Demo

The `demo/` directory contains scripts and manifests for exercising the agent against a local kind cluster with injected failures. Start the server, then run `python demo/send_alert.py --issue crashloop`.

## License

MIT — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
