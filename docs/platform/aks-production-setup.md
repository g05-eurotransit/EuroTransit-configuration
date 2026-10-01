# EuroTransit AKS production bootstrap

Sealed Secrets controller/key lifecycle is cluster-admin-owned and never Argo-owned. Application ciphertext under `platform/environments/aks/secrets` is Argo wave 5; the versioned Argo repository credential under `platform/argocd/bootstrap/aks` is the sole manually applied SealedSecret.

## 1. Preconditions

```bash
export AZ_SUBSCRIPTION='<subscription-id>' AKS_RESOURCE_GROUP='<resource-group>'
export AKS_CLUSTER_NAME='<cluster-name>' ACR_NAME='eurotransitregistry'
az login
az account set --subscription "$AZ_SUBSCRIPTION"
az aks get-credentials -g "$AKS_RESOURCE_GROUP" -n "$AKS_CLUSTER_NAME" --overwrite-existing
kubectl config current-context
kubectl get nodes -o wide                    # exactly three Ready nodes
az aks check-acr -g "$AKS_RESOURCE_GROUP" -n "$AKS_CLUSTER_NAME" --acr "$ACR_NAME" \
  || az aks update -g "$AKS_RESOURCE_GROUP" -n "$AKS_CLUSTER_NAME" --attach-acr "$ACR_NAME"
```

Set `g05.cpo2026.it` CNAME to `g05-eurotransit.swedencentral.cloudapp.azure.com` before root creation and verify `dig +short g05.cpo2026.it`. Confirm the account email in `platform/environments/aks/letsencrypt-cluster-issuer.yaml` is monitored.

## 2. Images and fail-closed rendering

```bash
export IMAGE_TAG='<immutable tag committed on main>'
export CONNECT_IMAGE_TAG='strimzi-0.46.1-kafka-3.9.0-debezium-2.7.0'
for image in catalog orders inventory payments notifications frontend; do
  az acr repository show -n "$ACR_NAME" --image "eurotransit/$image:$IMAGE_TAG" --output none
done
az acr repository show -n "$ACR_NAME" --image "eurotransit/debezium-connect:$CONNECT_IMAGE_TAG" --output none
just render-kind
just render-aks                         # intentionally fails before ciphertext exists
ALLOW_MISSING_AKS_SECRETS=1 just render-aks # scaffold-only validation
```

The scaffold flag validates only paths and placeholder structure. It is not a
production render: after ciphertext generation, both the normal `just
render-kind` and normal `just render-aks` commands must pass before the final
ciphertext revision is merged.

If required, build and push the immutable images from the sibling application
repository. The backend uses its root `Dockerfile` and the required `SERVICE`
argument; the frontend is environment-independent and receives its public runtime
configuration from the Helm-managed ConfigMap, while the connector uses the exact
Dockerfile and tag below.

```bash
export APP_REPOSITORY=../EuroTransit-application
export CONNECT_IMAGE_TAG='strimzi-0.46.1-kafka-3.9.0-debezium-2.7.0'
az acr login --name "$ACR_NAME"
for service in catalog orders inventory payments notifications; do
  docker build -f "$APP_REPOSITORY/Dockerfile" --build-arg SERVICE="$service" \
    -t "$ACR_NAME.azurecr.io/eurotransit/$service:$IMAGE_TAG" "$APP_REPOSITORY"
  docker push "$ACR_NAME.azurecr.io/eurotransit/$service:$IMAGE_TAG"
done
docker build -f "$APP_REPOSITORY/frontend/Dockerfile" \
  -t "$ACR_NAME.azurecr.io/eurotransit/frontend:$IMAGE_TAG" "$APP_REPOSITORY/frontend"
docker push "$ACR_NAME.azurecr.io/eurotransit/frontend:$IMAGE_TAG"
docker build -f "$APP_REPOSITORY/connect/Dockerfile" \
  -t "$ACR_NAME.azurecr.io/eurotransit/debezium-connect:$CONNECT_IMAGE_TAG" "$APP_REPOSITORY"
docker push "$ACR_NAME.azurecr.io/eurotransit/debezium-connect:$CONNECT_IMAGE_TAG"
```

Never use `latest`. Update image references through a reviewed PR; root reads
protected `main`, so images and configuration must be merged before bootstrap.

## 3. Admin-owned controller and ciphertext

### First installation

```bash
kubectl apply -f platform/environments/aks/namespaces.yaml
helm repo add bitnami https://charts.bitnami.com/bitnami && helm repo update
helm upgrade --install sealed-secrets bitnami/sealed-secrets --version 2.5.19 \
  -n sealed-secrets --create-namespace -f platform/sealed-secrets/values.yaml -f platform/sealed-secrets/values-aks.yaml
kubectl -n sealed-secrets rollout status deploy/sealed-secrets-controller --timeout=5m
# This Kubernetes label selector inventories the controller key Secrets.
kubectl -n sealed-secrets get secret \
  -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o custom-columns=NAME:.metadata.name,CREATED:.metadata.creationTimestamp
kubeseal --controller-name sealed-secrets-controller --controller-namespace sealed-secrets \
  --fetch-cert > /tmp/eurotransit-sealed-secrets.pem
```

