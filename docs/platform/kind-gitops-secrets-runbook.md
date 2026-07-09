# kind GitOps And Sealed Secrets Runbook

This runbook describes the current local kind GitOps path for EuroTransit Marketplace runtime secrets. It complements `docs/platform/cluster-bootstrap-runbook.md` with the concrete steps used for the database credentials on the `feature/cluster-platform-bootstrap` branch.

## Scope

Use this document when:

- Argo CD is already installed in the kind cluster.
- The Sealed Secrets controller is installed and healthy.
- The `eurotransit-platform-runtime` Argo CD Application reconciles `platform/`.
- Runtime database credentials must be managed by GitOps, not by manual `kubectl create secret`.

Do not commit unsealed Kubernetes `Secret` manifests. Commit only `SealedSecret` manifests.

## Repositories

The active worktree for this branch is:

```bash
cd /Users/matteo/IdeaProjects/EuroTransit-configuration-cluster-setup
```

The remote is the same EuroTransit configuration repository:

```text
git@github.com:carmelo-gulino/EuroTransit-configuration.git
```

The sibling `EuroTransit-configuration` worktree may be on a different branch and may not contain the platform manifests. Before editing, check the branch and the Argo CD live source:

```bash
git status --short --branch

kubectl -n argocd get application eurotransit-platform-runtime \
  -o jsonpath='{.spec.source.repoURL}{"\n"}{.spec.source.targetRevision}{"\n"}{.spec.source.path}{"\n"}'
```

For the current kind setup, the live Argo CD Application has been reconciled from:

```text
repo: https://github.com/carmelo-gulino/EuroTransit-configuration
branch: feature/cluster-platform-bootstrap
path: platform
```

## Secret Strategy

For local kind, Orders, Inventory, and Payments use separate database credentials:

```text
orders-db-credentials
inventory-db-credentials
payments-db-credentials
```

They are Kubernetes secrets of type:

```text
kubernetes.io/basic-auth
```

Each secret contains:

```text
username
password
```

CloudNativePG references these names from `platform/cloudnativepg/postgres-cluster.yaml`.

For the local kind environment, it is acceptable to use a shared disposable password while validating the platform. For proof or production-style environments, use distinct generated passwords and follow rotation expectations.

## Generate Sealed Database Credentials

Fetch the Sealed Secrets public certificate from the cluster:

```bash
kubeseal \
  --controller-name sealed-secrets-controller \
  --controller-namespace sealed-secrets \
  --fetch-cert > /tmp/eurotransit-sealed-secrets.pem
```

Generate the database credential SealedSecrets. Set the password in the shell instead of writing it into a plain YAML file:

```bash
cd /Users/matteo/IdeaProjects/EuroTransit-configuration-cluster-setup

KIND_DB_PASSWORD='changeme-kind'

for service in orders inventory payments; do
  kubectl -n eurotransit create secret generic "${service}-db-credentials" \
    --type=kubernetes.io/basic-auth \
    --from-literal=username="${service}" \
    --from-literal=password="${KIND_DB_PASSWORD}" \
    --dry-run=client -o yaml \
  | kubeseal \
      --cert /tmp/eurotransit-sealed-secrets.pem \
      --format yaml \
  > "platform/cloudnativepg/${service}-db-credentials.sealedsecret.yaml"
done

unset KIND_DB_PASSWORD
```

Expected files:

```text
platform/cloudnativepg/orders-db-credentials.sealedsecret.yaml
platform/cloudnativepg/inventory-db-credentials.sealedsecret.yaml
platform/cloudnativepg/payments-db-credentials.sealedsecret.yaml
```

## Include The SealedSecrets In Kustomize

Argo CD reconciles `platform/` as a Kustomize tree. A YAML file placed in `platform/cloudnativepg/` is ignored unless `platform/cloudnativepg/kustomization.yaml` references it.

Expected `platform/cloudnativepg/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - postgres-cluster.yaml
  - orders-db-credentials.sealedsecret.yaml
  - inventory-db-credentials.sealedsecret.yaml
  - payments-db-credentials.sealedsecret.yaml
```

Render and dry-run before committing:

```bash
kubectl kustomize platform/cloudnativepg
kubectl apply --dry-run=client -k platform/cloudnativepg
```

The dry-run should show the three `sealedsecret.bitnami.com/*` resources plus the CloudNativePG `Cluster`.

## Commit And Push

Commit the SealedSecrets and the Kustomize resource list:

