# EuroTransit AKS Production Setup

This runbook deploys EuroTransit Marketplace on the fixed AKS target of three
`Standard_B2als_v2` nodes. It is a constrained production profile: it provides
the complete backend platform with reduced availability, not full HA.

## Target

- Public hostname: `g05.cpo2026.it`.
- Azure Load Balancer hostname: `g05-eurotransit.swedencentral.cloudapp.azure.com`.
- Public entrypoint: Traefik on ports 80 and 443.
- OIDC issuer: `https://g05.cpo2026.it/realms/eurotransit`.
- GitOps owner: Argo CD.
- Runtime overlay: `platform/environments/aks`.

Before deployment, confirm that `g05.cpo2026.it` resolves to the Azure Load
Balancer hostname. The frontend is not included because no frontend workload
currently exists in the sibling application repository.

## 1. Prerequisites

Required tools are `az`, `kubectl`, `helm`, `argocd`, `kubeseal`, and `just`.
Set the target identifiers:

```bash
export AKS_RESOURCE_GROUP='<resource-group>'
export AKS_CLUSTER_NAME='<cluster-name>'
export ACR_NAME='eurotransitregistry'
```

Connect and verify the fixed capacity:

```bash
az aks get-credentials --resource-group "$AKS_RESOURCE_GROUP" --name "$AKS_CLUSTER_NAME" --overwrite-existing
kubectl get nodes -o wide
kubectl top nodes
az aks check-acr --resource-group "$AKS_RESOURCE_GROUP" --name "$AKS_CLUSTER_NAME" --acr "$ACR_NAME"
```

There must be three Ready nodes. Attach ACR with `az aks update --attach-acr`
if the registry check fails.

## 2. Validate Manifests

From the configuration repository:

```bash
just render-aks
```

The AKS profile uses one replica for Traefik, Keycloak, CloudNativePG, Kafka,
and each application service. Prometheus retention and resource limits are
reduced. Chaos Mesh is not installed by the normal Argo CD application set.
Keycloak is managed by the official Keycloak Operator `26.7.0` and shares the
constrained CloudNativePG cluster through the dedicated `keycloak_db` database.

## 3. Prepare Secrets

Bootstrap Sealed Secrets first, fetch its certificate, and replace every
example encrypted value with a value sealed for the production cluster:

```bash
kubeseal --controller-name sealed-secrets-controller \
  --controller-namespace sealed-secrets --fetch-cert \
  > /tmp/eurotransit-sealed-secrets.pem
```

Required secrets include database credentials for Orders, Inventory, Payments
and Keycloak (in both `eurotransit` for CloudNativePG and `keycloak` for the
operator), payment provider credentials, Keycloak admin credentials,
Grafana credentials, and an Argo CD repository secret when the repository is
private. Commit only `SealedSecret` resources, never plaintext `Secret` files.

The Let's Encrypt account email in
`platform/environments/aks/letsencrypt-cluster-issuer.yaml` defaults to
`admin@cpo2026.it`; replace it before go-live if that mailbox is not monitored.

## 4. Bootstrap Argo CD

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd --create-namespace \
  -f platform/argocd/values.yaml
kubectl -n argocd rollout status deploy/argocd-server
kubectl apply -k platform/argocd
```

When testing before merge, change every relevant `targetRevision` from `main`
to the pushed branch. Restore `main` before merging.

## 5. Sync In Order

```bash
argocd app sync traefik cert-manager sealed-secrets strimzi cloudnativepg
argocd app sync kube-prometheus-stack keycloak
argocd app sync eurotransit-platform-runtime
argocd app sync eurotransit-marketplace
```

After each group, inspect memory before continuing:

```bash
kubectl get pods -A
kubectl top nodes
kubectl top pods -A --sort-by=memory
kubectl get events -A --sort-by=.lastTimestamp
```

Do not increase replica counts until steady-state measurements prove that the
cluster has sufficient headroom.

## 6. Validate DNS, TLS And OIDC

```bash
kubectl -n traefik get svc traefik
kubectl -n eurotransit get certificate eurotransit-production-tls
curl -fsS https://g05.cpo2026.it/realms/eurotransit/.well-known/openid-configuration
```

The discovery document must report an issuer exactly equal to
`https://g05.cpo2026.it/realms/eurotransit`. Application API routes share the
same host; Keycloak owns non-API paths.

## 7. Smoke Test

```bash
curl -fsS https://g05.cpo2026.it/api/catalog/routes
curl -i -X POST https://g05.cpo2026.it/api/orders \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: aks-auth-check' -d '{}'
kubectl -n eurotransit get ingressroute -o yaml | rg 'inventory|payments' || true
```

Catalog must respond, Orders without a JWT must return 401 or 403, and neither
Inventory nor Payments may have a public route. Also verify all application
rollouts and Prometheus targets.

## 8. Rollback

Use Git as the source of truth:

```bash
git revert <bad-configuration-commit>
git push
argocd app sync eurotransit-platform-runtime eurotransit-marketplace
```

An emergency `kubectl rollout undo` must be followed by the equivalent Git
change or Argo CD will restore the undesired state.

## Capacity And Availability Statement

The profile intentionally has no stateful failover: PostgreSQL, Kafka and
Keycloak each run as a single instance. Long-term Prometheus retention and
steady-state Chaos Mesh are excluded. Production readiness means stable
scheduling and correct operation on the assigned hardware, not node-failure
tolerance.
