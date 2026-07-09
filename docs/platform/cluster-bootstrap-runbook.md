# Cluster Bootstrap Runbook

This runbook describes the steps to execute after the platform YAML and Helm templates exist in this repository. It is scoped to the EuroTransit Marketplace cluster proof: Traefik, Argo CD, Sealed Secrets, cert-manager, CloudNativePG, Strimzi, kube-prometheus-stack, Chaos Mesh, and the EuroTransit application chart.

The lab PDFs under `docs/labs` are treated as setup references for local Kubernetes, Helm, Argo CD, sealed secrets, and observability workflows. Product naming and operational proof remain EuroTransit-specific.

## Lab Alignment

- Lab02 maps to Helm-rendered Deployments, Services, probes, runtime config, and secret injection.
- Lab03 maps to Traefik as the single public entrypoint, internal ClusterIP services, path routing, and cert-manager TLS.
- Lab04 maps to SealedSecrets, Argo CD Applications, GitOps reconciliation, private repository credentials, and Argo CD UI exposure through Traefik.
- Lab05 maps to kube-prometheus-stack, ServiceMonitor, PrometheusRule, Grafana/Alertmanager access, and k6-driven proof.

## Repository And Worktree

Use the dedicated configuration worktree for this change:

```bash
cd /Users/matteo/IdeaProjects/EuroTransit-configuration-cluster-setup
git status --short --branch
```

The sibling application repository remains the source of service behavior, API contracts, and money-path design:

```bash
cd /Users/matteo/IdeaProjects/EuroTransit-application
```

## Prerequisites

Install or verify:

```bash
docker version
kind version
kubectl version --client
helm version
argocd version --client
kubeseal --version
```

Required cluster assumptions:

- Kubernetes context points to the local/proof cluster.
- The configuration repository branch is pushed before Argo CD syncs from Git.
- The application images referenced by `charts/eurotransit/values.yaml` are available in the selected registry or loaded into kind.
- No plaintext production or sandbox credentials are committed.

Environment selection:

- Keycloak kind/local uses `platform/keycloak/values.yaml` plus `platform/keycloak/values-kind.yaml`.
- Keycloak proof/demo uses `platform/keycloak/values.yaml` plus `platform/keycloak/values-proof.yaml`.
- Keycloak production-style uses `platform/keycloak/values.yaml` plus `platform/keycloak/values-production.yaml`.
- EuroTransit application kind/local uses `charts/eurotransit/values.yaml` plus `charts/eurotransit/values-kind.yaml`.
- EuroTransit application proof/demo uses `charts/eurotransit/values.yaml` plus `charts/eurotransit/values-proof.yaml`.
- EuroTransit application production-style uses `charts/eurotransit/values.yaml` plus `charts/eurotransit/values-production.yaml`.
- Change the second Keycloak and EuroTransit application value files in `platform/argocd/platform-applications.yaml` when moving environments.

## 1. Create Or Select The Cluster

For a local proof cluster, create kind with ports mapped for Traefik:

```bash
kind create cluster --name eurotransit --config platform/kind/kind-config.yaml
kubectl cluster-info --context kind-eurotransit
```

The control-plane node maps host ports 80 and 443 to Traefik for local proof.

## 2. Install Argo CD Bootstrap

