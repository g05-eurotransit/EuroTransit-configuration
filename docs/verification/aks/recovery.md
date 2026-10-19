# AKS workload and database recovery

Each section records a separate experiment with its own verdict, tested configuration and evidence.

| Scenario | Result and material limit | Details |
| --- | --- | --- |
| Selective node drain | Availability failed without spare capacity; operator uncordon recovered service and three accepted orders confirmed. | [Node drain](#node-drain) |
| Temporary PostgreSQL standby | Primary promotion ~3.5 s and read recovery ~5.1 s; one accepted order needed replay. | [Primary failover](#postgres-failover) |
| Orders SIGTERM | Accepted work preserved; four attempts failed during single-replica replacement. | [Orders shutdown](#orders-shutdown) |

<a id="node-drain"></a>

## Selective application node drain

| Report element | Summary |
| --- | --- |
| Hypothesis (accepted by the team) | Evacuating the application workloads of one node keeps checkout available. |
| Steady state | All three nodes and the critical services Ready; Orders, Catalog and Inventory with one replica each on the target node; no application PDBs, no spare replica. |
| Injected fault | The node cordoned and Catalog, Inventory and Orders evicted through `policy/v1` with their normal grace. |
| Observations | Catalog 24 of 105 probes HTTP 503 until its replacement was Ready; Orders Pending for lack of CPU and memory until an operator uncordoned the node; the three accepted orders confirmed with three matching charges ([details](#node-drain-injection-and-observations)). |
| Conclusion | Refuted: availability did not hold without spare capacity. Accepted work recovered without data correction. |
| Follow-up change | The Kind HA profile adds separated replicas, PDBs and failed-node headroom, and its [worker-loss experiment](../kind/ha-failover.md) repeats the disruption. |

<a id="node-drain-steady-state-and-proposed-hypothesis"></a>

### Steady state and hypothesis

All three AKS nodes and the critical services were Ready. Orders, Catalog and
Inventory each had one replica on node `aks-eurotransit-76738666-vms77`.
Hypothesis: evacuating that node's application workloads should retain
checkout availability. The observed deployment has no application PDBs and no
spare critical-service replica; this experiment tests those actual conditions,
not an assumed HA deployment. The team accepted this hypothesis.

<a id="node-drain-injection-and-observations"></a>

### Injection and observations

At 22:24:40.783 UTC the node was cordoned. UID-conditioned `policy/v1` Evictions
of Catalog, Inventory and Orders succeeded at 22:24:40.990 to 41.401 UTC with the
normal 45-second termination grace. No forced bypass of a PDB was used. Other
workloads, the node, its volumes and its network remained running. This is a
selective application evacuation, not a whole-node crash or an AZ outage.

Six ramp attempts ran with two VUs. Three were accepted and three had technical
HTTP failures. The original harness failed (exit 99). All three accepted orders
later confirmed; their separately labelled final-state audit passed with three
matching Stripe charges, zero unmatched charges and zero invariant violations.
The three rejected attempts remain failures in the original ledger.

| Observation | Result |
| --- | --- |
| Catalog probes | 81/105 HTTP 200; 24 HTTP 503 |
| Catalog unavailable samples | 22:24:42.381 to 22:25:08.457 UTC |
| Replacement Catalog Ready | 22:25:09 UTC, node vms78 |
| Replacement Inventory Ready | 22:25:17 UTC, node vms76 |
| Orders scheduling | Pending: insufficient CPU/memory on the remaining nodes |
| Recovery intervention | Early uncordon to restore scheduling on vms77 |
| Replacement Orders Ready | 22:26:20 UTC, original node vms77 |
| Orders eviction to replacement readiness | Approximately 99 seconds; includes operator uncordon |

The scheduler explicitly reported `1 Insufficient cpu` and `2 Insufficient
memory`, alongside the cordoned node. Resource-waiver authorization cannot add
physical capacity. Cleanup confirms the node is schedulable again. No workload
requests, limits, replicas or PDBs were changed to manufacture availability.

<a id="node-drain-conclusion-and-follow-up"></a>

### Conclusion and follow-up

Availability did not hold. Accepted work recovered without data correction,
with operator restoration of node scheduling. This is not an automatic node
recovery RTO or proof of AZ resilience. Reserve capacity for a failed node,
distribute multiple critical replicas and enable reviewed application PDBs
before repeating a genuine node/AZ experiment. A PDB alone cannot make a
single-replica application continuously available.

<a id="node-drain-evidence"></a>

### Evidence

Restricted eviction responses, scheduler findings, pod readiness timestamps,
Catalog samples and cleanup: `.resilience-evidence/chaos-20261012/node-drain-20261012T222431Z`.
Original run: `load-results/node-drain-20261012T222431Z`.
Accepted-order audit: `load-results/node-accepted-orders-final-audit-20261012T222704Z`.

<a id="orders-shutdown"></a>

## Orders SIGTERM under checkout traffic

| Report element | Summary |
| --- | --- |
| Hypothesis (accepted by the team) | SIGTERM flips readiness while work drains, stops consumers cooperatively and preserves accepted orders without double processing. Single-replica availability is assessed separately. |
| Steady state | Orders `bad4c04` Ready with one replica; one order `CONFIRMED`, another in `CONFIRMING_INVENTORY` at the signal. |
| Injected fault | SIGTERM sent directly to the Orders JVM under checkout traffic. |
| Observations | Readiness 503 within 0.6 s, consumers and server stopped in order, exit 143 with no SIGKILL; both accepted orders `CONFIRMED` without replay, two matching charges; four requests failed with HTTP 502 ([details](#orders-shutdown-signal-drain-and-recovery)). |
| Conclusion | Held for readiness refusal, cooperative shutdown and accepted work. Single-replica availability did not hold. |
| Follow-up change | Application #132 stops a listener after the record in progress instead of its whole batch; Kind runs two Orders replicas and its [Pod shutdown experiment](../kind/orders-shutdown.md) covers endpoint removal. |

<a id="orders-shutdown-steady-state-and-proposed-hypothesis"></a>

### Steady state and hypothesis

Orders `bad4c04` was Ready with one replica. Hypothesis: SIGTERM flips
readiness while work drains, stops consumers cooperatively and preserves the
accepted orders without double processing. Continuous availability of a single
replica is assessed separately. The team accepted this hypothesis.

<a id="orders-shutdown-signal-drain-and-recovery"></a>

### Signal, drain and recovery

Run `et-stop-6bacc86a7bb7` made six ramp attempts with two VUs. A read-only snapshot
immediately before the signal found one CONFIRMED order and another in
**CONFIRMING_INVENTORY**. At **22:41:11.069 UTC**, SIGTERM was sent directly to
Java PID 1 in pod `orders-56b98b8cff-bxg97`; its UID was checked beforehand.
This exercises the application shutdown path, bypassing the Pod preStop sleep.
It is not a complete Pod termination/readiness-to-endpoint-removal proof.

| Observation | Result |
| --- | --- |
| Direct readiness HTTP 503 | 22:41:11.602 UTC; body `OUT_OF_SERVICE` |
| Consumer-stop log messages | 22:41:11.741 to 11.868 UTC |
| Graceful server shutdown started | 22:41:11.874 UTC |
| Graceful server shutdown completed | 22:41:11.948 UTC |
| Old container exited | 22:41:14 UTC, code 143; no SIGKILL |
| Kubernetes restart | Same Pod UID; restart count increased from 0 to 1; Ready again |
| Client result | Failed, exit 99: two accepted/confirmed and four HTTP 502 |
| Accepted-order final audit | 2/2 CONFIRMED without replay, VERIFIED, zero violations |
| Independent Stripe audit | Two matching charges; zero unmatched effects |

The restricted probe ledger contains 391 observations, including the observed
refusing-traffic response and unavailable/recovery periods. Old-container logs
were streamed before signaling, rather than reconstructed from the new process.
The original load verdict remains failed. A labelled accepted-order subset
supports the final correctness audit; it excludes neither HTTP failures from the
original run nor evidence of unavailability.

The signal terminated the process, and consumers and the server logged their
shutdown sequence. This bounded drill does not establish all possible orphan,
cancellation or backlog behaviors. The published
[application shutdown report](https://github.com/g05-eurotransit/EuroTransit-application/blob/6e7af67afc6b7f785b269de0333ae3af1228c77e/docs/operations/reports/2026-10-orders-shutdown-local.md)
additionally records HTTP drain, Kafka backlog and dependency-down behavior,
including the immediate-stop fix. Application PR #132 merged that revision
into `dev` in the recorded run. Its local evidence is not AKS proof. The accompanying
lifecycle document describes a per-record `runBlocking` failure domain with
Kafka-owned shutdown; it does not claim a detached background coroutine scope.

<a id="orders-shutdown-conclusion-and-evidence"></a>

### Conclusion and evidence

The observed in-flight confirmation and both accepted orders were preserved;
readiness refusal and cooperative process shutdown held. Single-replica
availability did not hold. Full Pod endpoint removal, structured-concurrency
ownership and additional cancellation cases remain explicit review gates.

Restricted signal metadata, state-at-stop snapshot, readiness samples, old
container logs and termination status:
`.resilience-evidence/chaos-20261012/orders-shutdown-20261012T224058Z`.
Original run: `load-results/orders-shutdown-20261012T224058Z`.
Final audit: `load-results/orders-shutdown-20261012T224058Z-final-audit-20261012T224213Z`.
Temporary port-forward/log processes created by this experiment were stopped;
user-owned processes were not terminated. Resource saturation was waived for
bounded traffic; no application resource or retry setting changed.

<a id="postgres-failover"></a>

## CloudNativePG primary pod failover

| Report element | Summary |
| --- | --- |
| Hypothesis (accepted by the team) | CNPG promotes the Ready standby after a primary-pod crash, database-backed checkout reads recover, and accepted checkout work converges without duplicate effects. |
| Steady state | A temporary second CNPG instance on another node, Ready and replayed to a fixed WAL position; asynchronous replication; Argo reconciliation of the database paused. |
| Injected fault | The primary pod force-deleted under checkout traffic. |
| Observations | New primary after about 3.5 s, Orders reads back after about 5.1 s; three HTTP 500 and three accepted, two of them `CONFIRMED` automatically; the third stayed `RESERVING` with a `DELIVERY_EXHAUSTED` incident until its event was replayed; three matching charges ([details](#postgres-failover-fault-and-observed-recovery)). |
| Conclusion | Held for promotion, read recovery and final correctness. Automatic completion of every accepted order did not hold on Orders `bad4c04`. No failover RTO is adopted; the timings are measurements. |
| Follow-up change | Application #139 rides out a dependency outage before dead-lettering, and #149 verifies recovery from PostgreSQL statement failures; the [Kind HA failover](../kind/ha-failover.md) repeats the promotion with synchronous replication. |

<a id="postgres-failover-steady-state-and-proposed-hypothesis"></a>

### Steady state and hypothesis

The normal AKS deployment has one PostgreSQL instance. For this experiment only,
its owning Argo Application policy was saved and automatic reconciliation paused;
CNPG instances increased to two, leaving the CNPG operator running. Existing
controller pauses remained unchanged. The physical standby on a different node
was Ready and had replayed a fixed pre-test WAL position before injection.
Replication was asynchronous; this is not a synchronous zero-RPO configuration.

Hypothesis, accepted by the team: CNPG promotes the Ready standby after a primary-pod crash,
restores database-backed checkout reads, and accepted checkout work converges
without duplicate effects. The team adopts no failover RTO, so timings below are
measurements, not an RTO pass.

<a id="postgres-failover-fault-and-observed-recovery"></a>

### Fault and observed recovery

Run `et-pg-cc251ce6b763` made six ramp attempts with two VUs. At
**22:34:32.563 UTC**, a UID-conditioned force deletion killed primary
`eurotransit-postgres-1`, UID `110fb912-8613-4ea5-8872-8ed47878f774`.
Its Ready physical standby `eurotransit-postgres-4` became the new primary.

| Observation | Result |
| --- | --- |
| First sample naming new primary | 22:34:36.073 UTC, approximately 3.51s after injection |
| Orders GET sample at that time | HTTP 500 |
| First subsequent Orders GET HTTP 200 | 22:34:37.673 UTC, approximately 5.11s after injection |
| Client verdict | Failed, exit 99 |
| Attempts | Three HTTP 202 accepted; three HTTP 500 |
| Accepted work without intervention | Two CONFIRMED; one RESERVING with DELIVERY_EXHAUSTED incident |
| Failed-request key audit | Only the three accepted requests had idempotency records |
| Scoped recovery | Exact three original order-placed events replayed once |
| Final accepted-order audit | 3/3 CONFIRMED, VERIFIED, zero violations |
| Independent Stripe audit | Three matching sandbox charges, zero unmatched charges |

Sampling is approximately once per second and includes request overhead. A
successful GET does not establish successful new checkout completion. The
nonterminal order remained RESERVING throughout twelve further observations;
its failed pre-replay audit is preserved. Operator replay was required for final
money-path convergence. The unchanged original ledger retains the HTTP failures.
The connector status endpoint showed all three Debezium connector tasks RUNNING.

Cleanup restored one CNPG instance and the exact original Argo sync policy.
CNPG retained the promoted primary, and subsequently reported healthy 1/1.
No manual PVC deletion, SQL business correction or consumer-offset reset was
performed. Standby setup was temporary runtime instrumentation, not a GitOps
HA deployment or proof that the ordinary single-instance deployment tolerates
primary failure.

Two preceding setups injected no fault: a conservative moving-WAL lag check
was corrected to a fixed physical-replica position, and a later client setup
failed the seat-map precheck. They are excluded from failover evidence and their
setup changes were restored before this run.

<a id="postgres-failover-conclusion-and-evidence"></a>

### Conclusion and evidence

Primary promotion and database-backed read recovery were automatic. Continuous
checkout availability and automatic completion of every accepted order did not
hold. Final money-path correctness held after explicit recovery. A complete
availability proof still needs a reviewed HA configuration on the target cluster.

Restricted state snapshots, WAL check, primary observations, idempotency-key
audit and cleanup: `.resilience-evidence/chaos-20261012/postgres-failover-20261012T223334Z`.
Original run: `load-results/postgres-failover-20261012T223334Z`.
Failed automatic-convergence audit:
`load-results/postgres-accepted-orders-final-audit-20261012T223720Z`.
Recovered final audit:
`load-results/postgres-after-replay-final-audit-20261012T223758Z`.
