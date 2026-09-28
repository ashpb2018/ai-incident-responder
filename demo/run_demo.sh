#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# run_demo.sh — Full end-to-end demo: inject issue → investigate → show report
#
# Usage:
#   ./demo/run_demo.sh [issue_type] [--service NAME]
#
#   issue_type: crashloop (default), oom, imagefail, scale0, pending
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

ISSUE="${1:-crashloop}"
SERVICE="checkout"
while [[ $# -gt 1 ]]; do
  case "$2" in
    --service) SERVICE="$3"; shift 2 ;;
    *) shift ;;
  esac
done

BOLD='\033[1m'; CYAN='\033[0;36m'; GREEN='\033[0;32m'
YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[demo]${RESET}  $*"; }
success() { echo -e "${GREEN}[demo]${RESET}  $*"; }
warn()    { echo -e "${YELLOW}[demo]${RESET}  $*"; }
error()   { echo -e "${RED}[demo]${RESET}  $*" >&2; exit 1; }
header()  { echo -e "\n${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"; echo -e "${BOLD}${CYAN}  $*${RESET}"; echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"; }

AGENT_PID=""
cleanup() {
  if [[ -n "$AGENT_PID" ]]; then
    info "Stopping agent server (PID $AGENT_PID)..."
    kill "$AGENT_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

cd "$ROOT_DIR"

# ── 0. Pre-flight checks ──────────────────────────────────────────────────────
header "AI Incident Response — Demo: ${ISSUE}"

if [[ ! -f ".venv/bin/activate" ]]; then
  error "Python venv not found. Run ./demo/setup.sh first."
fi
source .venv/bin/activate

if [[ ! -f ".env" ]]; then
  error ".env not found. Run ./demo/setup.sh first."
fi
export $(grep -v '^#' .env | grep -v '^$' | xargs)

# Check kind cluster
if ! kubectl cluster-info --context "kind-incident-demo" &>/dev/null 2>&1; then
  error "kind cluster 'incident-demo' not running. Run ./demo/setup.sh first."
fi
success "Kind cluster: running"

# Check Prometheus
if curl -sf "http://localhost:9090/-/ready" &>/dev/null; then
  success "Prometheus: http://localhost:9090"
else
  warn "Prometheus not responding on :9090 — metrics queries will gracefully fail"
fi

# Check Ollama (if configured)
LLM_BACKEND="${LLM_BACKEND:-anthropic}"
if [[ "$LLM_BACKEND" == "ollama" ]]; then
  if ! curl -sf "http://localhost:11434/api/tags" &>/dev/null; then
    error "Ollama not running. Start it with: ollama serve"
  fi
  OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.1:8b}"
  success "Ollama: running  model=${OLLAMA_MODEL}"
else
  if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    error "ANTHROPIC_API_KEY not set in .env"
  fi
  success "Anthropic backend configured"
fi

# ── 1. Restore service to clean state ────────────────────────────────────────
info "Restoring ${SERVICE} to healthy baseline..."
"$SCRIPT_DIR/inject_issue.sh" restore --service "$SERVICE" 2>/dev/null || true
sleep 3

# ── 2. Start the agent server ─────────────────────────────────────────────────
header "Starting Agent Server"
info "Starting main.py on :8080..."
python main.py > /tmp/incident-agent.log 2>&1 &
AGENT_PID=$!

# Wait until healthy
for i in $(seq 1 30); do
  if curl -sf "http://localhost:8080/health" &>/dev/null; then
    success "Agent server ready (PID ${AGENT_PID})"
    break
  fi
  if ! kill -0 "$AGENT_PID" 2>/dev/null; then
    error "Agent server crashed. Logs:\n$(tail -20 /tmp/incident-agent.log)"
  fi
  printf "."
  sleep 1
done
echo ""

# ── 3. Inject the issue ───────────────────────────────────────────────────────
header "Injecting Issue: ${ISSUE} → ${SERVICE}"
"$SCRIPT_DIR/inject_issue.sh" "$ISSUE" --service "$SERVICE"

# Extra settle time so K8s events and pod states are fully written
info "Letting the issue settle for 10 seconds..."
sleep 10

# Show current pod status for context
echo ""
info "Current pod state in namespace 'demo':"
kubectl get pods -n demo -o wide 2>/dev/null || true
echo ""

# ── 4. Send alert and investigate ─────────────────────────────────────────────
header "Triggering Investigation"
info "Backend: ${LLM_BACKEND}  |  Issue: ${ISSUE}  |  Service: ${SERVICE}"
echo ""

python demo/send_alert.py --issue "$ISSUE" --service "$SERVICE" --url "http://localhost:8080"

# ── 5. Show agent logs (last 20 lines) ───────────────────────────────────────
echo ""
info "Agent server log tail:"
tail -20 /tmp/incident-agent.log | grep -v "^$" | head -20 || true

# ── 6. Restore ────────────────────────────────────────────────────────────────
echo ""
read -rp "$(echo -e "${YELLOW}Restore ${SERVICE} to healthy state? [Y/n]${RESET} ")" yn
case "${yn:-Y}" in
  [Yy]*|"")
    "$SCRIPT_DIR/inject_issue.sh" restore --service "$SERVICE"
    ;;
  *)
    info "Leaving ${SERVICE} in broken state. Run './demo/inject_issue.sh restore' when done."
    ;;
esac
