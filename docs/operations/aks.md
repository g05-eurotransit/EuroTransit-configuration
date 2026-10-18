# Bootstrap and operate constrained AKS

Prepare Azure access, images and cluster-specific ciphertext, then use the shared [GitOps bootstrap](gitops.md). The current AKS profile is constrained and single-instance; [deployment](../platform/deployment.md) owns topology and [readiness](../readiness.md) records evidence gaps.

## Preconditions

```bash
export AZ_SUBSCRIPTION='<subscription-id>' AKS_RESOURCE_GROUP='<resource-group>'
export AKS_CLUSTER_NAME='<cluster-name>' ACR_NAME='eurotransitregistry'
az login
az account set --subscription "$AZ_SUBSCRIPTION"
az aks get-credentials -g "$AKS_RESOURCE_GROUP" -n "$AKS_CLUSTER_NAME" --overwrite-existing
kubectl config current-context
kubectl get nodes -o wide
az aks check-acr -g "$AKS_RESOURCE_GROUP" -n "$AKS_CLUSTER_NAME" --acr "$ACR_NAME"
```

Require the intended three Ready nodes and working ACR access. If attachment is missing, an authorized cluster administrator can use `az aks update --attach-acr`. Confirm the public CNAME and issuer inputs from [deployment](../platform/deployment.md) and the monitored email in the [certificate issuer](../../platform/environments/aks/letsencrypt-cluster-issuer.yaml).

## Images and rendering

Use the reviewed per-service image references from [production values](../../charts/eurotransit/values-production.yaml) and base values. Verify every application image and the connector digest exist in ACR and are pullable. Application [image publication](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/.github/workflows/docker-gitops.yml) and [connector publication](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/.github/workflows/connect-gitops.yml) own builds; never substitute `latest` for a release identity.

```bash
just render-kind
just render-aks
```

The AKS render fails closed without its required ciphertext inventory. `ALLOW_MISSING_AKS_SECRETS=1 just render-aks` validates only scaffolding; both normal renders must pass before releasing the final ciphertext revision.

## Controller and application secrets

Sealed Secrets controller and keys are cluster-admin-owned. Install it outside Argo CD:

```bash
kubectl apply -f platform/environments/aks/namespaces.yaml
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update
helm upgrade --install sealed-secrets bitnami/sealed-secrets --version 2.5.19   -n sealed-secrets --create-namespace   -f platform/sealed-secrets/values.yaml -f platform/sealed-secrets/values-aks.yaml
kubectl -n sealed-secrets rollout status deploy/sealed-secrets-controller --timeout=5m
kubectl -n sealed-secrets get secret -l sealedsecrets.bitnami.com/sealed-secrets-key   -o custom-columns=NAME:.metadata.name,CREATED:.metadata.creationTimestamp
kubeseal --controller-name sealed-secrets-controller --controller-namespace sealed-secrets   --fetch-cert > /tmp/eurotransit-sealed-secrets.pem
```

Record the key inventory and complete encrypted off-cluster key backup before sealing/bootstrap. Never write plaintext private keys or delete controller keys/namespace as a recovery step. For upgrades save the inventory/backup first, use the reviewed chart version with both values files and compare key inventory after rollout. Disaster recovery restores the required original keys before reconciling ciphertext and qualifies recovery outside production.

```bash
SEALED_SECRETS_CERT=/tmp/eurotransit-sealed-secrets.pem scripts/generate-aks-sealed-secrets.sh
scripts/validate-aks-sealed-secrets.sh platform/environments/aks/secrets
just render-kind
just render-aks
```

The generator creates the eleven application ciphertexts without plaintext files, including identically valued Orders credentials scoped to both namespaces. Review and merge ciphertext before root reconciliation; [security and secrets](../platform/security-and-secrets.md) owns secret boundaries. The manually applied repository credential and its rotation are in [GitOps bootstrap](gitops.md#repository-credential).

## Acceptance and ordinary rollback

After root sync, require Healthy/Synced child applications, Ready certificates and PostgreSQL/Kafka/connectors, no Pending/OOM workloads and measured per-node headroom. Inspect actual connector tasks and Prometheus targets; resource declarations alone do not demonstrate health.

```bash
kubectl -n argocd get applications
kubectl get pods -A
kubectl get events -A --sort-by=.lastTimestamp
kubectl top nodes
kubectl top pods -A --sort-by=memory
kubectl -n eurotransit get cluster,kafka,kafkatopic,kafkaconnect,kafkaconnector
kubectl -n eurotransit get certificate,servicemonitor,ingressroute
kubectl -n keycloak get certificate
curl -fsS https://g05.cpo2026.it/realms/eurotransit/.well-known/openid-configuration
curl -fsS https://g05.cpo2026.it/api/catalog/routes
curl -i -X POST https://g05.cpo2026.it/api/orders   -H 'Content-Type: application/json' -H 'Idempotency-Key: aks-check' -d '{}'
```

Issuer must match the configured public issuer; unauthenticated Orders must return 401/403. Inventory and Payments must have no public route. For pending TLS inspect certificates, challenges/orders and the root's failed child. Keep the cert-manager [AKS webhook namespace filters](../../platform/cert-manager/values-aks.yaml) intact.

Rollback ordinary changes through a reviewed Git revert and Argo reconciliation. Application secret rotation uses replacement ciphertext; rotate the Orders value in both namespaces and recreate only its completed bootstrap Job after Argo sees the replacement. [Identity recovery](identity-recovery.md) covers the load-test client. Use [controlled maintenance](gitops.md#controlled-maintenance) for migrations and [capacity](../platform/capacity.md) for resource changes.

## PostgreSQL disk recovery

If Keycloak discovery works but token authentication fails, check database readiness before recreating the realm or clients. For `Not enough disk space`, inspect PVC capacity, WAL and slot retention. Keep an approved storage increase in Git, sync the runtime and wait for the PVC/Cluster to become Ready before retrying the failed identity Job. The storage class must support expansion; a revert cannot shrink a volume. Current size is defined by the [AKS PostgreSQL patch](../../platform/environments/aks/postgres-patch.yaml), not by an old incident's recommended number.

## Kafka storage before maintenance

AKS inherits ephemeral Kafka storage. Recreating its broker can erase records and Connect config/offset/status topics; recreated topic names do not prove preserved data. If state must survive, stop the rollout until a separate durable-storage migration or complete verified Kafka backup/restore exists. A PostgreSQL snapshot does not back up Kafka. A disposable reset needs its own authorization and post-reset checkout/connector qualification. Export fresh stopped-connector offsets before later maintenance; exports become stale once processing resumes.
