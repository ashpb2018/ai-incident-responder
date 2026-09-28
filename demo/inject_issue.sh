#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# inject_issue.sh — Inject realistic Kubernetes failures for demo purposes
#
# Usage:
#   ./demo/inject_issue.sh <issue_type> [--service <name>] [--namespace <ns>]
#
# Issue types:
#   crashloop    CrashLoopBackOff: container exits immediately with fatal error
#   oom          OOMKill: container exceeds tiny memory limit
#   imagefail    ImagePullBackOff: non-existent container image
#   scale0       Service with 0 ready replicas (silent outage)
#   pending      Pod stuck in Pending: impossible resource requests
#   restore      Restore affected service to healthy state
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ISSUE="${1:-}"
SERVICE="checkout"
NAMESPACE="demo"

# Parse flags
while [[ $# -gt 1 ]]; do
  case "$2" in
    --service)   SERVICE="$3";    shift 2 ;;
    --namespace) NAMESPACE="$3";  shift 2 ;;
    *) shift ;;
  esac
done

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERR]${RESET}   $*" >&2; exit 1; }
header()  { echo -e "\n${BOLD}${CYAN}▶ $*${RESET}"; }

wait_for_bad_state() {
  local label="$1"
  local max=60
  info "Waiting up to ${max}s for issue to manifest..."
  for i in $(seq 1 $max); do
    local phase
    phase=$(kubectl get pods -n "$NAMESPACE" -l "app=$label" \
            -o jsonpath='{.items[*].status.phase}' 2>/dev/null || true)
    local waiting_reason
    waiting_reason=$(kubectl get pods -n "$NAMESPACE" -l "app=$label" \
            -o jsonpath='{.items[*].status.containerStatuses[*].state.waiting.reason}' 2>/dev/null || true)

    if [[ "$waiting_reason" == *"CrashLoopBackOff"* ]] || \
       [[ "$waiting_reason" == *"OOMKill"* ]] || \
       [[ "$waiting_reason" == *"ErrImagePull"* ]] || \
       [[ "$waiting_reason" == *"ImagePullBackOff"* ]] || \
       [[ "$phase" == *"Pending"* ]]; then
      success "Issue is visible in pod status (${waiting_reason:-$phase})"
      return 0
    fi
    printf "."
    sleep 1
  done
  echo ""
  warn "Issue may still be propagating — proceeding anyway"
}

