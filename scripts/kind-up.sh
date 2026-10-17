#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

require_commands docker kind kubectl helm python3
KIND_PROFILE="${KIND_PROFILE:-dev}"
case "$KIND_PROFILE" in
  dev) platform_profile=kind; app_values=values-kind.yaml; cluster_config=kind-config.yaml ;;
  ha)
    if [[ "$KIND_CLUSTER_NAME" != eurotransit ]]; then
      echo "The HA placement rules currently require KIND_CLUSTER_NAME=eurotransit" >&2
      exit 2
    fi
    platform_profile=kind-ha; app_values=values-kind-ha.yaml; cluster_config=kind-ha-config.yaml ;;
  *) echo "KIND_PROFILE must be dev or ha" >&2; exit 2 ;;
esac
if [[ "$KIND_PROFILE" == ha ]]; then
  KIND_IMAGE_TAG="${KIND_IMAGE_TAG:-kind-ha}"
else
  KIND_IMAGE_TAG="${KIND_IMAGE_TAG:-local}"
fi
# Every cluster operation is scoped even if another terminal switches context.
kubectl() { command kubectl --context "kind-$KIND_CLUSTER_NAME" "$@"; }
helm() { command helm --kube-context "kind-$KIND_CLUSTER_NAME" "$@"; }
require_app_repo

if [[ -z "${STRIPE_SECRET_KEY:-}" ]]; then
  echo "STRIPE_SECRET_KEY must contain a Stripe test-mode secret key for the Kind payments service." >&2
  echo "Example: STRIPE_SECRET_KEY=sk_test_... just kind-up" >&2
  exit 1
fi

if [[ "$STRIPE_SECRET_KEY" != sk_test_* && "$STRIPE_SECRET_KEY" != rk_test_* ]]; then
  echo "Refusing to use a live Stripe key in the local Kind environment; use a test-mode key." >&2
  exit 1
fi

docker_memory_bytes="$(docker info --format '{{.MemTotal}}')"
# if [[ "$docker_memory_bytes" =~ ^[0-9]+$ ]] && (( docker_memory_bytes < 8589934592 )); then
#   echo "The integral Kind profile requires Docker Desktop with at least 8 GiB RAM." >&2
#   echo "Current Docker memory: $docker_memory_bytes bytes." >&2
#   exit 1
# fi

if ! kind get clusters | grep -qx "$KIND_CLUSTER_NAME"; then
  kind create cluster --name "$KIND_CLUSTER_NAME" --config "$ROOT_DIR/platform/kind/$cluster_config"
fi
kubectl config use-context "kind-$KIND_CLUSTER_NAME" >/dev/null
if [[ "$KIND_PROFILE" == ha ]]; then
  kubectl get nodes -o json | python3 -c '
import json, sys
nodes = json.load(sys.stdin)["items"]
workers = [n for n in nodes if "node-role.kubernetes.io/control-plane" not in n["metadata"].get("labels", {})]
if len(nodes) != 4 or len(workers) != 3:
    sys.exit("HA requires one control plane and three workers; an existing dev cluster is not converted automatically")
'
fi

services=(catalog orders inventory payments notifications)
for service in "${services[@]}"; do
  if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
    docker build -f "$APP_DIR/Dockerfile" --build-arg "SERVICE=$service" \
      -t "eurotransit/$service:$KIND_IMAGE_TAG" "$APP_DIR"
  elif ! docker image inspect "eurotransit/$service:$KIND_IMAGE_TAG" >/dev/null 2>&1; then
    echo "Missing eurotransit/$service:$KIND_IMAGE_TAG while SKIP_BUILD=1" >&2
    exit 1
  fi
  kind load docker-image --name "$KIND_CLUSTER_NAME" "eurotransit/$service:$KIND_IMAGE_TAG"
done

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  docker build -f "$APP_DIR/frontend/Dockerfile" \
    -t eurotransit/frontend:$KIND_IMAGE_TAG "$APP_DIR/frontend"
elif ! docker image inspect "eurotransit/frontend:$KIND_IMAGE_TAG" >/dev/null 2>&1; then
  echo "Missing eurotransit/frontend:$KIND_IMAGE_TAG while SKIP_BUILD=1" >&2
  exit 1
fi
kind load docker-image --name "$KIND_CLUSTER_NAME" "eurotransit/frontend:$KIND_IMAGE_TAG"

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  docker build -f "$APP_DIR/connect/Dockerfile" \
    -t eurotransit/debezium-connect:$KIND_IMAGE_TAG "$APP_DIR"
