# Run bounded traffic and collect evidence

Start with [testing and tooling](../verification/testing-tooling.md) for the workflow diagram, tool responsibilities and experiment map.

This repository owns the complete operational harness in [`load-tests`](../../load-tests):
k6 scenarios, finite fixtures, correctness assertions, image publication, launchers,
capacity checks, fixture ownership, operational evidence, and reports. Application
unit/integration tests and service instrumentation remain in the application repository.
This procedure uses existing cluster capacity and does not install a resident fault controller.

Optional checkout-only ingress refusal and its separate live-proof procedure
are described in [checkout-load-shedding.md](load-shedding.md).

## Workstation baseline

Prefer the immutable harness container on a workstation, outside AKS. The image
is built by the configuration CI; substitute its published commit SHA or digest.
Install Python 3, Docker and kubectl; use an explicitly selected AKS context.
Supply the existing technical client secret through the process environment,
using a local secret manager or hidden interactive prompt. Never paste it into a
command, tracked file, issue, artifact or console log. Do not enable shell tracing.

```bash
read -rs CLIENT_SECRET
export CLIENT_SECRET
python3 scripts/reliability-runner.py run \
  --context eurotransit --mode workstation \
  --image eurotransitregistry.azurecr.io/eurotransit/load-tests:COMMIT_SHA \
  --fixtures /absolute/path/fixtures.json --output /absolute/path/results-new-run \
  --public-url https://g05.cpo2026.it \
  --issuer https://g05.cpo2026.it/realms/eurotransit \
  --max-attempts 20 --max-vus 1
unset CLIENT_SECRET
```

The output directory must not exist. Instead of `--image`, `--harness` can identify
Configuration `load-tests/run.py` on a workstation with native k6. Docker mounts
fixture input read-only and runs with the operator's UID to preserve owner-only
output permissions. Tokens and credentials are passed by environment name, not
in argv. A Docker administrator can inspect container environment: use only a
trusted workstation. Public TLS verification is enabled by the configuration harness.

Fixture format is the harness contract: version 1 and a `fixtures` array
with `routeId`, `offerId`, `travelDate`, `seatId`, `unitPrice`. Select explicit unused
sample seat/date combinations within the Inventory bootstrap horizon. Preflight
queries only those slots and requires AVAILABLE. Persistent ConfigMaps claim each
slot atomically; collisions abort. Claiming every supplied slot conservatively
reserves the fixture set even if a run ends early. Existing bookings outside this
tool also matter; claims are attribution/coordination, not a new business reservation.
There is no cleanup of service databases, payment state or outbox rows.

A namespace ConfigMap lock permits one operator run at a time. Completed runs
release the lock; interrupted/ambiguous runs retain it and fixture claims. For a
workstation lock, verify the process/container is stopped before manually removing
`eurotransit-load-test-lock`. For Job locks, use the `recover` subcommand; it refuses
while the associated Job is active. Never remove persistent `et-fixture-*` claims
just to rerun a consumed fixture. Manually started tools bypass this coordination.

## Capacity and optional cluster Job

Preflight reads nodes, all pod requests, and metrics-server data. Samples older
than 60 seconds, missing metrics, non-Ready/MemoryPressure nodes, live unhealthy
containers and OOM kills in the previous ten minutes fail closed. Workstation
mode may run only a sequential baseline of at most 20 attempts when measured
usage exceeds allocatable. It declares saturation and prohibits fault experiments.
These are tool admission bounds, not SLOs or a capacity certification.

Current [baseline](../verification/aks/checkout.md), [contention](../verification/aks/checkout.md), [request replay](../verification/aks/checkout.md) and [ramp/spike](../verification/aks/checkout.md) observations are indexed in [verification results](../verification/README.md). Each report retains its own financial-audit and telemetry scope.

The optional Job requires a schedulable, untainted node with 50m/128Mi available
requests and measured memory + 256Mi runner limit + 128Mi safety margin within
allocatable. `--extra-memory-mib` only increases that bound: experiments must
include proxy peak and any extra Orders rollout pod. This tool never reduces
existing workloads or changes node sizes. At the observed 100 to 108% usage the
cluster Job and fault gates are blocked.

Jobs are constrained by node affinity to the nodes admitted by that preflight;
the scheduler cannot place them on another node with insufficient measured
headroom. A successful Job exit without the complete result ledger and final
passing summary is reported as a failed, incomplete run.

```bash
python3 scripts/reliability-runner.py preflight \
  --context eurotransit --mode job --extra-memory-mib 576 > preflight.json
```

For #47, admission also requires `faultsPermitted: true`, matching context/namespace
and a fresh timestamp. The additional 576Mi example is a 64Mi proxy plus one
512Mi Orders rollout pod; adjust upward if actual configured limits differ.
Even workstation fault preflight conservatively keeps the runner allowance.