```bash
git status --short

git add platform/cloudnativepg/kustomization.yaml \
  platform/cloudnativepg/orders-db-credentials.sealedsecret.yaml \
  platform/cloudnativepg/inventory-db-credentials.sealedsecret.yaml \
  platform/cloudnativepg/payments-db-credentials.sealedsecret.yaml

git commit -m "Add sealed database credentials for kind"
git push origin feature/cluster-platform-bootstrap
```

The current branch contains commit:

```text
44f093d Add sealed database credentials for kind
```

## Let Argo CD Reconcile

If the Argo CD CLI is installed, sync the runtime Application:

```bash
argocd app sync eurotransit-platform-runtime
```

If the Argo CD CLI is not installed, request a hard refresh through Kubernetes:

```bash
kubectl -n argocd annotate application eurotransit-platform-runtime \
  argocd.argoproj.io/refresh=hard \
  --overwrite
```

Check the Application status:

```bash
kubectl -n argocd get application eurotransit-platform-runtime \
  -o jsonpath='{.status.sync.revision}{"\n"}{.status.sync.status}{"\n"}{.status.health.status}{"\n"}'
```

The revision should move to the pushed commit hash.

## Verify Secret Creation

Verify the `SealedSecret` resources:

```bash
kubectl -n eurotransit get sealedsecret \
  orders-db-credentials \
  inventory-db-credentials \
  payments-db-credentials
```

Verify that the Sealed Secrets controller decrypted them into normal Kubernetes `Secret` resources:

```bash
kubectl -n eurotransit get secret \
  orders-db-credentials \
  inventory-db-credentials \
  payments-db-credentials
```

Expected type:

```text
kubernetes.io/basic-auth
```

At this point the GitOps secret path is working. If `eurotransit-platform-runtime` still reports `OutOfSync` or `Progressing`, inspect the remaining resource:

```bash
kubectl -n argocd get application eurotransit-platform-runtime \
  -o jsonpath='{range .status.resources[?(@.status!="Synced")]}{.kind}{" "}{.namespace}{"/"}{.name}{" status="}{.status}{" health="}{.health.status}{"\n"}{end}'
```

In the current cluster, after the database SealedSecrets were created, the remaining out-of-sync resource was the CloudNativePG `Cluster` named `eurotransit-postgres`.

## Application Image Follow-Up

The EuroTransit application chart references local-style images such as:

```text
eurotransit/catalog:latest
eurotransit/orders:latest
eurotransit/inventory:latest
eurotransit/payments:latest
eurotransit/notifications:latest
```

For kind, build and load them into the cluster from the sibling application repository:

```bash
cd /Users/matteo/IdeaProjects/EuroTransit-application

./gradlew --no-daemon build

for service in catalog orders inventory payments notifications; do
  docker build --build-arg "SERVICE=$service" -t "eurotransit/$service:latest" .
  kind load docker-image "eurotransit/$service:latest" --name eurotransit
done

kubectl -n eurotransit rollout restart \
  deploy/catalog \
  deploy/orders \
  deploy/inventory \
  deploy/payments \
  deploy/notifications
```

Then check:

```bash
kubectl -n eurotransit get pods
kubectl -n argocd get application eurotransit-marketplace
```

## Next Runtime Gap

The database secrets now exist, but application Deployments must still inject the correct environment variables. The services read:

```text
DB_HOST
DB_PORT
DB_NAME
DB_USER
DB_PASSWORD
SPRING_KAFKA_BOOTSTRAP_SERVERS
SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_ISSUER_URI
SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_JWK_SET_URI
```

The next configuration task is to wire those values into the Helm chart under `charts/eurotransit/templates/*-deployment.yaml`, using `secretKeyRef` for `DB_USER` and `DB_PASSWORD`.

## Troubleshooting

If `kubectl` cannot connect to the kind API server, confirm the context:

```bash
kubectl config current-context
kubectl get nodes --request-timeout=5s
```

If the cluster is running through a Docker SSH context, sandboxed shells may fail to query Docker or Kubernetes. Run the command from a normal terminal or grant the required local access.

If `argocd` is not installed locally, use the `kubectl annotate application ... refresh=hard` command above.

If `SealedSecret` exists but `Secret` does not, check the controller:

```bash
kubectl -n sealed-secrets get pods,svc
kubectl -n eurotransit describe sealedsecret orders-db-credentials
```

If an application pod still fails after image pulls and secrets are fixed, check its environment wiring and logs:

```bash
kubectl -n eurotransit describe pod <pod-name>
kubectl -n eurotransit logs <pod-name>
```
