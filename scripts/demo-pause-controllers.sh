#!/usr/bin/env bash
set -euo pipefail

# Temporarily reduce AKS memory use for a short, static EuroTransit demo.
# Kafka, Kafka Connect, Keycloak, Prometheus, Grafana, Argo CD, Traefik and
# application workloads remain running. Only reconciliation controllers pause.
#
# Usage:
#   scripts/demo-pause-controllers.sh pause
#   scripts/demo-pause-controllers.sh resume
#   scripts/demo-pause-controllers.sh status

source "$(dirname "$0")/lib.sh"
require_commands kubectl

STATE_NAMESPACE="argocd"
STATE_CONFIGMAP="eurotransit-demo-controller-pause-state"

# The root app-of-apps owns the child Application manifests. It must be paused
# first, otherwise it restores the child sync policies on its next refresh.
root_app="eurotransit-platform-root"
apps=(keycloak-operator strimzi cert-manager)
deployments=(
  "keycloak/keycloak-operator"
  "strimzi/strimzi-cluster-operator"
  "eurotransit/eurotransit-kafka-entity-operator"
  "cert-manager/cert-manager"
  "cert-manager/cert-manager-cainjector"
  "cert-manager/cert-manager-webhook"
)

usage() {
  echo "Usage: $0 {pause|resume|status}" >&2
  exit 2
}

state_exists() {
  kubectl -n "$STATE_NAMESPACE" get configmap "$STATE_CONFIGMAP" >/dev/null 2>&1
}

require_resources() {
  local app deployment namespace name
  kubectl -n "$STATE_NAMESPACE" get application "$root_app" >/dev/null
  for app in "${apps[@]}"; do
    kubectl -n "$STATE_NAMESPACE" get application "$app" >/dev/null
  done
  for deployment in "${deployments[@]}"; do
    namespace="${deployment%%/*}"
    name="${deployment#*/}"
    kubectl -n "$namespace" get deployment "$name" >/dev/null
  done
}

state_value() {
  local key="$1"
  kubectl -n "$STATE_NAMESPACE" get configmap "$STATE_CONFIGMAP" \
    -o go-template="{{ index .data \"$key\" }}"
}

state_has_key() {
  local key="$1"
  [[ "$(kubectl -n "$STATE_NAMESPACE" get configmap "$STATE_CONFIGMAP" \
    -o go-template="{{ if index .data \"$key\" }}present{{ end }}")" == "present" ]]
}

pause() {
  if state_exists; then
    echo "Controllers are already paused; run '$0 status' or '$0 resume'." >&2
    exit 1
  fi

  require_resources

  local create_args=() app deployment namespace name policy replicas
  policy="$(kubectl -n "$STATE_NAMESPACE" get application "$root_app" -o jsonpath='{.spec.syncPolicy}')"
  create_args+=(--from-literal="app-${root_app}-sync-policy=${policy:-\{\}}")
  for app in "${apps[@]}"; do
    policy="$(kubectl -n "$STATE_NAMESPACE" get application "$app" -o jsonpath='{.spec.syncPolicy}')"
    create_args+=(--from-literal="app-${app}-sync-policy=${policy:-\{\}}")
  done
  for deployment in "${deployments[@]}"; do
    namespace="${deployment%%/*}"
    name="${deployment#*/}"
    replicas="$(kubectl -n "$namespace" get deployment "$name" -o jsonpath='{.spec.replicas}')"
    create_args+=(--from-literal="deployment-${namespace}-${name}-replicas=$replicas")
  done
  kubectl -n "$STATE_NAMESPACE" create configmap "$STATE_CONFIGMAP" \
    --from-literal=purpose="temporary EuroTransit demo controller pause" \
    "${create_args[@]}" >/dev/null

  # Stop the app-of-apps before its children, then stop the child apps. The
  # complete syncPolicy is saved above and restored by resume.
  kubectl -n "$STATE_NAMESPACE" patch application "$root_app" --type json \
    --patch '[{"op":"remove","path":"/spec/syncPolicy/automated"}]' >/dev/null
  for app in "${apps[@]}"; do
    # A merge patch with `automated: null` is accepted by the API but does not
    # reliably remove this nested field. JSON Patch makes auto-sync removal
    # explicit, so Argo cannot immediately scale the controllers back up.
    kubectl -n "$STATE_NAMESPACE" patch application "$app" --type json \
      --patch '[{"op":"remove","path":"/spec/syncPolicy/automated"}]' >/dev/null
  done

  for deployment in "${deployments[@]}"; do
    namespace="${deployment%%/*}"
    name="${deployment#*/}"
    kubectl -n "$namespace" scale deployment "$name" --replicas=0 >/dev/null
  done

  echo "Paused Keycloak, Strimzi, Kafka Entity and cert-manager reconciliation controllers."
  echo "Kafka Connect, Keycloak, Prometheus, Grafana and all marketplace services remain running."
  echo "Run '$0 resume' immediately after the demo."
}

resume() {
  if ! state_exists; then
    echo "No saved controller-pause state exists; nothing to resume." >&2
    exit 1
  fi

  local deployment namespace name replicas app policy
  for deployment in "${deployments[@]}"; do
    namespace="${deployment%%/*}"
    name="${deployment#*/}"
    replicas="$(state_value "deployment-${namespace}-${name}-replicas")"
    kubectl -n "$namespace" scale deployment "$name" --replicas="$replicas" >/dev/null
  done
  for app in "${apps[@]}"; do
    policy="$(state_value "app-${app}-sync-policy")"
    kubectl -n "$STATE_NAMESPACE" patch application "$app" --type merge \
      --patch "{\"spec\":{\"syncPolicy\":${policy}}}" >/dev/null
  done
  # Restore the root last so it only resumes reconciling after every child
  # Application has its original policy again. Older saved states, created
  # before root-app pausing was added, deliberately have no such value.
  if state_has_key "app-${root_app}-sync-policy"; then
    policy="$(state_value "app-${root_app}-sync-policy")"
    kubectl -n "$STATE_NAMESPACE" patch application "$root_app" --type merge \
      --patch "{\"spec\":{\"syncPolicy\":${policy}}}" >/dev/null
  fi

  kubectl -n "$STATE_NAMESPACE" delete configmap "$STATE_CONFIGMAP" >/dev/null
  echo "Restored the saved replica counts and Argo CD sync policies."
}

status() {
  echo "Argo CD applications:"
  kubectl -n "$STATE_NAMESPACE" get application "$root_app" \
    -o jsonpath="${root_app}: sync={.status.sync.status} health={.status.health.status} automated={.spec.syncPolicy.automated}{'\n'}"
  for app in "${apps[@]}"; do
    kubectl -n "$STATE_NAMESPACE" get application "$app" \
      -o jsonpath="${app}: sync={.status.sync.status} health={.status.health.status} automated={.spec.syncPolicy.automated}{'\n'}"
  done
  echo
  echo "Controller deployments:"
  for deployment in "${deployments[@]}"; do
    namespace="${deployment%%/*}"
    name="${deployment#*/}"
    kubectl -n "$namespace" get deployment "$name" \
      -o jsonpath="${namespace}/${name}: desired={.spec.replicas} ready={.status.readyReplicas}{'\n'}"
  done
  if state_exists; then
    echo
    echo "Pause state is saved in ${STATE_NAMESPACE}/${STATE_CONFIGMAP}. Run '$0 resume' to restore it."
  fi
}

case "${1:-}" in
  pause) pause ;;
  resume) resume ;;
  status) status ;;
  *) usage ;;
esac
