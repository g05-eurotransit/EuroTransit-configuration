#!/usr/bin/env bash
set -euo pipefail

command -v kubectl >/dev/null || { echo 'missing kubectl' >&2; exit 2; }
command -v rg >/dev/null || { echo 'missing rg' >&2; exit 2; }

usage() {
  echo 'usage: validate-aks-sealed-secrets.sh [--scaffold] <directory>' >&2
  exit 2
}

scaffold=0
case "${1:-}" in
  --scaffold) scaffold=1; shift ;;
esac
[[ $# -eq 1 && -d "$1" ]] || usage
dir="$1"

# This is the single authoritative AKS runtime-secret inventory.  The Git
# bootstrap repository credential is deliberately not part of it.
inventory=$'catalog-db-credentials.sealedsecret.yaml|eurotransit|catalog-db-credentials\norders-db-credentials.sealedsecret.yaml|eurotransit|orders-db-credentials\ninventory-db-credentials.sealedsecret.yaml|eurotransit|inventory-db-credentials\npayments-db-credentials.sealedsecret.yaml|eurotransit|payments-db-credentials\nkeycloak-db-credentials-eurotransit.sealedsecret.yaml|eurotransit|keycloak-db-credentials\nkeycloak-db-credentials-keycloak.sealedsecret.yaml|keycloak|keycloak-db-credentials\nkeycloak-admin-credentials.sealedsecret.yaml|keycloak|keycloak-admin-credentials\nkeycloak-demo-users-credentials.sealedsecret.yaml|keycloak|keycloak-demo-users-credentials\norders-service-credentials-eurotransit.sealedsecret.yaml|eurotransit|orders-service-credentials\norders-service-credentials-keycloak.sealedsecret.yaml|keycloak|orders-service-credentials\neurotransit-load-test-credentials-eurotransit.sealedsecret.yaml|eurotransit|eurotransit-load-test-credentials\neurotransit-load-test-credentials-keycloak.sealedsecret.yaml|keycloak|eurotransit-load-test-credentials\npayments-provider-credentials.sealedsecret.yaml|eurotransit|payments-provider-credentials\ngrafana-admin-credentials.sealedsecret.yaml|monitoring|grafana-admin-credentials'

expected_files="$(printf '%s\n' "$inventory" | cut -d'|' -f1 | sort)"
expected_pairs="$(printf '%s\n' "$inventory" | awk -F'|' '{print $2 "/" $3}' | sort)"

resources_from_kustomization() {
  awk '
    /^resources:[[:space:]]*$/ { in_resources = 1; next }
    in_resources && /^[^[:space:]#]/ { in_resources = 0 }
    in_resources && /^  - / { sub(/^  - /, ""); sub(/[[:space:]]+#.*/, ""); print }
  ' "$dir/kustomization.yaml" | sort
}

check_resources() {
  [[ -f "$dir/kustomization.yaml" ]] || { echo "missing $dir/kustomization.yaml" >&2; return 1; }
  local actual
  actual="$(resources_from_kustomization)"
  if [[ "$actual" != "$expected_files" ]]; then
    echo "AKS secrets kustomization resources must exactly match the required 14-file inventory" >&2
    echo "expected:" >&2; printf '%s\n' "$expected_files" >&2
    echo "found:" >&2; printf '%s\n' "$actual" >&2
    return 1
  fi
}

check_files() {
  local actual
  actual="$(find "$dir" -maxdepth 1 -type f -name '*.sealedsecret.yaml' -printf '%f\n' | sort)"
  if [[ "$actual" != "$expected_files" ]]; then
    echo "AKS ciphertext files must exactly match the required 14-file inventory" >&2
    echo "expected:" >&2; printf '%s\n' "$expected_files" >&2
    echo "found:" >&2; printf '%s\n' "$actual" >&2
    return 1
  fi
}

if [[ "$scaffold" -eq 1 ]]; then
  actual_count="$(find "$dir" -maxdepth 1 -type f -name '*.sealedsecret.yaml' -printf . | wc -c)"
  [[ "$actual_count" -eq 0 ]] || { echo "--scaffold requires zero ciphertext files; found $actual_count" >&2; exit 1; }
  check_resources

  temp_dir="$(mktemp -d)"
  cleanup() { rm -rf "$temp_dir"; }
  trap cleanup EXIT INT TERM
  cp "$dir/kustomization.yaml" "$temp_dir/kustomization.yaml"
  while IFS='|' read -r filename namespace name; do
    cat >"$temp_dir/$filename" <<EOF
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: $name
  namespace: $namespace
spec:
  encryptedData:
    validation: Ag==
EOF
  done <<<"$inventory"
  if ! kubectl kustomize "$temp_dir" >/dev/null; then
    echo 'AKS secrets kustomization is not syntactically valid with the required scaffold files' >&2
    exit 1
  fi
  echo 'AKS SealedSecret scaffold is valid'
  exit 0
fi

check_files
check_resources
if rg -n 'REPLACE_WITH_KUBESEAL_OUTPUT|eurotransit-configuration-repo|^kind:[[:space:]]+Secret$|^[[:space:]]*stringData:' "$dir"/*.sealedsecret.yaml; then
  echo 'AKS ciphertext inventory contains a plaintext placeholder, Secret, or Git bootstrap credential' >&2
  exit 1
fi

render="$(kubectl kustomize "$dir")"
actual_pairs="$(printf '%s\n' "$render" | awk '
  /^kind: / { kind=$2; meta=0; name=""; ns="" }
  /^metadata:/ { meta=1; next }
  meta && /^  name: / { name=$2 }
  meta && /^  namespace: / { ns=$2 }
  /^---$/ { if (kind != "SealedSecret") bad=1; else print ns "/" name; kind=""; meta=0 }
  END { if (kind != "") { if (kind != "SealedSecret") bad=1; else print ns "/" name } exit bad }
' | sort)" || { echo 'AKS secrets render contains a resource other than SealedSecret' >&2; exit 1; }
if [[ "$actual_pairs" != "$expected_pairs" ]]; then
  echo 'Rendered SealedSecret namespace/name pairs differ from the required inventory' >&2
  echo "expected:" >&2; printf '%s\n' "$expected_pairs" >&2
  echo "found:" >&2; printf '%s\n' "$actual_pairs" >&2
  exit 1
fi

echo 'AKS SealedSecret ciphertext inventory is valid'
