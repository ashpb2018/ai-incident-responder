#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# setup.sh — One-command demo environment setup
#
# What this does:
#   1. Checks prerequisites (kind, kubectl, docker, ollama, python3)
#   2. Creates a kind cluster with port-forwarding for Prometheus
#   3. Deploys sample apps (checkout, payments, redis) in the demo namespace
#   4. Deploys kube-state-metrics + Prometheus in the monitoring namespace
#   5. Pulls the Ollama model (llama3.1:8b by default)
#   6. Creates a .env file configured for local use
#   7. Creates a Python virtualenv and installs dependencies
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[ OK ]${RESET}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ ERR]${RESET}  $*" >&2; exit 1; }
step()    { echo -e "\n${BOLD}${CYAN}━━ $* ━━${RESET}"; }

OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.1:8b}"
CLUSTER_NAME="incident-demo"

# ── 1. Prerequisites ──────────────────────────────────────────────────────────
step "Checking prerequisites"

check_cmd() {
  if ! command -v "$1" &>/dev/null; then
    error "'$1' not found. Install it and re-run setup.\n       $2"
  fi
  success "$1 found: $(command -v "$1")"
}

check_cmd docker    "https://docs.docker.com/get-docker/"
check_cmd kind      "brew install kind  OR  https://kind.sigs.k8s.io/docs/user/quick-start/"
check_cmd kubectl   "brew install kubectl  OR  https://kubernetes.io/docs/tasks/tools/"
check_cmd python3   "brew install python3"

if ! command -v ollama &>/dev/null; then
  warn "ollama not found. Install from https://ollama.com — then re-run this script."
  warn "Alternatively, set LLM_BACKEND=anthropic in .env and provide ANTHROPIC_API_KEY."
  SKIP_OLLAMA=true
else
  success "ollama found: $(command -v ollama)"
  SKIP_OLLAMA=false
fi

# Check Docker is running
if ! docker info &>/dev/null; then
  error "Docker is not running. Start Docker Desktop and re-run."
fi
success "Docker daemon is running"

# ── 2. kind cluster ───────────────────────────────────────────────────────────
step "Creating kind cluster: ${CLUSTER_NAME}"

if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  warn "Cluster '${CLUSTER_NAME}' already exists — skipping creation"
else
  info "Creating cluster (this takes ~30 seconds)..."
  kind create cluster --config "$SCRIPT_DIR/kind_cluster.yaml" --wait 60s
  success "Cluster created"
fi

info "Setting kubectl context..."
kubectl cluster-info --context "kind-${CLUSTER_NAME}" &>/dev/null || \
  kind export kubeconfig --name "$CLUSTER_NAME"
kubectl config use-context "kind-${CLUSTER_NAME}" &>/dev/null || true
success "kubectl context: kind-${CLUSTER_NAME}"

# ── 3. Deploy namespaces ──────────────────────────────────────────────────────
step "Deploying namespaces"
kubectl apply -f "$SCRIPT_DIR/manifests/namespace.yaml"
success "Namespaces: demo, monitoring"

# ── 4. Deploy sample apps ─────────────────────────────────────────────────────
step "Deploying sample apps (checkout, payments, redis)"
kubectl apply -f "$SCRIPT_DIR/manifests/apps.yaml"

info "Waiting for apps to be ready (up to 90s)..."
kubectl wait deployment/checkout  -n demo --for=condition=Available --timeout=90s
kubectl wait deployment/payments  -n demo --for=condition=Available --timeout=90s
kubectl wait deployment/redis     -n demo --for=condition=Available --timeout=90s
success "Apps running in namespace 'demo'"

# ── 5. Deploy monitoring ──────────────────────────────────────────────────────
step "Deploying kube-state-metrics + Prometheus"
kubectl apply -f "$SCRIPT_DIR/manifests/monitoring/kube-state-metrics.yaml"
kubectl apply -f "$SCRIPT_DIR/manifests/monitoring/prometheus.yaml"

info "Waiting for Prometheus to be ready (up to 120s)..."
kubectl wait deployment/kube-state-metrics -n monitoring --for=condition=Available --timeout=120s
kubectl wait deployment/prometheus         -n monitoring --for=condition=Available --timeout=120s
success "Prometheus available at http://localhost:9090"

# ── 6. Ollama model ───────────────────────────────────────────────────────────
if [[ "$SKIP_OLLAMA" == "false" ]]; then
  step "Ensuring Ollama model: ${OLLAMA_MODEL}"
  if ollama list 2>/dev/null | grep -q "${OLLAMA_MODEL%%:*}"; then
    success "Model '${OLLAMA_MODEL}' already downloaded"
  else
    info "Pulling model '${OLLAMA_MODEL}' (may take several minutes)..."
    ollama pull "$OLLAMA_MODEL"
    success "Model '${OLLAMA_MODEL}' ready"
  fi

  # Make sure Ollama server is running
  if ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
    warn "Ollama server not responding at localhost:11434."
    warn "Start it with:  ollama serve"
  else
    success "Ollama server is running at http://localhost:11434"
  fi
fi

# ── 7. Python environment ─────────────────────────────────────────────────────
step "Setting up Python environment"
cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  info "Creating virtualenv..."
  python3 -m venv .venv
fi

info "Installing dependencies..."
source .venv/bin/activate
pip install -q -r requirements.txt
success "Python virtualenv ready: .venv/"

# ── 8. .env file ──────────────────────────────────────────────────────────────
step "Writing .env configuration"

if [[ -f ".env" ]] && grep -q "^LLM_BACKEND=" ".env"; then
  warn ".env already exists — not overwriting. Edit it manually if needed."
else
  cat > ".env" <<EOF
# Generated by demo/setup.sh — edit as needed

# ── LLM Backend ───────────────────────────────────────────────────────────────
$([ "$SKIP_OLLAMA" == "true" ] && echo "LLM_BACKEND=anthropic" || echo "LLM_BACKEND=ollama")

# ── Anthropic (set this if LLM_BACKEND=anthropic) ─────────────────────────────
ANTHROPIC_API_KEY=

# ── Ollama (local, free) ──────────────────────────────────────────────────────
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=${OLLAMA_MODEL}

# ── Prometheus (kind cluster) ─────────────────────────────────────────────────
PROMETHEUS_URL=http://localhost:9090

# ── Kubernetes ────────────────────────────────────────────────────────────────
KUBECONFIG=${HOME}/.kube/config

# ── Datadog (leave blank — not needed for this demo) ─────────────────────────
DATADOG_API_KEY=
DATADOG_APP_KEY=

# ── Server ────────────────────────────────────────────────────────────────────
HOST=0.0.0.0
PORT=8080
EOF
  success ".env created"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}${GREEN}  Setup complete!${RESET}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  ${BOLD}Prometheus:${RESET}   http://localhost:9090"
echo -e "  ${BOLD}App (checkout):${RESET} http://localhost:8888"
echo ""
echo -e "  ${BOLD}Next steps:${RESET}"
echo -e "    1. Run the full demo:     ${CYAN}./demo/run_demo.sh crashloop${RESET}"
echo -e "    2. Or step by step:"
echo -e "       a) Start server:       ${CYAN}source .venv/bin/activate && python main.py${RESET}"
echo -e "       b) Inject an issue:    ${CYAN}./demo/inject_issue.sh crashloop${RESET}"
echo -e "       c) Send the alert:     ${CYAN}python demo/send_alert.py --issue crashloop${RESET}"
echo ""