Record that initial inventory and complete the approved encrypted, off-cluster
key backup before generating ciphertext or bootstrapping Argo; this is a hard
gate. Never create a plaintext private-key file, uninstall the release, or
delete its namespace or key Secrets.

### Subsequent controller upgrades

Controller upgrades are cluster-admin actions. Before an upgrade, record the
same key inventory and ensure its encrypted off-cluster backup is current. Use
the reviewed upgrade chart version, wait for rollout, then record and compare
the after inventory:

```bash
kubectl -n sealed-secrets get secret \
  -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o custom-columns=NAME:.metadata.name,CREATED:.metadata.creationTimestamp
export SEALED_SECRETS_CHART_VERSION='<reviewed-upgrade-version>'
helm upgrade sealed-secrets bitnami/sealed-secrets \
  --version "$SEALED_SECRETS_CHART_VERSION" \
  -n sealed-secrets -f platform/sealed-secrets/values.yaml -f platform/sealed-secrets/values-aks.yaml
kubectl -n sealed-secrets rollout status deploy/sealed-secrets-controller --timeout=5m
kubectl -n sealed-secrets get secret \
  -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o custom-columns=NAME:.metadata.name,CREATED:.metadata.creationTimestamp
```

Disaster recovery restores all required original keys before any ciphertext is
reconciled, then runs a DR test outside production.

```bash
SEALED_SECRETS_CERT=/tmp/eurotransit-sealed-secrets.pem scripts/generate-aks-sealed-secrets.sh
scripts/validate-aks-sealed-secrets.sh platform/environments/aks/secrets
just render-kind
just render-aks
git switch -c aks/sealed-secrets-bootstrap
git add platform/environments/aks/secrets
git commit -m 'Add AKS SealedSecret ciphertext'
export REVIEWED_COMMIT="$(git rev-parse HEAD)"
# Open PR, obtain required review, merge through protected main.
git fetch origin main
git merge-base --is-ancestor "$REVIEWED_COMMIT" origin/main
```

The generator asks for the payment-provider value and the three demo-user passwords, then creates all eleven ciphertexts without plaintext files, including the same Orders secret separately scoped to `eurotransit` and `keycloak`.

The final command must exit zero: it verifies that the reviewed commit is an
ancestor of `origin/main`, rather than merely displaying its latest commit.

## 4. Bootstrap Argo

The repository credential is versioned as ciphertext at
`platform/argocd/bootstrap/aks/eurotransit-configuration-repo.sealedsecret.yaml`.
It is applied manually before root creation and is outside `eurotransit-secrets`
and all Argo kustomizations. Clone the repository using your own GitHub access;
Argo's token is used only after the bootstrap Secret exists.

On another PC with the same cluster, reuse the committed ciphertext. On a new
cluster, restore the required original controller keys from the encrypted
backup first. If those keys are unavailable or the GitHub token has expired or
been revoked, generate a replacement as described below. Ciphertext in Git is
not a backup of controller private keys.

```bash
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubeseal --controller-name sealed-secrets-controller --controller-namespace sealed-secrets \
  --validate < platform/argocd/bootstrap/aks/eurotransit-configuration-repo.sealedsecret.yaml
kubectl apply -f platform/argocd/bootstrap/aks/eurotransit-configuration-repo.sealedsecret.yaml
kubectl -n argocd wait --for=condition=Synced \
  sealedsecret/eurotransit-configuration-repo --timeout=60s
helm repo add argo https://argoproj.github.io/argo-helm && helm repo update
helm upgrade --install argocd argo/argo-cd --version 10.2.2 -n argocd --create-namespace -f platform/argocd/values.yaml -f platform/argocd/values-aks.yaml
kubectl -n argocd rollout status deploy/argocd-server --timeout=5m
argocd login --core && argocd repo list
kubectl apply -k apps/argocd-apps/environments/aks
argocd app wait eurotransit-platform-root --sync --health --timeout 1800
```

Repository access must be `Successful` before root creation. No runtime Secret is applied manually after this point.

| Wave | Owner/content |
| --- | --- |
| 5 | `eurotransit-secrets`; SealedSecret `Synced=True` health |
| 10 | Traefik, cert-manager, Strimzi, CNPG, monitoring; never controller |
| 15/20 | Keycloak Operator; runtime/TLS |
| 25/30/40 | Keycloak plus client Job; marketplace; connectors |

Confirm no Argo Application owns the controller and inspect `kubectl -n argocd get applications`.

```bash
argocd app get eurotransit-secrets
kubectl -n argocd get application eurotransit-secrets \
  -o jsonpath='{.status.health.status}{"\n"}' # Healthy
if kubectl -n argocd get application sealed-secrets; then
  echo 'sealed-secrets must not be Argo-owned' >&2; exit 1
else
  echo 'confirmed: sealed-secrets Application is absent'
fi
```

### Repository token rotation or sealing for a new controller