elif ! docker image inspect eurotransit/debezium-connect:$KIND_IMAGE_TAG >/dev/null 2>&1; then
  echo "Missing eurotransit/debezium-connect:$KIND_IMAGE_TAG while SKIP_BUILD=1" >&2
  exit 1
fi
kind load docker-image --name "$KIND_CLUSTER_NAME" eurotransit/debezium-connect:$KIND_IMAGE_TAG

helm repo add traefik https://traefik.github.io/charts --force-update
helm repo add jetstack https://charts.jetstack.io --force-update
helm repo add cnpg https://cloudnative-pg.github.io/charts --force-update
helm repo add strimzi https://strimzi.io/charts/ --force-update
helm repo update
platform_helm_args=()
cnpg_ha_args=()
strimzi_ha_args=()
if [[ "$KIND_PROFILE" == ha ]]; then
  platform_helm_args=(-f "$ROOT_DIR/platform/kind/values-ha-controllers.yaml")
  cnpg_ha_args=(-f "$ROOT_DIR/platform/cloudnativepg/values-kind-ha.yaml")
  strimzi_ha_args=(-f "$ROOT_DIR/platform/strimzi/values-kind-ha.yaml")
fi

helm upgrade --install traefik traefik/traefik -n traefik --create-namespace \
  --version 36.3.0 -f "$ROOT_DIR/platform/traefik/values.yaml" \
  -f "$ROOT_DIR/platform/traefik/values-kind.yaml"
helm upgrade --install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --version v1.18.2 -f "$ROOT_DIR/platform/cert-manager/values.yaml" \
  -f "$ROOT_DIR/platform/cert-manager/values-kind.yaml"
helm upgrade --install cloudnativepg cnpg/cloudnative-pg -n cnpg-system --create-namespace \
  --version 0.24.0 -f "$ROOT_DIR/platform/cloudnativepg/values.yaml" \
  -f "$ROOT_DIR/platform/cloudnativepg/values-kind.yaml" "${platform_helm_args[@]}" "${cnpg_ha_args[@]}"
helm upgrade --install strimzi strimzi/strimzi-kafka-operator -n strimzi --create-namespace \
  --version 0.46.1 -f "$ROOT_DIR/platform/strimzi/values.yaml" \
  -f "$ROOT_DIR/platform/strimzi/values-kind.yaml" "${platform_helm_args[@]}" "${strimzi_ha_args[@]}"

wait_for_deployments traefik
wait_for_deployments cert-manager
wait_for_deployments cnpg-system
wait_for_deployments strimzi

kubectl apply -f "$ROOT_DIR/platform/environments/kind/namespaces.yaml"
kubectl -n eurotransit create secret generic orders-db-credentials \
  --from-literal=username=orders --from-literal=password=password \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n eurotransit create secret generic inventory-db-credentials \
  --from-literal=username=inventory --from-literal=password=password \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n eurotransit create secret generic payments-db-credentials \
  --from-literal=username=payments --from-literal=password=password \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n eurotransit create secret generic keycloak-db-credentials \
  --from-literal=username=keycloak --from-literal=password=password \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n eurotransit create secret generic payments-provider-credentials \
  --from-literal="provider-api-key=$STRIPE_SECRET_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n eurotransit create secret generic orders-service-credentials \
  --from-literal=client-secret=orders-service-secret \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n keycloak create secret generic keycloak-admin-credentials \
  --from-literal=username=eurotransit-admin --from-literal=password=admin \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n keycloak create secret generic keycloak-demo-users-credentials \
  --from-literal='alice-password=Alice!Metro#2026' \
  --from-literal='bruno-password=Bruno!Route#2026' \
  --from-literal='chiara-password=Chiara!Ticket#2026' \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n keycloak create secret generic keycloak-db-credentials \
  --from-literal=username=keycloak --from-literal=password=password \
  --dry-run=client -o yaml | kubectl apply -f -

# The load-test Keycloak bootstrap consumes this local-only technical credential.
# Preserve it on repeated runs and copy it only between namespaces in this Kind.
python3 - "$KIND_CLUSTER_NAME" <<'PY_LOCAL_CLIENT'
import base64, json, secrets, subprocess, sys
context = "kind-" + sys.argv[1]
lookup = subprocess.run(["kubectl", "--context", context, "-n", "eurotransit",
                         "get", "secret", "eurotransit-load-test-credentials",
                         "--ignore-not-found", "-o", "json"], capture_output=True, text=True, check=True)
value = (base64.b64decode(json.loads(lookup.stdout)["data"]["client-secret"]).decode()
         if lookup.stdout.strip() else secrets.token_urlsafe(32))
