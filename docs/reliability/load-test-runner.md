# Load-test runner (issue #46, first tranche)

The application repository owns scenarios and correctness assertions in
[`load-tests`](https://github.com/g05-eurotransit/EuroTransit-application/tree/dev/load-tests).
This repository owns admission checks, fixture ownership and operational evidence.
No HA expansion or resident chaos controller is part of this tranche.

## Workstation baseline

Prefer the immutable harness container on a workstation, outside AKS. The image
is built by the application CI; substitute its published commit SHA or digest.
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
Application `load-tests/run.py` on a workstation with native k6. Docker mounts
fixture input read-only and runs with the operator's UID to preserve owner-only
output permissions. Tokens and credentials are passed by environment name, not
in argv. A Docker administrator can inspect container environment: use only a
trusted workstation. Public TLS verification is enabled by the application harness.

Fixture format is the application contract: version 1 and a `fixtures` array
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

The optional Job requires a schedulable, untainted node with 50m/128Mi available
requests and measured memory + 256Mi runner limit + 128Mi safety margin within
allocatable. `--extra-memory-mib` only increases that bound: experiments must
include proxy peak and any extra Orders rollout pod. This tool never reduces
existing workloads or changes node sizes. At the observed 100–108% usage the
cluster Job and fault gates are blocked.

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
python3 ../EuroTransit-application/load-tests/verify.py \
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
validates scope and shape. The application verifier determines the final result.

`canonical-events.json` contains original order-placed outbox IDs, Kafka keys
(`aggregate_id`) and payloads only for run Orders. It is owner-only and may contain
principal identifiers: retain locally as restricted operational evidence and do
not commit it. It supports a separately authorized #47 replay; this collector
never produces Kafka messages. Notification payloads and payment credentials
are not collected. Public `evidence.json` projects safe event fields only.

Artifacts also include run metadata, before/after pod states and images, structured
order outcomes, summary and runner logs. A failed/ambiguous run must retain its
artifacts and report missing evidence. This tranche does not manufacture dashboard
screenshots, tracing results, provider audits or a successful AKS run. Preserve the
run's UTC window when linking actual Prometheus/Grafana evidence in experiment reports.

With an operator-managed Prometheus port-forward, supply `collect --prometheus-url
http://127.0.0.1:9090` to export checkout confirmation/failure counters, duration
buckets and dead-letter counters over the run's UTC window. Results are explicitly
namespace/time scoped and include other traffic; they do not prove per-order
invariants. Without a Prometheus URL, `telemetry.json` remains INCOMPLETE.