Use a dedicated fine-grained GitHub token with read-only Contents access only
to `EuroTransit-configuration`; enter the personal username that owns the token.
Fetch the target controller certificate after the key-backup gate above. With
shell tracing disabled, regenerate only ciphertext, validate it, then apply it
manually. Review and commit the replacement file after access is restored;
Argo does not apply repository credential rotations from Git.

```bash
set -euo pipefail
read -rp 'GitHub username: ' ARGO_REPO_USERNAME
read -rsp 'Read-only repository token: ' ARGO_REPO_TOKEN; echo
printf 'type=git\nurl=https://github.com/g05-eurotransit/EuroTransit-configuration.git\nusername=%s\npassword=%s\n' "$ARGO_REPO_USERNAME" "$ARGO_REPO_TOKEN" \
 | kubectl -n argocd create secret generic eurotransit-configuration-repo --from-env-file=/dev/stdin --dry-run=client -o yaml \
 | kubectl label --local -f - argocd.argoproj.io/secret-type=repository -o yaml \
 | kubeseal --cert /tmp/eurotransit-sealed-secrets.pem --scope strict --format yaml \
 > platform/argocd/bootstrap/aks/eurotransit-configuration-repo.sealedsecret.yaml
unset ARGO_REPO_USERNAME ARGO_REPO_TOKEN
kubeseal --controller-name sealed-secrets-controller --controller-namespace sealed-secrets \
  --validate < platform/argocd/bootstrap/aks/eurotransit-configuration-repo.sealedsecret.yaml
kubectl apply -f platform/argocd/bootstrap/aks/eurotransit-configuration-repo.sealedsecret.yaml
kubectl -n argocd wait --for=condition=Synced \
  sealedsecret/eurotransit-configuration-repo --timeout=60s
argocd repo list
# Require Successful, then review and commit only the replacement ciphertext.
```

Never commit the token, the decrypted Secret, or controller private keys.

## 5. Acceptance and operations

```bash
kubectl -n traefik get svc traefik
kubectl -n eurotransit get certificate eurotransit-production-tls
kubectl -n keycloak get certificate eurotransit-production-tls
kubectl -n eurotransit wait --for=condition=Ready certificate/eurotransit-production-tls --timeout=10m
kubectl -n keycloak wait --for=condition=Ready certificate/eurotransit-production-tls --timeout=10m
INGRESSROUTES_YAML="$(kubectl get ingressroute -A -o yaml)"
printf '%s\n' "$INGRESSROUTES_YAML"
if printf '%s\n' "$INGRESSROUTES_YAML" | rg -qi \
  '^[[:space:]]*(-[[:space:]]*)?name:[[:space:]]*(inventory|payments)([[:space:]]|$)'; then
  echo 'Inventory and Payments must not have public IngressRoutes' >&2; exit 1
else
  echo 'confirmed: Inventory and Payments IngressRoutes are absent'
fi
kubectl -n eurotransit get servicemonitor
kubectl -n monitoring get servicemonitor
kubectl -n monitoring get prometheus
kubectl -n eurotransit get kafka,kafkatopic,cluster
kubectl -n eurotransit get kafkaconnect,kafkaconnector
kubectl get pods -A; kubectl get events -A --sort-by=.lastTimestamp
kubectl top nodes; kubectl top pods -A --sort-by=memory
curl -fsS https://g05.cpo2026.it/realms/eurotransit/.well-known/openid-configuration
curl -fsS https://g05.cpo2026.it/api/catalog/routes
curl -i -X POST https://g05.cpo2026.it/api/orders -H 'Content-Type: application/json' -H 'Idempotency-Key: aks-check' -d '{}'
```

The EuroTransit and Keycloak Certificates must be `Ready=True`. The only public
IngressRoutes are the EuroTransit and Keycloak routes: the `eurotransit` list
must contain no Inventory or Payments route. Confirm ServiceMonitors are present
and that Prometheus is Ready with their targets discovered; confirm each
`KafkaConnect` and `KafkaConnector` reports Ready after Orders/Inventory Flyway
succeeds. This fixed three-node, single-instance topology is deliberately
non-HA: use the `kubectl top` output to confirm capacity headroom, not a claim
of node or process failure tolerance.

If root sync times out, inspect its child Applications and their resource
health, then diagnose pending certificates explicitly:

```bash
argocd app get eurotransit-platform-root
kubectl -n argocd get applications
kubectl -n eurotransit describe certificate eurotransit-production-tls
kubectl -n keycloak describe certificate eurotransit-production-tls
kubectl get challenge,order -A
```

The OIDC issuer must be public; Orders without JWT returns 401/403;
Inventory/Payments have no public route.

Rollback Argo-owned resources by reverting the reviewed Git revision through
the normal PR flow and syncing Argo to that Git state. Rotate application
secrets by PR-merging new ciphertext. Orders rotation updates the identical
value in both `keycloak` and `eurotransit`, then deletes the completed
`orders-service-client-secret-bootstrap` Job so Argo recreates it in wave 25.
Controller disaster recovery is separate: restore original controller keys
before any ciphertext reconciliation, then perform the DR test described above.
