#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_commands curl kubectl kind
KIND_PROFILE="${KIND_PROFILE:-dev}"
case "$KIND_PROFILE" in dev|ha) ;; *) echo "KIND_PROFILE must be dev or ha" >&2; exit 2 ;; esac
kubectl() { command kubectl --context "kind-$KIND_CLUSTER_NAME" "$@"; }
connects=(orders-outbox-connect inventory-outbox-connect payments-outbox-connect)
if [[ "$KIND_PROFILE" == ha ]]; then connects=(orders-outbox-connect); fi

kubectl config use-context "kind-$KIND_CLUSTER_NAME" >/dev/null
wait_for_deployments eurotransit
wait_for_deployments keycloak
for connect in "${connects[@]}"; do
  kubectl -n eurotransit wait "kafkaconnect/$connect" \
    --for=condition=Ready --timeout=2m
done
for connector in orders-outbox-connector inventory-outbox-connector payments-outbox-connector; do
  kubectl -n eurotransit wait "kafkaconnector/$connector" \
    --for=condition=Ready --timeout=2m
done

curl -ksSf --resolve eurotransit.local:443:127.0.0.1 \
  https://eurotransit.local/api/catalog/routes >/dev/null
curl -ksSf --resolve keycloak.eurotransit.local:443:127.0.0.1 \
  https://keycloak.eurotransit.local/realms/eurotransit/.well-known/openid-configuration >/dev/null

status="$(curl -ksS -o /dev/null -w '%{http_code}' --resolve eurotransit.local:443:127.0.0.1 \
  -X POST -H 'Content-Type: application/json' -H 'Idempotency-Key: kind-auth-check' \
  -d '{}' https://eurotransit.local/api/orders)"
case "$status" in 401|403) ;; *) echo "Expected Orders 401/403, got $status" >&2; exit 1 ;; esac

if kubectl -n eurotransit get ingressroute -o yaml | rg -q 'PathPrefix\(`/api/(inventory|payments)'; then
  echo "Inventory or Payments is publicly routed" >&2
  exit 1
fi
echo "Kind smoke tests passed"