Argo CD cannot reconcile itself before its CRDs exist, so install it once with Helm:

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  -f platform/argocd/values.yaml
```

Wait for Argo CD:

```bash
kubectl -n argocd rollout status deploy/argocd-server
kubectl -n argocd rollout status statefulset/argocd-application-controller
```

Apply the EuroTransit Argo CD project and app-of-apps definitions:

```bash
kubectl apply -k platform/argocd
```

For branch testing before merge, update `targetRevision` values in `platform/argocd/platform-applications.yaml` from `main` to the pushed branch, then revert before merging.

## 3. Verify Platform Controller Sync

Check the controller Applications:

```bash
argocd app list
argocd app sync traefik
argocd app sync cert-manager
argocd app sync sealed-secrets
argocd app sync strimzi
argocd app sync cloudnativepg
argocd app sync kube-prometheus-stack
argocd app sync chaos-mesh
argocd app sync keycloak
```

Confirm the CRDs exist before syncing runtime resources:

```bash
kubectl get crd ingressroutes.traefik.io middlewares.traefik.io
kubectl get crd certificates.cert-manager.io clusterissuers.cert-manager.io
kubectl get crd sealedsecrets.bitnami.com
kubectl get crd clusters.postgresql.cnpg.io
kubectl get crd kafkas.kafka.strimzi.io kafkatopics.kafka.strimzi.io
kubectl get crd servicemonitors.monitoring.coreos.com prometheusrules.monitoring.coreos.com
```

## 4. Create Sealed Secrets

Fetch the controller certificate:

```bash
kubeseal \
  --controller-name sealed-secrets-controller \
  --controller-namespace sealed-secrets \
  --fetch-cert > /tmp/eurotransit-sealed-secrets.pem
```

Create local Secret manifests and seal them. Example for Orders database credentials:

```bash
kubectl -n eurotransit create secret generic orders-db-credentials \
  --from-literal=username=orders \
  --from-literal=password='REPLACE_LOCALLY' \
  --dry-run=client -o yaml \
  | kubeseal --cert /tmp/eurotransit-sealed-secrets.pem \
  --format yaml > platform/cloudnativepg/orders-db-credentials.sealedsecret.yaml
```

Repeat for:

- `inventory-db-credentials` with username `inventory`;
- `payments-db-credentials` with username `payments`;
- `payments-provider-credentials`;
- `keycloak-admin-credentials` in namespace `keycloak`;
- `keycloak-postgresql-credentials` in namespace `keycloak` for kind/local;
- `keycloak-external-db-credentials` in namespace `keycloak` for proof/production;
- `keycloak-client-settings`;
- `grafana-admin-credentials` in namespace `monitoring`;
- `eurotransit-configuration-repo` in namespace `argocd` if the configuration repository is private.

Use the templates under:

- `platform/cloudnativepg/templates/`;
- `platform/sealed-secrets/templates/`;
- `platform/kube-prometheus-stack/templates/`;
- `platform/argocd/templates/`;
- `platform/keycloak/templates/`.

Do not commit unsealed Secret manifests.

## 5. Sync Runtime Resources

After SealedSecrets are committed and pushed:

```bash
argocd app sync eurotransit-platform-runtime
kubectl get clusterissuer eurotransit-selfsigned
kubectl -n eurotransit get certificate
kubectl -n argocd get certificate
kubectl -n eurotransit get cluster.postgresql.cnpg.io
kubectl -n eurotransit get kafka,kafkatopic
kubectl -n eurotransit get deploy inventory-outbox-connect
kubectl -n eurotransit get job inventory-outbox-connector-register
kubectl -n keycloak get pods,svc,ingress
```

Expected runtime resources:

- `eurotransit-local-tls` certificate for Traefik TLS;
- `eurotransit-postgres` CloudNativePG cluster;
- `orders_db`, `inventory_db`, and `payments_db` logical databases with separate service credentials;
- `eurotransit-kafka` Strimzi cluster;
- `keycloak` deployment, service, ingress, and imported `eurotransit` realm;
- money-path Kafka topics, Inventory outbox topics, Kafka Connect internal topics, and dead-letter topic;
- `inventory-outbox-connect` Debezium Connect deployment and connector registration job for `inventory.outbox_events`;
- Prometheus rules for checkout symptoms.

## 6. Sync EuroTransit Application

Build or load application images first. Then sync:

```bash
argocd app sync eurotransit-marketplace
kubectl -n eurotransit rollout status deploy/catalog
kubectl -n eurotransit rollout status deploy/orders
kubectl -n eurotransit rollout status deploy/inventory
kubectl -n eurotransit rollout status deploy/payments
kubectl -n eurotransit rollout status deploy/notifications
```

Check public routing:

```bash
kubectl -n eurotransit get ingressroute
kubectl -n argocd get ingressroute
kubectl -n eurotransit get networkpolicy
kubectl -n eurotransit get servicemonitor
```

Only these route groups should be public through Traefik:

- `/api/catalog`;
- `/api/orders`;
- `/api/notifications` when the customer notification API is enabled.

Inventory and Payments must stay internal-only.

## 7. Local DNS And Access

For local proof, map the host:

```bash
sudo sh -c 'echo "127.0.0.1 eurotransit.local argocd.eurotransit.local keycloak.eurotransit.local" >> /etc/hosts'
```

If the kind cluster does not support LoadBalancer directly, use port-forwarding:

```bash
kubectl -n traefik port-forward svc/traefik 8443:443
```

Then test:

```bash
curl -k https://argocd.eurotransit.local
curl -k https://keycloak.eurotransit.local/realms/eurotransit/.well-known/openid-configuration
curl -k https://eurotransit.local/api/catalog/routes
curl -k -X POST https://eurotransit.local/api/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: local-auth-check" \
  -d "{}"
