# Run the bounded Kind HA experiment

Measure worker loss, PostgreSQL promotion, checkout recovery and financial correctness on the isolated HA profile. Start it with [Kind setup](kind.md), then satisfy every preflight below. The [HA report](../verification/kind/ha-failover.md) owns recorded results and failed diagnostics; [deployment](../platform/deployment.md) owns the configured topology.

All nodes share one workstation. The control plane, ingress, identity, operators and monitoring stay outside the fault target. This measures worker-container loss, not host/AZ failure or AKS capacity. PDBs govern voluntary eviction, not abrupt worker loss.

## Execute the bounded experiment

After bootstrap, use the host k6 binary and the local DNS entries for
`eurotransit.local` and `keycloak.eurotransit.local`, both resolving to loopback.
The runner permits self-signed TLS only for these fixed local endpoints.
Kafka diagnostics use short-lived Pods with separate memory limits rather than
launching another JVM inside a broker's memory cgroup. They have no API token,
a bounded lifetime and unconditional deletion on exit.

```bash
kubectl --context kind-eurotransit -n monitoring port-forward \
  --address 127.0.0.1 svc/kube-prometheus-stack-prometheus 19190:9090
# In another terminal, from this repository:
python3 scripts/kind-ha-experiment.py baseline
# After an instance replacement, align the CDC barrier with live instance IDs:
python3 scripts/kind-ha-experiment.py prepare-cdc
# If standby logical slots are not initialized (including after primary rejoin):
python3 scripts/kind-ha-experiment.py warmup
python3 scripts/kind-ha-experiment.py fault --fault-mode worker-stop
# Explicit longer observation of the existing finite connector auto-restart policy:
# python3 scripts/kind-ha-experiment.py fault --fault-mode worker-stop --fault-seconds 180
# A different failure, retained because it exposed unresolved recovery problems:
# python3 scripts/kind-ha-experiment.py fault --fault-mode worker-freeze
```

Additional sequential checks use the same fixed Kind context, sandbox provider
credential, exclusive lock, fresh-seat claims and independent financial audit:

```bash
python3 scripts/kind-orders-shutdown.py
python3 scripts/kind-checkout-load-shedding.py
```

The shutdown check holds one fresh seat with a finite, rolled-back row lock to
observe a listener in flight, then normally deletes that Orders Pod and records
readiness, endpoint withdrawal, drain and recovery. It makes at most four
checkouts. The load-shedding check applies only rendered ingress/middleware
objects with a deliberately low temporary limit of 1/s, burst 1, makes at most
eight attempts and restores the ingress. It is direct local test configuration,
not evidence of a GitOps delivery. Read the [shutdown report](../verification/kind/orders-shutdown.md)
and [429/recovery report](../verification/kind/checkout-load-shedding.md) for measured scope.

The baseline makes two real sandbox checkouts. `warmup` checks the slot gate
and executes at most four such batches, stopping immediately once all standby
slots are initialized. Other preflight failures are never waived. Three bounded
seat-availability reads warm cold auth/JWK/database caches before the measured
harness; their responses remain in `setup-warmup.json`. A failed checkout setup
is preserved and never rewritten as a passing run. The fault run makes at most eight,
with one checkout VU, 12-second spacing after each outcome and one independent
Catalog VU for 180 seconds. By default it SIGKILLs the current primary's Kind
worker and starts the same container after 90 seconds, following the first
successful checkout. It preserves the node's writable layer and volumes. The
separate `worker-freeze` mode pauses processes instead; it is not equivalent to
node termination and failed checkout recovery in the recorded investigation.
An independent host process restores
the worker even if the runner exits; normal cleanup also unpauses it. The harness
has a 500-second operator deadline, and final-state polling is bounded to 120
seconds. No manual replay/redrive or database business-row cleanup is performed.

