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

The sealing script supplies the client secret in both namespaces.
The Keycloak bootstrap Job creates or reconciles the confidential client named
`eurotransit-load-test`, including in an already imported realm. When its Pod
template changes, recreate only that Job after merge using the
[AKS recovery procedure](../platform/aks-keycloak-cert-manager-recovery.md).
It has a service account with the `customer` role; direct-access/password
grants are disabled.  It is not a demo-user credential and must never use
Alice’s password.

## Controlled traffic

The CronJob is permanently suspended; it is a template for a manually created,
short-lived Job rather than a scheduled load generator.

```bash
kubectl -n eurotransit create job --from=cronjob/progressive-delivery-k6 pd-k6-$(date +%s)
kubectl -n eurotransit logs -f job/<created-job-name>
```

The k6 Job uses client credentials, goes through public Traefik routes, checks
`catalog-preview` directly before checking the public Catalog route, and
verifies that offer `of-001` for `rt-to-mi-001` costs 24.90 for one seat. It
then continuously creates and polls one-seat Orders with `offerId`, a generated
future `travelDate`, and fresh `pd-k6-*` idempotency keys. Its default is two
VUs for 45 minutes. After each checkout/poll cycle, each VU waits 15 seconds,
so the resulting rate is roughly 3--8 checkouts per minute depending on the
time to terminal state. A 45-minute run can therefore create up to 360 real
Orders and Stripe Sandbox payment attempts; verify cluster capacity and Stripe
rate limits before starting it. Each VU maps its iteration to a distinct
seat/date pair from 24 seats across a 15-day block. The job refuses to wrap or
reuse a slot: a duration or rate that exceeds 360 checkouts fails explicitly.
`tok_visa` is the default Stripe Sandbox source token;
`loadTest.paymentMethodToken` can override it for a compatible test provider.
Each checkout cycle gets a fresh client-credentials token, rather than relying
on the short-lived token used for the setup prechecks.

The Inventory bootstrap hook must have run successfully recently enough to
provision the selected days; it seeds from its execution date through six
months ahead. Confirm that precondition before starting k6. The default
`loadTest.startOffsetDays: 7` uses days 7--21 after Job startup. Do not rerun
the same block: a subsequent demonstration must use a small reviewed values
change to the next non-overlapping block, for example `22`, `37`, `52`, or
`67` (the supported range is 7--76, so every 15-day block ends by day 90).

There is intentionally no reset CronJob or database cleanup procedure.
Deleting Orders, reservation rows, outbox records, idempotency state, or
Payments state by route/seat pattern is not safely attributable to this test
and would destroy audit evidence. If the selected date is unavailable, stop
the test; do not alter service databases directly. Before another Job, make a
small reviewed values change to an unused non-overlapping
`loadTest.startOffsetDays` block.

## Demonstration procedure

1. Start k6, then update the target Rollout while k6 continues generating
   checkouts. Each analysis metric has a 90-second initial delay, allowing the
   new hash to receive traffic, be scraped two or three times, and process
   terminal checkout events before its first evaluation.
2. For Catalog, update the Catalog image tag.  Verify preview health, inspect
   `catalog-preview`, then promote manually with `kubectl argo rollouts promote
   catalog -n eurotransit`.  The former revision stays available for 60 seconds;
   abort during that interval to prove rollback and confirm the public route.
3. For Orders, update only the Orders image tag.  At each 10/25/50% step,
   inspect `orders-weighted`, its AnalysisRun and k6 logs, then manually promote
   to the next pause.  Promote the final 100% pause only after the evidence is
   recorded.
4. Prove automatic abort once: temporarily make a real AnalysisTemplate
   threshold impossible (for example `p95-latency-seconds:
   len(result) > 0 && result[0] < 0`), start a new Orders revision, observe
   `Failed`/`Aborted`, then immediately restore the real threshold
   (`len(result) > 0 && result[0] < 1`) in Git and re-sync. Never leave an
   impossible guardrail committed.

Useful evidence commands:

```bash
kubectl -n eurotransit get rollout,analysisrun
kubectl -n eurotransit get traefikservice orders-weighted -o yaml
kubectl -n eurotransit describe rollout orders
kubectl -n eurotransit logs job/<k6-job>
```

Save that output with Grafana/Prometheus screenshots for 5xx rate, p95,
the canary pod's terminal checkout counters and dead-letter counter, and
Kafka lag. Before starting, verify that `/actuator/prometheus` is actually
scrapable: the ServiceMonitor alone cannot make a security-denied endpoint
observable.

## Promotion signals and guardrails

`orders-canary-guardrails` queries only the latest
`rollouts-pod-template-hash`. It requires HTTP samples (zero traffic fails),
a 5xx rate below 2%, p95 below one second, at least one terminal checkout
observed by that pod, a terminal checkout failure rate below 2%, and no
dead-letter event emitted by that pod. ServiceMonitors retain the rollout hash
as a Prometheus target label, so stable and canary measurements are distinct.
Every Prometheus condition explicitly evaluates the returned vector
(`len(result) > 0 && result[0] ...`). The HTTP error and counter queries use
`or vector(0)` where an absent series represents zero; p95 deliberately does
not, so an absent or non-numeric latency result fails safely.

The k6 threshold requires all checks to pass and aborts the Job on the first
failed check. A failed k6 Job is a failed demonstration input: do not promote
the Rollout; inspect the Job logs and resolve the cause before restarting with
an unused date block.

The terminal and dead-letter counters are emitted by the pod that processes a
Kafka record. Traefik's HTTP weight does **not** select that Kafka consumer: a
checkout accepted by the HTTP canary can be completed or failed by another pod
in the consumer group. The guardrails therefore prove the health of the
canary pod when it processes records; they do not claim end-to-end attribution
of every weighted HTTP request. With `failureLimit: 0`, zero terminal samples
make the AnalysisRun fail and the canary abort; continuous k6 checkout traffic
is required before and throughout each analysis window. Operators must inspect the cross-pod business metrics,
Kafka assignment/lag, and the k6 order outcomes before manually promoting.
The former database-wide `orders_pipeline_inflight` and
`orders_reconciliation_open` gauges are deliberately not rollout gates:
filtering their replicated DB-wide values by a pod hash neither attributes an
incident to that revision nor avoids replica multiplication.

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
