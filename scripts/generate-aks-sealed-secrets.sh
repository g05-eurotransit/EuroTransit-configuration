#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_commands kubectl kubeseal openssl

dotenv="$ROOT_DIR/../.env"
if [[ -f "$dotenv" ]]; then
  # The shared project .env is deliberately outside this repository.  Export
  # its values only for this process so they are never written to Git or shown
  # in command output.
  set -a
  # shellcheck disable=SC1090
  source "$dotenv"
  set +a
fi

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

seal_db_role() {
  local namespace="$1" name="$2" file="$3"; shift 3
  # CloudNativePG observes these labeled basic-auth Secrets and reconciles
  # the corresponding PostgreSQL role password immediately on rotation.
  local pair
  { for pair in "$@"; do printf '%s\n' "$pair"; done; } \
    | kubectl -n "$namespace" create secret generic "$name" \
        --type=kubernetes.io/basic-auth --from-env-file=/dev/stdin --dry-run=client -o yaml \
    | kubectl label --local -f - cnpg.io/reload=true -o yaml \
    | kubeseal --cert "$cert" --format yaml > "$staging/$file"
}

orders="$(openssl rand -base64 32)"; inventory="$(openssl rand -base64 32)"
catalog="$(openssl rand -base64 32)"
payments="$(openssl rand -base64 32)"; keycloak="$(openssl rand -base64 32)"
admin="$(openssl rand -base64 32)"; grafana="$(openssl rand -base64 32)"
client="$(openssl rand -base64 48)"; load_test_client="$(openssl rand -base64 48)"
api="${STRIPE_SECRET_KEY:-}"
alice_demo_password="${ALICE_PWD:-}"
bruno_demo_password="${BRUNO_PWD:-}"
chiara_demo_password="${CHIARA_PWD:-}"

read_if_missing() {
  local variable="$1" prompt="$2" value="${!1:-}"
  if [[ -z "$value" ]]; then
    read -rsp "$prompt" value
    echo
    printf -v "$variable" '%s' "$value"
  fi
}

read_if_missing api 'Payment provider API key: '
read_if_missing alice_demo_password 'Alice demo-user password: '
read_if_missing bruno_demo_password 'Bruno demo-user password: '
read_if_missing chiara_demo_password 'Chiara demo-user password: '
[[ -n "$api" ]] || { echo 'Payment provider API key must not be empty' >&2; exit 1; }
[[ -n "$alice_demo_password" && -n "$bruno_demo_password" && -n "$chiara_demo_password" ]] \
  || { echo 'Demo-user passwords must not be empty' >&2; exit 1; }
seal_db_role eurotransit orders-db-credentials orders-db-credentials.sealedsecret.yaml username=orders "password=$orders"
seal_db_role eurotransit catalog-db-credentials catalog-db-credentials.sealedsecret.yaml username=catalog "password=$catalog"
seal_db_role eurotransit inventory-db-credentials inventory-db-credentials.sealedsecret.yaml username=inventory "password=$inventory"
seal_db_role eurotransit payments-db-credentials payments-db-credentials.sealedsecret.yaml username=payments "password=$payments"
seal_db_role eurotransit keycloak-db-credentials keycloak-db-credentials-eurotransit.sealedsecret.yaml username=keycloak "password=$keycloak"
seal keycloak keycloak-db-credentials keycloak-db-credentials-keycloak.sealedsecret.yaml username=keycloak "password=$keycloak"
seal keycloak keycloak-admin-credentials keycloak-admin-credentials.sealedsecret.yaml username=kcadmin "password=$admin"
seal keycloak keycloak-demo-users-credentials keycloak-demo-users-credentials.sealedsecret.yaml "alice-password=$alice_demo_password" "bruno-password=$bruno_demo_password" "chiara-password=$chiara_demo_password"
seal eurotransit orders-service-credentials orders-service-credentials-eurotransit.sealedsecret.yaml "client-secret=$client"
seal keycloak orders-service-credentials orders-service-credentials-keycloak.sealedsecret.yaml "client-secret=$client"
seal eurotransit eurotransit-load-test-credentials eurotransit-load-test-credentials-eurotransit.sealedsecret.yaml "client-secret=$load_test_client"
seal keycloak eurotransit-load-test-credentials eurotransit-load-test-credentials-keycloak.sealedsecret.yaml "client-secret=$load_test_client"
seal eurotransit payments-provider-credentials payments-provider-credentials.sealedsecret.yaml "provider-api-key=$api"
seal monitoring grafana-admin-credentials grafana-admin-credentials.sealedsecret.yaml username=admin "password=$grafana"
unset catalog orders inventory payments keycloak admin grafana client load_test_client alice_demo_password bruno_demo_password chiara_demo_password api

"$ROOT_DIR/scripts/validate-aks-sealed-secrets.sh" "$staging"

previous="$parent/.secrets.previous.$$"
mv "$target" "$previous"
mv "$staging" "$target"; staging=""
rm -rf "$previous"; previous=""
git -C "$ROOT_DIR" diff --check
echo "Generated and validated 14 AKS SealedSecrets; review, commit through PR, then merge to main."
