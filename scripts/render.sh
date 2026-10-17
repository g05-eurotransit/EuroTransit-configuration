#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

environment="${1:-}"
case "$environment" in
  kind|kind-ha|aks) ;;
  *) echo "Usage: $0 kind|kind-ha|aks" >&2; exit 2 ;;
esac

require_commands helm kubectl rg
values_file="$ROOT_DIR/charts/eurotransit/values-${environment/aks/production}.yaml"
helm_render="$(mktemp)"
kustomize_render="$(mktemp)"
trap 'rm -f "$helm_render" "$kustomize_render"' EXIT

helm template eurotransit "$ROOT_DIR/charts/eurotransit" \
  -f "$ROOT_DIR/charts/eurotransit/values.yaml" \
  -f "$values_file" >"$helm_render"
kubectl kustomize "$ROOT_DIR/platform/environments/$environment" >"$kustomize_render"
if [[ "$environment" == "aks" ]]; then
  secrets_dir="$ROOT_DIR/platform/environments/aks/secrets"
  actual_secret_files="$(find "$secrets_dir" -maxdepth 1 -type f -name '*.sealedsecret.yaml' -printf . | wc -c)"
  if [[ "$actual_secret_files" -eq 0 && "${ALLOW_MISSING_AKS_SECRETS:-0}" == "1" ]]; then
    "$ROOT_DIR/scripts/validate-aks-sealed-secrets.sh" --scaffold "$secrets_dir"
    echo "AKS runtime secrets ciphertext is intentionally absent; scaffold validated" >&2
  elif [[ "$actual_secret_files" -eq 0 ]]; then
    echo "AKS production rendering is blocked until cluster-specific SealedSecret ciphertext is generated; run scripts/generate-aks-sealed-secrets.sh." >&2
    exit 1
  else
    "$ROOT_DIR/scripts/validate-aks-sealed-secrets.sh" "$secrets_dir"
  fi
fi
kubectl kustomize "$ROOT_DIR/platform/connectors/environments/$environment" >/dev/null

if [[ "$environment" == kind* ]]; then
  keycloak_profile=keycloak-kind
  if [[ "$environment" == kind-ha ]]; then keycloak_profile=keycloak-kind-ha; fi
  kubectl kustomize "$ROOT_DIR/platform/environments/$keycloak_profile" >/dev/null
  kubectl kustomize "$ROOT_DIR/platform/argocd/environments/kind" >/dev/null
  kubectl kustomize "$ROOT_DIR/apps/argocd-apps/environments/kind" >/dev/null
else
  kubectl kustomize "$ROOT_DIR/platform/keycloak" >/dev/null
  kubectl kustomize "$ROOT_DIR/platform/argocd/environments/aks" >/dev/null
  kubectl kustomize "$ROOT_DIR/apps/argocd-apps/environments/aks" >/dev/null
fi

if rg -n 'eurotransit\.example\.com|resources: \{\}' "$values_file" "$ROOT_DIR/platform/environments/$environment"; then
  echo "Placeholder or empty resources found in $environment profile" >&2
  exit 1
fi

if rg -n 'REPLACE_WITH_KUBESEAL_OUTPUT' "$kustomize_render"; then
  echo "A SealedSecret placeholder would be applied by the $environment overlay" >&2
  exit 1
fi

if [[ "$environment" == "aks" ]]; then
  # The sole AKS Kafka broker is represented by one broker-role KafkaNodePool.
  broker_count="$(awk '
    $0 == "kind: KafkaNodePool" { nodepool = 1; broker = 0 }
    nodepool && $0 ~ /^  replicas: / { replicas = $2 }
    nodepool && $0 ~ /- broker/ { broker = 1 }
    /^---$/ { if (nodepool && broker) total += replicas; nodepool = broker = 0 }
    END { if (nodepool && broker) total += replicas; print total + 0 }
  ' "$kustomize_render")"
  if [[ "$broker_count" -lt 1 ]]; then
    echo "AKS render contains no Kafka broker nodes" >&2
    exit 1
  fi
  if ! awk -v brokers="$broker_count" '
    $0 == "kind: KafkaTopic" { topic = 1; name = "" }
    topic && $0 ~ /^  name: / { name = $2 }
    topic && $0 ~ /^  replicas: / && $2 > brokers {
      printf "KafkaTopic %s has replicas %s but only %s broker(s) render for AKS\\n", name, $2, brokers > "/dev/stderr"; failed = 1
    }
    /^---$/ { topic = 0 }
    END { exit failed }
  ' "$kustomize_render"; then
    exit 1
  fi
  if rg -n '^kind: PodDisruptionBudget$' "$helm_render"; then
    echo "AKS renders application PDBs although its application replicas are single-instance" >&2
    exit 1
  fi
  frontend_block="$(awk '
    $0 == "kind: Deployment" { deployment = 1; frontend = 0 }
    deployment && $0 == "  name: frontend" { frontend = 1 }
    deployment && frontend { print }
    /^---$/ && deployment { deployment = 0 }
  ' "$helm_render")"
  if ! printf '%s\n' "$frontend_block" | rg -q '^  replicas: 1$' \
    || ! printf '%s\n' "$frontend_block" | rg -q '^            requests:$' \
    || ! printf '%s\n' "$frontend_block" | rg -q '^            limits:$'; then
    echo "AKS frontend must render one replica with non-empty resource requests and limits" >&2
    exit 1
  fi
fi

echo "$environment manifests render successfully"
