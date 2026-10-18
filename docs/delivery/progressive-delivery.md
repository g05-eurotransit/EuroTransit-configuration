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
for the actual stable/canary overlap plus the 256Mi test Job. Follow the
[AKS resource preflight](../platform/aks-resource-budgets.md) and
[memory reduction runbook](../platform/aks-memory-reduction-runbook.md): inspect
per-node allocatable memory, requests and Pending/OOM events; aggregate headroom
does not prove that another pod fits. Coordinate the cluster window with #46 to #49.  Do not overlap the Catalog
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

1. Verify a compatible Orders image and fresh fixtures (below), start the #46
   traffic harness, then update the target Rollout while traffic continues.
   Orders waits five minutes before the first evaluation, then evaluates twice
   60 seconds apart over a rolling five-minute evidence window. Catalog retains
   its 90-second delay. Insufficient evidence aborts; gather more traffic or
   tune the documented observation policy before retrying, never bypass a gate.
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

Save that output with Grafana/Prometheus screenshots for absolute 5xx count, p95,
the canary pod's terminal checkout counters and exhausted-delivery counter, and
Kafka lag. Before starting, verify that `/actuator/prometheus` is actually
scrapable: the ServiceMonitor alone cannot make a security-denied endpoint
observable.

## Promotion signals and guardrails

`orders-canary-guardrails` scopes evidence to the latest rollout hash. The
`progressiveDelivery.analysis.orders` values declare a **controlled demo** policy:

| Gate | Default | Scope |
| --- | --- | --- |
| HTTP evidence | at least 4 requests | increase over 5 minutes |
| Terminal evidence | at least 4 confirmed checkouts | increase over 5 minutes, Kafka processing pod |
| HTTP errors | zero 5xx | current canary process lifetime |
| Checkout failures | zero, every reason | current canary process lifetime |
| Exhausted deliveries | zero | emitter process lifetime, all topics/classes |
| Latency | p95 below 1 second | histogram rate over 5 minutes |
| Observability | all scrape targets up; required counters present | every canary instance |
| Continuity | no observed counter reset/process change; process age at least 300s | rolling window/current process |

HTTP evidence excludes actuator endpoints, so scrape/health traffic cannot satisfy
the request minimum. `increase()` produces extrapolated estimates rather than
exact event counts; record raw counters and k6 outcomes alongside the estimates.

This replaces percentage claims at tiny volumes. At 3 to 8 checkouts/minute,
one of three Kafka partitions can yield roughly 5 to 13 terminal outcomes in five
minutes; requiring four confirmations fits that illustrative exposure and the
360-slot fixture. Assignment and actual outcomes must be checked; the estimate
is not a guarantee. Three analyses take about 18 minutes plus manual pauses,
within the default 45-minute job. Use the #46 harness measurements to tune the
window/delay/sample requirement together. A job timeout is not approval.

Zero failure is intentional for the existing success-only fixture: unused
seat/date pairs and `tok_visa` should confirm. A payment decline or inventory
refusal is an expected business outcome for some inputs, but invalidates this
promotion experiment and must stop it. Inspect `reason` and k6 logs to separate
fixture failure from application regression. Do not exclude business labels
from the query: a regression can cause those same refusals. Run intentional
negative scenarios separately with an explicit expected-result contract; they
are not evidence that this success fixture should promote. This is not a
production 2% checkout/HTTP SLO and does not replace application SLO alerts.

HTTP series are lazily created on their first request. Lifetime counts expose a
first 5xx scraped at 1, which `increase()` alone can miss. Exhaustion and failure
counts also preserve the first observed error and reject errors from earlier
steps on the same processes. Counters are deduplicated by instance and their
semantic labels when both Services discover the same endpoint. A reset can
erase lifetime history: the continuity gate rejects observed resets and young
processes, but cannot reconstruct an error lost before any scrape, or a previous
process that disappeared before observation. Record pod UIDs/restarts at each
step and abort/retry on a restart or replacement; never present those runs as
clean lifetime evidence. No Prometheus gate can prove events never scraped.

The coverage query uses `up` targets from Services `orders`/`orders-canary`, with
the rollout hash retained by the ServiceMonitor. Every discovered instance must
export both completed result series, a failed-reason counter, the six registered
exhaustion topic/class series and process start time; all targets must be up.
An empty target set fails too. This deliberately fails on old images or missing
metrics; `or vector(0)` in error queries cannot waive the independent coverage
gate. Validate target labels and metric coverage in the actual cluster first.

**Image prerequisite:** delivery remains disabled in the values files. Do not
enable it on the pinned `98bedf2` image. Deploy a verified artifact containing
application [#127](https://github.com/g05-eurotransit/EuroTransit-application/pull/127)
and [#128](https://github.com/g05-eurotransit/EuroTransit-application/pull/128),
verify its digest/provenance, and inspect its scraped series. Source merges
`4389f4f` and `3f04bcb` on application `dev` establish code availability, not
registry artifact availability. #127 emits `orders_events_exhausted_total`
from the retry-exhausting pod; `orders_events_dlt_total` identifies the DLT
reader and is not a rollout attribution signal. #128 registers checkout series
at zero. Application contracts and failure taxonomy remain in the
[application source](https://github.com/g05-eurotransit/EuroTransit-application/tree/dev/orders/src/main/kotlin/it/polito/cpo/service).

### Kafka exposure and evidence

HTTP weights do not determine Kafka exposure. Stable and canary join the same
consumer group. With two consumers and three partitions a canary can own one
or two partitions (roughly 33% or 67% of records for balanced partition traffic),
regardless of a 10% HTTP weight; replicas, skew and rebalances can change this.
A checkout accepted by one HTTP pod can finish on another Kafka consumer.
Terminal metrics prove the processing revision's behavior, not end-to-end
attribution of weighted requests. Database-wide pipeline/reconciliation gauges
remain diagnostic, not version-specific promotion gates.

For each 10/25/50% step, record the image digest, rollout hash, pod UIDs and
restart counts; actual HTTP weight and HTTP samples; confirmed/failed outcomes
by reason and pod; lifetime 5xx/exhaustion counts; and the consumer group members,
assigned partitions for `order-placed` and `refund-requested`, lag and any
rebalance. Collect assignments using the Kafka CLI `kafka-consumer-groups.sh
--bootstrap-server <internal-bootstrap> --describe --group <actual-orders-group>
--members --verbose`, with the cluster's configured authentication, or equivalent
broker/operator evidence. Resolve the group ID from the deployed configuration;
do not infer assignment from pod count or HTTP weights.

The k6 Job must remain healthy. A failed check, unavailable fresh fixture, absent
metric, insufficient samples, unobserved canary assignment or restart prevents
manual promotion. Coordinate #46 for healthy and controlled regression runs;
#49 collects the final promotion/abort/recovery evidence. The impossible-threshold
exercise above proves controller wiring only; also show a genuine controlled
error causes abort without editing the gate. Distributed tracing (#38) is a
separate prerequisite for trace evidence and is not implemented by these gates.

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
