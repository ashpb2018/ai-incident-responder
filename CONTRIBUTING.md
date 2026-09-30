# Contributing to Sentinel

Thanks for your interest in improving Sentinel.

## Development setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[all,dev]'
```

## Before opening a pull request

- Run the linter: `ruff check src tests`
- Run the tests: `pytest`
- Add tests for new behaviour, and keep changes focused.

## Project layout

The core lives under `src/incident_sentinel/`:

- `ingest/` — webhook parsing and signature verification
- `tools/` — the investigation tools the agent can call
- `backends/` — LLM backends behind one interface
- `agent.py` — the reason-act loop and report extraction
- `app.py` — the FastAPI webhook server

## Security

Tool arguments come from an LLM, so network- and shell-facing tools are
deliberately restrictive (SSRF guard, kubectl flag-injection guard, no shell
exfiltration). Please preserve these guarantees in any change and add tests
that cover new tool surfaces.

## Maintainer

Maintained by [@ashpb2018](https://github.com/ashpb2018).
