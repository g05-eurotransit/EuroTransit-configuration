# Progressive Delivery

EuroTransit Marketplace uses Argo Rollouts for two complementary delivery strategies:

- Catalog is Blue/Green: `catalog` stays the active Service and
  `catalog-preview` is validated before a manual promotion.
- Orders is a metric-gated canary: `orders` remains stable, `orders-canary`
  receives 10%, 25%, 50%, then 100% through the TraefikService
  `orders-weighted`.

The first GitOps migration is intentionally non-disruptive.  Both Rollout
objects use `workloadRef` to adopt the existing Deployments, so old and new
pods can coexist while controller ownership is proven.  Do Catalog and Orders
separately.  Only after that proof, make a dedicated reviewed migration that
copies the existing pod template into the now-independent Rollout and removes
the corresponding Deployment.  Do not delete a Deployment before its Rollout
has reported Healthy; the current chart deliberately keeps the safe
`workloadRef` phase enabled until that review is made.

## Prerequisites

Argo CD syncs the `argo-rollouts` Helm Application (chart 2.41.1) in wave 29,
before `eurotransit-marketplace` in wave 30.  Before a demonstration verify:

```bash
kubectl -n argo-rollouts get deploy argo-rollouts
kubectl -n eurotransit get kafkaConnect,kafkatopic
kubectl -n eurotransit get kafkaconnector
kubectl -n eurotransit get pods -l strimzi.io/cluster=eurotransit-kafka
kubectl -n eurotransit get deploy orders catalog
```

Check that the Strimzi Entity Operator, actual Kafka topics and the Debezium
Connectors are healthy, confirm one baseline checkout, and reserve capacity
for one extra service pod plus the 256Mi test Job.  Do not overlap the Catalog
and Orders exercises on the small demo cluster.

For AKS, generate the two namespace-bound ciphertexts for
`eurotransit-load-test-credentials` before syncing the keycloak bootstrap Job:

```bash
SEALED_SECRETS_CERT=/tmp/eurotransit-sealed-secrets.pem \
  scripts/generate-aks-sealed-secrets.sh
```

This creates a confidential Keycloak client named `eurotransit-load-test`.
It has a service account with only the `customer` role; direct-access/password
grants are disabled.  It is not a demo-user credential and must never use
Alice’s password.

## Controlled traffic and reset

Both CronJobs are permanently suspended; they are templates for manually
created, short-lived Jobs rather than scheduled load generators.

```bash
kubectl -n eurotransit create job --from=cronjob/progressive-delivery-k6 pd-k6-$(date +%s)
kubectl -n eurotransit logs -f job/<created-job-name>
```

The k6 Job uses client credentials, goes through public Traefik routes, checks
`catalog-preview` directly before checking the public Catalog route, creates
only three real Orders with dedicated seats, then repeatedly reads those
Orders.  Every checkout has a fresh `pd-k6-*` idempotency key.

The reset template never runs automatically and refuses to operate without
the exact confirmation value.  Create it as a Job, then set the environment
variable in its copied manifest to `RESET_EUROTRANSIT_DEMO` before applying.
It resets only the three dedicated seats and their related test Orders,
outbox/idempotency state and reconciliation state; it must not be used during
another checkout or connector exercise.

## Demonstration procedure

1. Start k6 and wait for Prometheus to scrape both stable and canary pod hashes.
2. For Catalog, update the Catalog image tag.  Verify preview health, inspect
   `catalog-preview`, then promote manually with `kubectl argo rollouts promote
   catalog -n eurotransit`.  The former revision stays available for 60 seconds;
   abort during that interval to prove rollback and confirm the public route.
3. For Orders, update only the Orders image tag.  At each 10/25/50% step,
   inspect `orders-weighted`, its AnalysisRun and k6 logs, then manually promote
   to the next pause.  Promote the final 100% pause only after the evidence is
   recorded.
4. Prove automatic abort once: temporarily make a real AnalysisTemplate
   threshold impossible (for example `p95-latency-seconds: result < 0`), start
   a new Orders revision, observe `Failed`/`Aborted`, then immediately restore
   the real threshold (`result < 1`) in Git and re-sync.  Never leave an
   impossible guardrail committed.

Useful evidence commands:

```bash
kubectl -n eurotransit get rollout,analysisrun
kubectl -n eurotransit get traefikservice orders-weighted -o yaml
kubectl -n eurotransit describe rollout orders
kubectl -n eurotransit logs job/<k6-job>
```

Save that output with Grafana/Prometheus screenshots for 5xx rate, p95,
Kafka lag, non-terminal Orders and open reconciliation incidents.

## Promotion signals and guardrails

`orders-canary-guardrails` queries only the latest
`rollouts-pod-template-hash`.  It requires samples (zero traffic fails), a
5xx rate below 2%, p95 below one second, fewer than five non-terminal Orders,
and no open reconciliation incident.  ServiceMonitors retain the rollout hash
as a Prometheus target label, so stable and canary measurements are distinct.

## Strategies Not Used on the Critical Path

EuroTransit also documents where rolling and all-at-once delivery would fit, because they are valid delivery strategies but weaker choices for the checkout money path.

- **Rolling deployment:** Useful for low-risk stateless service updates, routine patching, or internal components where gradual pod replacement is enough. It is not the primary Orders strategy because it does not provide an explicit traffic percentage, metric-gated promotion, or simple abort decision for the critical checkout path.
- **All-at-once deployment:** Useful only for very low-risk changes, local/dev environments, or emergency rollback to a previously validated version. It is not used for Orders because the blast radius is immediate and there is no progressive exposure window.

Orders therefore uses canary for metric-gated exposure. Catalog uses blue/green because it is stateless, read-heavy, and easy to switch or roll back as a whole.

## Promotion Signals

Promotion should depend on observable behavior:

- checkout success rate;
- request latency;
- HTTP 5xx rate;
- circuit breaker state for critical dependencies;
- relevant application logs and traces.

## Abort Criteria

- Checkout success-rate burn exceeds the threshold defined in the canonical application SLO document.
- p95 checkout latency breaches the SLO during the canary window.
- Orders payment or inventory circuit breakers remain open beyond the configured alert window.
- Distributed traces show the new version adds unexplained latency or error concentration.