Only Kind's local provider Secret is read. The runner never retrieves an AKS
credential. It creates an exclusive run lock and persistent fresh-seat claims.
Private outputs go into ignored `load-results/et-kind-*` directories. Failed
client observations remain intact; the labelled `final-audit/` is separate.
`server-attribution/` also resolves known run idempotency keys in the database:
an HTTP timeout can hide a committed order. This audit verifies those orders and
provider charges without turning the original HTTP 0 into HTTP 202. The ordinary
verifier retains its acceptance failures; financial correctness is a separate result.
A zero runner exit for the fault requires a new primary and at least one checkout
confirmation while the worker is still unavailable, node NotReady observation, healthy
Catalog samples and an independently verified final state for all accepted orders.
It does not claim that all admission attempts succeeded or that an SLO was met.
This is a strict diagnostic gate, including zero Catalog errors, rather than an
additional requirement from the project specification. A nonzero exit caused by
transient errors does not by itself invalidate demonstrated failover. Report
recovery, correctness and user impact separately, then compare the measurements
with the applicable team-owned SLO/RTO and error budget. Do not silently treat
zero errors as mandatory or declare SLO compliance from recovery alone.

## Slot readiness

Initial synchronization can require bounded warm-up batches and offset flushes. Verify initialized restart/confirmed LSNs for all three slots on both standbys. An active owner is permitted only for the internal `pg_failover_slots worker`; reject an external walsender. Do not drop slots or replay orders to bypass the gate. The [CDC incident](../verification/incidents/cdc-slots.md) records a separately authorized manual repair, not a general recovery recipe.

## Acceptance checklist before injection

1. Four Ready nodes, no pressure/OOM, enough host headroom for the experiment.
2. Three Ready PostgreSQL instances on distinct workers; inspect synchronous
   standby configuration and streaming state, not just the Cluster Ready flag.
3. Three Kafka brokers, RF 3 and full ISR for business and Connect topics.
4. Both Connect workers and all three tasks Ready; outbox slots initialized on
   both PostgreSQL standbys. Require both CR status and live REST task status;
   the operator's last status can be stale during failure.
5. Two Ready replicas on distinct workers for each critical backend. Identify
   the replicas that will be interrupted together with PostgreSQL.
6. Healthy Catalog, successful real sandbox checkout, independent provider
   audit, attributable fresh seats, working metrics and retained raw evidence.
7. Team-owned recovery and availability criteria recorded before the fault.

The runner requires both physical standbys to be streaming from the current
primary, with replay lag below 1 MiB before setup and zero at injection. Ready
3/3 alone was misleading during the initial attempts. A standby that has crossed
onto an incompatible timeline must be repaired before another experiment. The [HA report](../verification/kind/ha-failover.md) documents divergent-standby diagnosis and the assisted, PVC-preserving repair. Qualify the authoritative primary and a healthy synchronous standby before any instance replacement.
After such a repair, run `prepare-cdc`, then `warmup`; never drop logical slots
or replay orders to bypass these gates. This assisted repair is not evidence of
automatic recovery.

## Combined experiment

Proposed hypothesis for team ownership: a single worker loss triggers primary
promotion while surviving service replicas and Kafka quorum remain available;
accepted orders converge without operator replay, oversell or duplicate charges.
A database promotion can cause temporary HTTP errors; measure them explicitly.

1. Preserve node/pod UIDs, placements, PostgreSQL settings/LSNs/slots, Kafka ISR,
   metrics and the run ID. Generate bounded checkout and continuous Catalog load.
2. Resolve the current primary and its worker immediately before injection.
   Refuse a control-plane target, a non-Kind context or an unexpected container.
3. Stop only that worker container with SIGKILL for a bounded interval, with an
   independent host-side restart watchdog and unconditional restoration on exit.
   For a process-freeze experiment, explicitly select `worker-freeze` instead.
   Do not delete the worker or its PVCs. Keep one injected failure per experiment.
4. Observe node NotReady, primary promotion, `-rw` endpoint change, surviving
   API replicas, Kafka leaders/ISR and connector recovery. Continue traffic and
   polling; preserve original client deadlines and HTTP errors.
5. Restore the worker and verify old-primary rejoin, three Ready database
   instances, all Kafka ISR restored and consumer lag convergence.
6. Compare every accepted order with final order/reservation/payment state and
   an independent Stripe sandbox audit. Do not silently replay failed work or
   replace failed client observations with a passing final audit.

Record primary promotion time, first successful database write, first successful
checkout admission and confirmation, maximum Catalog outage, original client
outcomes and total convergence time separately. Recovery after worker restoration
must be distinguished from recovery while the worker remained down.

## Evidence and reporting

Keep raw API, provider and credential-bearing records outside Git. Commit a
sanitized report with hypothesis, steady state, exact topology and image digests,
injection timeline, observations, cleanup and a verdict for each criterion.
The report must distinguish preparation from an executed/passed experiment.
