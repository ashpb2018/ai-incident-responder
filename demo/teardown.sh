#!/usr/bin/env bash
# Tear down the demo environment completely
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[teardown]${RESET}  $*"; }
success() { echo -e "${GREEN}[teardown]${RESET}  $*"; }

info "Deleting kind cluster: incident-demo"
kind delete cluster --name incident-demo 2>/dev/null && success "Cluster deleted" || info "Cluster not found"

info "Killing any running agent server on :8080"
lsof -ti:8080 | xargs kill -9 2>/dev/null || true

info "Removing generated report files"
find "$(dirname "$0")/.." -name "report_*.json" -delete 2>/dev/null || true

success "Teardown complete. Run ./demo/setup.sh to start fresh."
