#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

require_commands docker kind kubectl helm
require_app_repo

if [[ -z "${STRIPE_SECRET_KEY:-}" ]]; then
  echo "STRIPE_SECRET_KEY must contain a Stripe test-mode secret key for the Kind payments service." >&2
  echo "Example: STRIPE_SECRET_KEY=sk_test_... just kind-up" >&2
  exit 1
fi

if [[ "$STRIPE_SECRET_KEY" == sk_live_* ]]; then
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
  kind create cluster --config "$ROOT_DIR/platform/kind/kind-config.yaml"
fi
kubectl config use-context "kind-$KIND_CLUSTER_NAME" >/dev/null

services=(catalog orders inventory payments notifications)
if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  gradle_tasks=()
  for service in "${services[@]}"; do
    gradle_tasks+=(":$service:bootJar")
  done
  "$APP_DIR/gradlew" --no-daemon -p "$APP_DIR" "${gradle_tasks[@]}"
fi

for service in "${services[@]}"; do
  if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
    docker build -f "$APP_DIR/Dockerfile.ci" --build-arg "SERVICE=$service" \
      -t "eurotransit/$service:local" "$APP_DIR"
  elif ! docker image inspect "eurotransit/$service:local" >/dev/null 2>&1; then
    echo "Missing eurotransit/$service:local while SKIP_BUILD=1" >&2
    exit 1
  fi
  kind load docker-image --name "$KIND_CLUSTER_NAME" "eurotransit/$service:local"
done

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  docker build -f "$APP_DIR/frontend/Dockerfile" \
    --build-arg "VITE_KEYCLOAK_ISSUER=https://keycloak.eurotransit.local/realms/eurotransit" \
    --build-arg "VITE_KEYCLOAK_CLIENT_ID=eurotransit-frontend" \
    --build-arg "VITE_API_BASE=/api" \
    -t eurotransit/frontend:local "$APP_DIR/frontend"
elif ! docker image inspect "eurotransit/frontend:local" >/dev/null 2>&1; then
  echo "Missing eurotransit/frontend:local while SKIP_BUILD=1" >&2
  exit 1
fi
kind load docker-image --name "$KIND_CLUSTER_NAME" "eurotransit/frontend:local"

helm repo add traefik https://traefik.github.io/charts --force-update
helm repo add jetstack https://charts.jetstack.io --force-update
helm repo add cnpg https://cloudnative-pg.github.io/charts --force-update
helm repo add strimzi https://strimzi.io/charts/ --force-update
helm repo update

helm upgrade --install traefik traefik/traefik -n traefik --create-namespace \
  --version 36.3.0 -f "$ROOT_DIR/platform/traefik/values.yaml" \
  -f "$ROOT_DIR/platform/traefik/values-kind.yaml"
helm upgrade --install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --version v1.18.2 -f "$ROOT_DIR/platform/cert-manager/values.yaml" \
  -f "$ROOT_DIR/platform/cert-manager/values-kind.yaml"
helm upgrade --install cloudnativepg cnpg/cloudnative-pg -n cnpg-system --create-namespace \
  --version 0.24.0 -f "$ROOT_DIR/platform/cloudnativepg/values.yaml" \
  -f "$ROOT_DIR/platform/cloudnativepg/values-kind.yaml"
helm upgrade --install strimzi strimzi/strimzi-kafka-operator -n strimzi --create-namespace \
  --version 0.46.1 -f "$ROOT_DIR/platform/strimzi/values.yaml" \
  -f "$ROOT_DIR/platform/strimzi/values-kind.yaml"

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
kubectl -n keycloak create secret generic keycloak-admin-credentials \
  --from-literal=username=eurotransit-admin --from-literal=password=admin \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n keycloak create secret generic keycloak-db-credentials \
  --from-literal=username=keycloak --from-literal=password=password \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -k "$ROOT_DIR/platform/environments/kind"
kubectl -n eurotransit wait cluster/eurotransit-postgres --for=condition=Ready --timeout=8m
kubectl -n eurotransit wait kafka/eurotransit-kafka --for=condition=Ready --timeout=10m

kubectl apply -f https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.7.0/kubernetes/keycloaks.k8s.keycloak.org-v1.yml
kubectl apply -f https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.7.0/kubernetes/keycloakrealmimports.k8s.keycloak.org-v1.yml
kubectl apply -f https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.7.0/kubernetes/keycloakoidcclients.k8s.keycloak.org-v1.yml
kubectl apply -f https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.7.0/kubernetes/keycloaksamlclients.k8s.keycloak.org-v1.yml
kubectl -n keycloak apply -f https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.7.0/kubernetes/kubernetes.yml
kubectl -n keycloak rollout status deployment/keycloak-operator --timeout=5m
kubectl apply -k "$ROOT_DIR/platform/environments/keycloak-kind"

if [[ "${ENABLE_OBSERVABILITY:-0}" == "1" ]]; then
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
  helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
    -n monitoring --create-namespace --version 75.15.1 \
    -f "$ROOT_DIR/platform/kube-prometheus-stack/values.yaml" \
    --set prometheus.prometheusSpec.retention=1d \
    --set prometheus.prometheusSpec.resources.requests.memory=256Mi \
    --set prometheus.prometheusSpec.resources.limits.memory=512Mi \
    --set grafana.admin.existingSecret=""
fi

kubectl -n keycloak wait keycloak/eurotransit-keycloak --for=condition=Ready --timeout=8m
helm upgrade --install eurotransit "$ROOT_DIR/charts/eurotransit" -n eurotransit \
  -f "$ROOT_DIR/charts/eurotransit/values.yaml" \
  -f "$ROOT_DIR/charts/eurotransit/values-kind.yaml"
kubectl -n eurotransit rollout restart deployment/payments
wait_for_deployments eurotransit

echo "EuroTransit is ready. Run: just kind-test"