For the Job, enable `reliabilityTests.enabled` and supply its immutable `image`
through a reviewed GitOps values change. ArgoCD renders a permanently suspended
CronJob independent of progressive delivery; it consumes no pod memory until
launched. Run the same command with `--mode job`; no local secret is required.
The Job receives `CLIENT_SECRET` from the existing SealedSecret-backed runtime
Secret. Do not start the CronJob directly: its fixture ConfigMap deliberately does
not exist. The launcher inserts claimed fixtures and run identity. The Job has no
ServiceAccount token, privileges or retries; a ten-minute deadline and one-day TTL
bound execution and preserve time to retrieve logs. Output uses emptyDir, and
stdout events remain available from completed pods without exec/cp or sidecars.

## Read-only evidence and verification

```bash
python3 scripts/reliability-runner.py collect \
  --context eurotransit --output /absolute/path/results-new-run
python3 load-tests/verify.py \
  --ledger /absolute/path/results-new-run/orders.jsonl \
  --evidence /absolute/path/results-new-run/evidence.json \
  --output /absolute/path/results-new-run/verification.json
```

The collector executes SELECT statements inside `BEGIN READ ONLY`, with a ten-second
statement timeout, through the CNPG primary's local `psql`. Operator permissions
include pod exec on PostgreSQL; the runner pod has none. Local postgres superuser
access is used for the cross-database audit only; do not give these credentials or
operator permissions to CI. Order IDs are validated UUIDs taken from the ledger.
Queries export only matching Orders, reservations, owned seats and authorizations;
provider reference values become SHA-256 identifiers. `extraction: COMPLETE` means
the queries completed, not that correctness passed.

Provider effects cannot be inferred from payment rows. By default `providerEffects`
is INCOMPLETE and no claim of no double-charge is made. `--provider-evidence` accepts
a separately collected provider audit `{runId, extraction: "COMPLETE", authorizations:
[{order_id, provider_reference, status, amount, currency}]}` and hashes references before exporting.
Its attribution/completeness must be verified at the provider; the collector only
validates scope and shape. The harness verifier determines the final result.

`canonical-events.json` contains original order-placed outbox IDs, Kafka keys
(`aggregate_id`) and payloads only for run Orders. It is owner-only and may contain
principal identifiers: retain locally as restricted operational evidence and do
not commit it. It supports a separately authorized #47 replay; this collector
never produces Kafka messages. Notification payloads and payment credentials
are not collected. Public `evidence.json` projects safe event fields only.

Artifacts also include run metadata, before/after pod states and images, structured
order outcomes, summary and runner logs. A failed/ambiguous run must retain its
artifacts and report missing evidence. Missing dashboard, trace, provider or live-run evidence remains explicitly unavailable. Preserve the
run's UTC window when linking actual Prometheus/Grafana evidence in experiment reports.

With an operator-managed Prometheus port-forward, supply `collect --prometheus-url
http://127.0.0.1:9090` to export checkout confirmation/failure counters, duration
buckets and dead-letter counters over the run's UTC window. Results are explicitly
namespace/time scoped and include other traffic; they do not prove per-order
invariants. Without a Prometheus URL, `telemetry.json` remains INCOMPLETE.

## Independent sandbox provider audit

`python3 scripts/reliability/provider-audit.py --run-dir <results>` reads
`run.json` and `evidence.json`, then enumerates the complete Stripe sandbox charge
window through read-only HTTPS GET `/v1/charges`, padded by two seconds on each
side. Supply `STRIPE_SECRET_KEY` through the environment using a secret manager or
hidden prompt. Only test/restricted-test key prefixes are accepted; keys never
appear in arguments, output or artifacts. Redirects are rejected so authorization
cannot be forwarded to another host. Each request has a ten-second timeout;
pagination uses 100 records/page and stops at ten pages. Exhaustion is required.

The output is exclusive-created `provider-audit.json` with permission 0600.
It contains only attributed order IDs, charge references, amounts, currencies,
statuses and audit coverage. No card, customer, billing or provider response body
is exported. Charge references are needed by the subsequent collector but remain
restricted here; the collector hashes them for public evidence.

Any unattributed successful/authorized effect in the window, duplicate reference, live-mode charge,
missing authorized payment effect, pending charge, invalid record, pagination
limit or HTTP failure leaves extraction INCOMPLETE and exits nonzero. Hashing a DB
reference is used only to map independently enumerated charges to run Orders;
it is not used to manufacture provider effects. Other traffic during the window
can therefore prevent a complete run attribution, even when checkout succeeded.

