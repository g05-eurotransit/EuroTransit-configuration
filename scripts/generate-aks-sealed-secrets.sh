#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_commands kubectl kubeseal openssl

target="$ROOT_DIR/platform/environments/aks/secrets"
parent="$(dirname "$target")"
staging="$(mktemp -d "$parent/.secrets.staging.XXXXXX")"
cert="${SEALED_SECRETS_CERT:-}"
temporary_cert=""
previous=""
cleanup() {
  [[ -z "$temporary_cert" ]] || rm -f "$temporary_cert"
  [[ -z "$staging" ]] || rm -rf "$staging"
  if [[ -n "$previous" && ! -d "$target" ]]; then mv "$previous" "$target"; fi
}
trap cleanup EXIT INT TERM

if [[ -z "$cert" ]]; then
  temporary_cert="$(mktemp)"; cert="$temporary_cert"
  kubeseal --controller-name sealed-secrets-controller --controller-namespace sealed-secrets --fetch-cert > "$cert"
fi
cp "$target/kustomization.yaml" "$staging/kustomization.yaml"

seal() {
  local namespace="$1" name="$2" file="$3"; shift 3
  # Values are function arguments only; kubectl reads the env-file stream on stdin.
  local pair
  { for pair in "$@"; do printf '%s\n' "$pair"; done; } \
    | kubectl -n "$namespace" create secret generic "$name" --from-env-file=/dev/stdin --dry-run=client -o yaml \
    | kubeseal --cert "$cert" --format yaml > "$staging/$file"
}

orders="$(openssl rand -base64 32)"; inventory="$(openssl rand -base64 32)"
payments="$(openssl rand -base64 32)"; keycloak="$(openssl rand -base64 32)"
admin="$(openssl rand -base64 32)"; grafana="$(openssl rand -base64 32)"
client="$(openssl rand -base64 48)"
read -rsp 'Payment provider API key: ' api; echo
[[ -n "$api" ]] || { echo 'Payment provider API key must not be empty' >&2; exit 1; }
seal eurotransit orders-db-credentials orders-db-credentials.sealedsecret.yaml username=orders "password=$orders"
seal eurotransit inventory-db-credentials inventory-db-credentials.sealedsecret.yaml username=inventory "password=$inventory"
seal eurotransit payments-db-credentials payments-db-credentials.sealedsecret.yaml username=payments "password=$payments"
seal eurotransit keycloak-db-credentials keycloak-db-credentials-eurotransit.sealedsecret.yaml username=keycloak "password=$keycloak"
seal keycloak keycloak-db-credentials keycloak-db-credentials-keycloak.sealedsecret.yaml username=keycloak "password=$keycloak"
seal keycloak keycloak-admin-credentials keycloak-admin-credentials.sealedsecret.yaml username=kcadmin "password=$admin"
seal eurotransit orders-service-credentials orders-service-credentials-eurotransit.sealedsecret.yaml "client-secret=$client"
seal keycloak orders-service-credentials orders-service-credentials-keycloak.sealedsecret.yaml "client-secret=$client"
seal eurotransit payments-provider-credentials payments-provider-credentials.sealedsecret.yaml "provider-api-key=$api"
seal monitoring grafana-admin-credentials grafana-admin-credentials.sealedsecret.yaml username=admin "password=$grafana"
unset orders inventory payments keycloak admin grafana client api

"$ROOT_DIR/scripts/validate-aks-sealed-secrets.sh" "$staging"

previous="$parent/.secrets.previous.$$"
mv "$target" "$previous"
mv "$staging" "$target"; staging=""
rm -rf "$previous"; previous=""
git -C "$ROOT_DIR" diff --check
echo "Generated and validated 10 AKS SealedSecrets; review, commit through PR, then merge to main."