for namespace in ("eurotransit", "keycloak"):
    secret = {"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
              "metadata": {"name": "eurotransit-load-test-credentials", "namespace": namespace},
              "stringData": {"client-secret": value}}
    subprocess.run(["kubectl", "--context", context, "apply", "-f", "-"],
                   input=json.dumps(secret), text=True, check=True)
PY_LOCAL_CLIENT

kubectl apply -k "$ROOT_DIR/platform/environments/$platform_profile"
kubectl -n eurotransit wait cluster/eurotransit-postgres --for=condition=Ready --timeout=8m
kubectl -n eurotransit wait kafka/eurotransit-kafka --for=condition=Ready --timeout=10m

kubectl apply -f https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.7.0/kubernetes/keycloaks.k8s.keycloak.org-v1.yml
kubectl apply -f https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.7.0/kubernetes/keycloakrealmimports.k8s.keycloak.org-v1.yml
kubectl apply -f https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.7.0/kubernetes/keycloakoidcclients.k8s.keycloak.org-v1.yml
kubectl apply -f https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.7.0/kubernetes/keycloaksamlclients.k8s.keycloak.org-v1.yml
kubectl -n keycloak apply -f https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.7.0/kubernetes/kubernetes.yml
kubectl -n keycloak rollout status deployment/keycloak-operator --timeout=5m
keycloak_profile=keycloak-kind
if [[ "$KIND_PROFILE" == ha ]]; then keycloak_profile=keycloak-kind-ha; fi
kubectl apply -k "$ROOT_DIR/platform/environments/$keycloak_profile"

if [[ "${ENABLE_OBSERVABILITY:-0}" == "1" ]]; then
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
  observability_helm_args=()
  if [[ "$KIND_PROFILE" == ha ]]; then observability_helm_args=(-f "$ROOT_DIR/platform/kube-prometheus-stack/values-kind-ha.yaml"); fi
  helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
    -n monitoring --create-namespace --version 75.15.1 \
    -f "$ROOT_DIR/platform/kube-prometheus-stack/values.yaml" \
    --set prometheus.prometheusSpec.retention=1d \
    --set prometheus.prometheusSpec.resources.requests.memory=256Mi \
    --set prometheus.prometheusSpec.resources.limits.memory=512Mi \
    --set grafana.admin.existingSecret="" "${observability_helm_args[@]}"
  if [[ "$KIND_PROFILE" == ha ]]; then
    kubectl wait --for=condition=Established crd/podmonitors.monitoring.coreos.com --timeout=90s
    kubectl apply -f "$ROOT_DIR/platform/kube-prometheus-stack/kafka-exporter-podmonitor-kind-ha.yaml"
  fi
fi

kubectl -n keycloak wait keycloak/eurotransit-keycloak --for=condition=Ready --timeout=8m
helm upgrade --install eurotransit "$ROOT_DIR/charts/eurotransit" -n eurotransit \
  -f "$ROOT_DIR/charts/eurotransit/values.yaml" \
  -f "$ROOT_DIR/charts/eurotransit/$app_values" \
  --set-string catalog.image.tag="$KIND_IMAGE_TAG",orders.image.tag="$KIND_IMAGE_TAG",inventory.image.tag="$KIND_IMAGE_TAG",payments.image.tag="$KIND_IMAGE_TAG",notifications.image.tag="$KIND_IMAGE_TAG",frontend.image.tag="$KIND_IMAGE_TAG" \
  --wait --timeout 8m
kubectl -n eurotransit rollout restart deployment/payments
wait_for_deployments eurotransit

# Remove only the previous unmanaged Kafka Connect resources during upgrades.
kubectl -n eurotransit delete \
  deployment/orders-outbox-connect deployment/inventory-outbox-connect \
  service/orders-outbox-connect service/inventory-outbox-connect \
  job/orders-outbox-connector-register job/inventory-outbox-connector-register \
  --ignore-not-found

kubectl apply -k "$ROOT_DIR/platform/connectors/environments/$platform_profile"
connects=(orders-outbox-connect inventory-outbox-connect payments-outbox-connect)
if [[ "$KIND_PROFILE" == ha ]]; then connects=(orders-outbox-connect); fi
for connect in "${connects[@]}"; do
  kubectl -n eurotransit wait "kafkaconnect/$connect" \
    --for=condition=Ready --timeout=8m
done
for connector in orders-outbox-connector inventory-outbox-connector payments-outbox-connector; do
  kubectl -n eurotransit wait "kafkaconnector/$connector" \
    --for=condition=Ready --timeout=8m
done

echo "EuroTransit is ready. Run: just kind-test"