An unattributed **failed** Charge object is recorded separately in
`unattributedFailedAttempts` only with explicit zero-effect proof: `paid=false`,
`captured=false`, integer `amount_captured=0`, integer `amount_refunded=0`, and
an explicitly null `balance_transaction`. It is not a successful authorization;
its ownership is not certified. Missing proof still blocks extraction. An
uncaptured successful authorization (`paid=true`) remains a monetary effect and
cannot use this classification. Pending effects always block. All records and
pages are still enumerated, and expected run authorizations must all be present.
See the [measured correction](../verification/kind/progressive-delivery.md#orders-canary).

After a complete audit, rerun `collect --provider-evidence <provider-audit.json>`
and the harness verifier. Audit completeness applies to the bounded window,
not to future charges, historical charges outside the window or provider metadata
that the current payment adapter does not supply. Record this limit in the report.

Bounded pacing experiments and their overload-proof limits are recorded in
[Aks ramp spike](../verification/aks/checkout.md).

## Fault experiments

Use [fault hypotheses](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/verification/strategy.md) and the selected environment's verified runbook. The optional [Payments proxy](../../platform/reliability/payments-proxy/README.md) supplies a bounded latency lease. Its image must exist in the target registry before enabling its overlay.

The opt-in Helm overlay is `values.yaml` here. Supply the derivative image digest. Preparation and teardown require distinct GitOps reconciliations:

1. Set `enabled=true, routeOrders=false`. Check capacity including 64Mi proxy and the additional Orders pod needed during rolling update; check startup and proxy Ready.
2. Set `routeOrders=true`. Wait for Argo Synced/Healthy and the Orders rollout. Run a neutral baseline through the proxy, requiring CONFIRMED orders and healthy Catalog.
3. Run one latency lease. Delete the lease after observations. Save recovery, including any DELIVERY_EXHAUSTED incidents and explicit operator redrive; automatic convergence is not guaranteed.
4. Set `routeOrders=false`, keep `enabled=true`. Wait for healthy direct Orders rollout and another successful checkout.
5. Set `enabled=false` and reconcile to prune the proxy. Never delete the proxy while Orders points at it.

Default chart rendering remains unchanged. The proxy uses 32Mi requested/64Mi limited, CPU25m/100m, no Kubernetes token, no privileged network access, and no public/admin Service. The lease API binds localhost inside the pod. Use `kubectl --context CONTEXT -n eurotransit port-forward --address 127.0.0.1 deployment/payments-fault-proxy 18474:8474`.

## Fault execution

First run #46's capacity/readiness preflight and collector. A fresh preflight must identify the same context, namespace and run. `scripts/reliability/fault.py` defaults to dry-run; `--execute` explicitly enables a mutation.

Example (after the neutral baseline, with the run already created by #46):

```bash
python3 scripts/reliability-runner.py preflight --context eurotransit --mode workstation --run-id "$RUN_ID" --extra-memory-mib 576 > "$OUTPUT_DIR/preflight.json"
python3 scripts/reliability/fault.py payments-latency --context eurotransit --run-id "$RUN_ID" --output-dir "$OUTPUT_DIR" --preflight "$OUTPUT_DIR/preflight.json" --seconds 60 --execute
python3 scripts/reliability/fault.py payments-reset --context eurotransit --run-id "$RUN_ID" --output-dir "$OUTPUT_DIR" --preflight "$OUTPUT_DIR/preflight.json" --execute
```

Reset deliberately remains available if a later capacity/preflight check fails. The fresh preflight run ID must match, and latency preparation reserves 576Mi for the proxy plus Orders rollout. Each fault is recorded before mutation; an ambiguous attempt must be investigated rather than blindly repeated. A separate run is required for each experiment.

Payments breaker needs at least five actual calls within 20s (failure/slow threshold50%, open10s, half-open3). Traffic too low makes the experiment inconclusive. Capture Catalog simultaneously. Timeout3s, at most three remote attempts, and Kafka's bounded redelivery may result in persistent reconciliation incidents.

Inventory command selects exactly one Ready pod, records its UID and deletes using an API UID precondition. This is a single forced pod kill (`gracePeriodSeconds: 0`), not graceful shutdown or a disruption scheduler. The UID precondition limits it to the selected original pod. Wait for its replacement and collect evidence. A kill under contended traffic is not proof of killing mid-reservation: require temporal overlap from actual traces/logs before claiming that stronger result.

After collection, `scripts/reliability/replay-events.py` replays only original exported `order-placed` payloads, scoped to the run by the collector; at most20. Use the existing broker producer tool, explicitly choosing the verified broker pod. It defaults to no publication, saves hashes/source ids, and never writes SQL or fabricates payloads. Retry HTTP separately using the original idempotency keys. Event replay and HTTP retry demonstrate different invariants.

Read-only audit must check active/confirmed reservation uniqueness per order and seat/date, consistency between confirmed orders and seats, and payment authorization uniqueness for run orders. Provider-reference hashes are useful for correlating effects; application DB rows alone cannot prove that Stripe did not double-charge. Link sandbox provider audit evidence before claiming that result.

At current memory saturation, fault execution is blocked. Do not add nodes/memory or silently scale down unrelated workloads. A failed capacity gate is a recorded prerequisite failure, not an experiment result.