case "$ISSUE" in

  # ── CrashLoopBackOff ───────────────────────────────────────────────────────
  crashloop)
    header "Injecting: CrashLoopBackOff into ${SERVICE} (${NAMESPACE})"
    info "Patching deployment to use a container that exits with a fatal DB error..."
    kubectl patch deployment "$SERVICE" -n "$NAMESPACE" --patch '{
      "spec": {
        "template": {
          "spec": {
            "containers": [{
              "name": "'"$SERVICE"'",
              "image": "busybox:1.36",
              "command": ["/bin/sh", "-c"],
              "args": ["echo \"[FATAL] $(date -u +%Y-%m-%dT%H:%M:%SZ) payments-db:5432 - Connection refused (ECONNREFUSED)\"; echo \"[ERROR] Database pool exhausted after 30 retries\"; echo \"[ERROR] Cannot start service without database connection\"; exit 1"],
              "resources": {"limits": {"memory": "64Mi", "cpu": "100m"}}
            }]
          }
        }
      }
    }' >/dev/null
    wait_for_bad_state "$SERVICE"
    success "CrashLoopBackOff active on ${SERVICE}. Pods are exiting with DB connection errors."
    echo ""
    echo -e "  ${YELLOW}Suggested alert payload:${RESET}"
    echo '  { "title": "'"$SERVICE"'-service: pods in CrashLoopBackOff", "severity": "high",'
    echo '    "service": "'"$SERVICE"'", "description": "3/3 pods restarting. Error rate 100%.",'
    echo '    "labels": {"namespace": "'"$NAMESPACE"'", "env": "production"} }'
    ;;

  # ── OOMKill ────────────────────────────────────────────────────────────────
  oom)
    header "Injecting: OOMKill into ${SERVICE} (${NAMESPACE})"
    info "Patching deployment with 32Mi memory limit and a memory-hungry process..."
    kubectl patch deployment "$SERVICE" -n "$NAMESPACE" --patch '{
      "spec": {
        "template": {
          "spec": {
            "containers": [{
              "name": "'"$SERVICE"'",
              "image": "python:3.11-slim",
              "command": ["python3", "-c"],
              "args": ["import time; buf=[]; print(\"Allocating memory...\"); [buf.append(b\"x\" * 1024 * 1024) or time.sleep(0.05) for _ in range(1000)]"],
              "resources": {
                "requests": {"memory": "16Mi"},
                "limits":   {"memory": "32Mi", "cpu": "100m"}
              }
            }]
          }
        }
      }
    }' >/dev/null
    wait_for_bad_state "$SERVICE"
    success "OOMKill active on ${SERVICE}. Containers are being killed by the kernel."
    echo ""
    echo -e "  ${YELLOW}Suggested alert payload:${RESET}"
    echo '  { "title": "'"$SERVICE"'-service: OOMKilled pods detected", "severity": "critical",'
    echo '    "service": "'"$SERVICE"'", "description": "Pods being OOMKilled. Memory limit: 32Mi.",'
    echo '    "labels": {"namespace": "'"$NAMESPACE"'", "env": "production"} }'
    ;;

  # ── ImagePullBackOff ───────────────────────────────────────────────────────
  imagefail)
    header "Injecting: ImagePullBackOff into ${SERVICE} (${NAMESPACE})"
    info "Patching deployment with a non-existent image tag..."
    kubectl patch deployment "$SERVICE" -n "$NAMESPACE" --patch '{
      "spec": {
        "template": {
          "spec": {
            "containers": [{
              "name": "'"$SERVICE"'",
              "image": "mycompany/'"$SERVICE"'-service:v3.1.4-hotfix-NONEXISTENT"
            }]
          }
        }
      }
    }' >/dev/null
    wait_for_bad_state "$SERVICE"
    success "ImagePullBackOff active on ${SERVICE}. New pods cannot start."
    echo ""
    echo -e "  ${YELLOW}Suggested alert payload:${RESET}"
    echo '  { "title": "'"$SERVICE"'-service: image pull failure after deploy", "severity": "high",'
    echo '    "service": "'"$SERVICE"'", "description": "Rollout stuck. New pods cannot pull image.",'
    echo '    "labels": {"namespace": "'"$NAMESPACE"'", "env": "production", "team": "platform"} }'
    ;;

  # ── Scale to zero (silent outage) ─────────────────────────────────────────
  scale0)
    header "Injecting: Scale-to-zero on ${SERVICE} (${NAMESPACE})"
    info "Scaling deployment to 0 replicas..."
    kubectl scale deployment "$SERVICE" -n "$NAMESPACE" --replicas=0 >/dev/null
    sleep 3
    READY=$(kubectl get deployment "$SERVICE" -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    success "Scaled ${SERVICE} to 0 replicas. Ready: ${READY:-0}"
    echo ""
    echo -e "  ${YELLOW}Suggested alert payload:${RESET}"
    echo '  { "title": "'"$SERVICE"'-service: 0 pods available (possible accidental scale-down)", "severity": "critical",'
    echo '    "service": "'"$SERVICE"'", "description": "All replicas gone. 100% error rate.",'
    echo '    "labels": {"namespace": "'"$NAMESPACE"'", "env": "production"} }'
    ;;

  # ── Pending (unschedulable) ───────────────────────────────────────────────
  pending)
    header "Injecting: Unschedulable pod into ${NAMESPACE}"
    info "Creating a pod requesting 500Gi memory (impossible on this cluster)..."
    kubectl apply -n "$NAMESPACE" -f - >/dev/null <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: checkout-canary-unschedulable
  namespace: demo
  labels:
    app: checkout
    issue: pending-demo
spec:
  containers:
  - name: checkout
    image: nginx:alpine
    resources:
      requests:
        memory: "500Gi"
        cpu: "100"
EOF
    sleep 3
    success "Unschedulable pod created. It will be stuck in Pending indefinitely."
    echo ""
    echo -e "  ${YELLOW}Suggested alert payload:${RESET}"
    echo '  { "title": "checkout-service: pods stuck in Pending state", "severity": "high",'
    echo '    "service": "checkout", "description": "New pods cannot be scheduled. Cluster capacity issue?",'
    echo '    "labels": {"namespace": "'"$NAMESPACE"'", "env": "production"} }'
    ;;

  # ── Restore ───────────────────────────────────────────────────────────────
  restore)
    header "Restoring ${SERVICE} (${NAMESPACE}) to healthy state"
    info "Re-applying original apps manifest..."
    kubectl apply -f "$(dirname "$0")/manifests/apps.yaml" >/dev/null
    # Remove any injected unschedulable pods
    kubectl delete pod checkout-canary-unschedulable -n "$NAMESPACE" --ignore-not-found >/dev/null
    info "Waiting for rollout to complete..."
    kubectl rollout status deployment/"$SERVICE" -n "$NAMESPACE" --timeout=120s
    success "${SERVICE} restored and healthy."
    ;;

  *)
    echo -e "${BOLD}Usage:${RESET} $0 <issue_type> [--service NAME] [--namespace NS]"
    echo ""
    echo -e "${BOLD}Issue types:${RESET}"
    echo "  crashloop   Pods crash immediately with database connection error"
    echo "  oom         Pods are OOMKilled (memory limit too low)"
    echo "  imagefail   Pods stuck in ImagePullBackOff (bad image tag)"
    echo "  scale0      Service scaled to 0 replicas (silent outage)"
    echo "  pending     Pod stuck in Pending (impossible resource requests)"
    echo "  restore     Restore service to its original healthy state"
    echo ""
    echo -e "${BOLD}Examples:${RESET}"
    echo "  $0 crashloop"
    echo "  $0 oom --service payments"
    echo "  $0 restore --service checkout"
    exit 1
    ;;
esac
