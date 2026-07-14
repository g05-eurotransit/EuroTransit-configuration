#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

environment="${1:-}"
case "$environment" in
  kind|aks) ;;
  *) echo "Usage: $0 kind|aks" >&2; exit 2 ;;
esac

require_commands helm kubectl rg
values_file="$ROOT_DIR/charts/eurotransit/values-${environment/aks/production}.yaml"

helm template eurotransit "$ROOT_DIR/charts/eurotransit" \
  -f "$ROOT_DIR/charts/eurotransit/values.yaml" \
  -f "$values_file" >/dev/null
kubectl kustomize "$ROOT_DIR/platform/environments/$environment" >/dev/null

if [[ "$environment" == "kind" ]]; then
  kubectl kustomize "$ROOT_DIR/platform/environments/keycloak-kind" >/dev/null
else
  kubectl kustomize "$ROOT_DIR/platform/keycloak" >/dev/null
fi

if rg -n 'eurotransit\.example\.com|resources: \{\}' "$values_file" "$ROOT_DIR/platform/environments/$environment"; then
  echo "Placeholder or empty resources found in $environment profile" >&2
  exit 1
fi

echo "$environment manifests render successfully"