```

The Orders request without a valid JWT should fail at the configured authentication boundary or in the Orders service.

## 8. Optional Chaos Mesh Latency Experiment

Chaos Mesh is optional for the lab path. Use it only after the normal application, monitoring, and checkout path are healthy.

The provided experiment adds 800 ms latency, plus 100 ms jitter, from Orders pods to Payments pods for 5 minutes. It is intentionally not included in the base platform kustomization, so Argo CD does not apply it during normal sync.

Start baseline traffic first, then apply the experiment:

```bash
kubectl -n chaos-mesh get pods
kubectl apply -k platform/chaos-mesh/experiments
kubectl -n eurotransit get networkchaos
```

Observe during the 5-minute window:

```bash
kubectl -n eurotransit describe networkchaos orders-to-payments-latency
kubectl -n eurotransit logs deploy/orders --tail=100
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090
```

What this should prove:

- Orders latency increases when Payments is slow.
- Orders timeout, retry, and circuit-breaker behavior remains bounded.
- Payment idempotency prevents duplicate authorization effects under retries.
- Checkout latency and payment dependency symptoms are visible in metrics or logs.

Clean up explicitly:

```bash
kubectl delete -k platform/chaos-mesh/experiments
kubectl -n eurotransit get networkchaos
```

For the simplest lab-style failure test, deleting one pod is still enough:

```bash
kubectl delete pod -n eurotransit -l app=orders
kubectl -n eurotransit rollout status deploy/orders
```

## 9. Operational Proof Checklist

Run and capture evidence for:

- Argo CD Applications healthy and synced.
- Argo CD UI is reachable through Traefik at `argocd.eurotransit.local`.
- Keycloak is reachable through Traefik and exposes the `eurotransit` realm discovery document.
- Catalog route reachable through Traefik.
- Orders checkout rejects unauthenticated traffic.
- Inventory and Payments have no IngressRoute and no external Service.
- SealedSecrets produce Kubernetes Secrets and no plaintext secret is committed.
- CloudNativePG exposes separate credentials for Orders, Inventory, and Payments.
- Strimzi topics exist for order, inventory, payment, notification, Inventory outbox routed events, Kafka Connect internal state, and dead-letter events.
- Prometheus discovers EuroTransit ServiceMonitors.
- Checkout alerts are loaded as PrometheusRule objects.
- Chaos Mesh is installed and the optional Orders-to-Payments latency experiment can be applied and removed cleanly.

## 10. Known Follow-Ups

- Compare `platform/kind/kind-config.yaml` with lab-specific cluster notes if port mappings or node counts need to differ.
- Switch Keycloak from `values-kind.yaml` to `values-proof.yaml` or `values-production.yaml` after hostnames, TLS issuer, and sealed external DB credentials are ready.
- Switch EuroTransit from `charts/eurotransit/values-kind.yaml` to `charts/eurotransit/values-proof.yaml` or `charts/eurotransit/values-production.yaml` at the same time as Keycloak.
- Replace `forwardAuth.enabled=false` with the selected gateway auth component when it exists.
- Pin chart versions again immediately before first cluster sync.
- Add Grafana dashboards for checkout RED, Kafka lag, inventory correctness, and payment safety.
- Add incident notes and reliability reports for each executed Chaos Mesh experiment.

