# Kind worker loss and PostgreSQL failover — 2026-10-17

Status: **partial**. PostgreSQL and checkout recovered automatically during an
abrupt worker stop; the strict zero-error experiment did not pass. The four
process-freeze runs did not recover checkout while the worker remained frozen.
Promotion, client availability and financial convergence are separate findings.
This report supersedes the earlier
[preparation snapshot](kind-ha-preparation-2026-10-17.md).

| Criterion | Final observation | Verdict |
| --- | --- | --- |
| PostgreSQL promotion and synchronous replication with worker stopped | Promotion at 51.86 s; surviving quorum sampled at 70.30 s | Demonstrated |
| Checkout recovery before worker return | One confirmation at 179.62 s during the declared 180-second stop | Demonstrated once; no team RTO/SLO pass claimed |
| Committed purchases in final stop run | 5/5 confirmed; five distinct Stripe charges; full invariant audit passed | Passed |
| Original client experience | 3 confirmations, 2 polling timeouts, 3 technical failures across 8 attempts | Failed zero-error criterion |
| Catalog replica failover | 250 HTTP 200 and one HTTP 504; p95 615.43 ms | Partial; failed zero-error criterion |
| Process-freeze recovery | No checkout confirmation during any of four freezes | Failed |
| Continuous Kafka consumer-lag SLI | Expected Prometheus series missing | Not verified |

A later [Catalog-only verification](catalog-failover-verification-2026-10-17.md)
attributed the historical 504 to the replica on the stopped worker. A controlled
process stall reproduced five gateway timeouts while the healthy replica returned
52/52 successful responses. Errors stopped after endpoint withdrawal; no Catalog
business-logic defect was observed on the tested routes API. This diagnosis does
not change the original HA test's partial verdict.

## Hypothesis and steady state

Proposed hypothesis for team review: losing the worker hosting PostgreSQL's
primary preserves Kafka quorum and Catalog browsing, promotes a standby and
restores checkout before that worker returns. Every committed purchase must
converge without duplicate reservations, oversell or duplicate provider charges.
The team must own the hypothesis and choose its RTO/SLO targets; no numeric
target or production availability claim is inferred from these small samples.

The experiment uses one control plane and three workers on one workstation,
Kubernetes v1.34.0. Two replicas of each critical backend occupy distinct
workers. PostgreSQL 16 has three separated instances and `ANY 1` synchronous
replication with **required** durability. Kafka 3.9 has three persistent
broker/controllers, RF 3 and min ISR 2. Two Kafka Connect workers share one
distributed group and three outbox tasks. Traefik, identity, controllers and
observability stay outside the interrupted worker.

Application images were reused, not rebuilt or modified: Orders `45357ef`,
other backends `98bedf2`, frontend `4364f1f`.
[Image provenance](evidence/2026-10-17/kind-ha-images.json) records the digests.
All mutations targeted `kind-eurotransit`; AKS was not modified. With explicit
authorization, the sandbox provider credential was transferred into Kind in
memory. Credentials, raw financial identifiers and access tokens are not in Git.

Steady-state gates include four Ready nodes, no memory pressure, at least 1 GiB
host memory available, separated Ready replicas, full Kafka ISR, both Connect
workers and all tasks running, and initialized outbox slots on both standbys, with no external consumer
owning a standby slot. Baselines each submit two real sandbox checkouts and independently
check Stripe, reservations, sold seats and amounts. An important correction after
run 2 was to require **actual physical streaming**, not merely PostgreSQL Ready
3/3. Run 3 also verified zero replay lag on both standbys at injection.

## Method and original results

The [runner](../../scripts/kind-ha-experiment.py) reuses the existing k6 checkout,
collector, provider auditor and invariant verifier. Each fault run attempts eight
fresh-seat purchases from one VU, with 12 seconds between outcomes, alongside
one Catalog request per second for 180 seconds. Original HTTP and polling
deadlines remain unchanged. After the first confirmed purchase, `docker pause`
freezes the current primary's worker for 90 seconds. A separate host watchdog
and unconditional cleanup restore exactly that Kind container.

| Run suffix | Configuration at injection | Primary promotion | Client confirmations / attempts | Confirmed during freeze | Catalog errors / samples | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `f910496a33` | Initial HA profile | 49.66 s | 1/8 | 0 | 0/179 | Failed recovery during worker loss |
| `a7fe5c86db` | Bounded R2DBC pool; one non-streaming standby escaped the old preflight | 51.85 s | 3/8 | 0 | 8/139 | Failed recovery during worker loss |
| `1d68d06bdb` | Fresh streaming standby, bounded pool and Catalog GET transport retry | 51.81 s | 3/8 | 0 | 0/179 | Failed recovery during worker loss |
| `9e174ad41d` | Standby TCP timeout 5 s; Catalog replica also frozen | 56.14 s | 3/8 | 0 | 10/161 | Failed recovery during process freeze |

All four original k6 runs exited **99**. Node NotReady appeared 47.6–54.0
seconds after injection. Restoring the worker occurred about 90.7–92.0 seconds
after injection. These timings are sampled observations, not availability SLOs.
Catalog replicas were both outside the interrupted worker in runs 1 and 3;
those runs do not prove Catalog replica failover. Run 2 interrupted a replica
and exposed eight failed browse requests, including five-second timeouts.
Run 4 still returned ten Catalog 504 responses, with about one-second p95,
despite bounded GET transport retries. The TCP timeout also did not restore
checkout while the worker was frozen. These changes are not a passing fix for
the process-freeze failure.

## Financial correctness and client delivery

Run 1 has one attributable committed/confirmed purchase and one matching sandbox
charge. Runs 2 and 3 each have **six** committed purchases, all finally confirmed
with six distinct successful charges and matching reservations/sold seats. No
duplicate effect or oversell was observed within these run-scoped purchases.
Run 4 has five committed/finally confirmed purchases and five distinct charges;
two order IDs were recovered through idempotency records after HTTP timeouts.

Runs 2 and 3 originally returned only three order IDs to the client. Three
additional requests committed despite an HTTP timeout. A SELECT-only audit of
their exact idempotency keys recovered the IDs and compared final API, database
and independent Stripe evidence. No order or event was manually replayed and no
business rows were repaired or deleted.

`server-attribution/` preserves the original HTTP 0 and labels the database
attribution. Its ordinary verifier still reports `invalid_acceptance_evidence`;
the separate financial result passes only if every other invariant passes and
the provider audit is complete. Thus **financial correctness passed; client
delivery and recovery during worker loss did not**. A timeout is never rewritten
as a successful response.

## Abrupt worker termination and host repair

The separate stop run `7788dd4e18` killed the worker hosting the primary, one
replica of Orders/Inventory/Payments, one Connect worker, a broker and Notifications.
The node became NotReady at 45.39 s and a new primary was observed at 47.49 s.
The surviving physical standby resumed streaming before the worker returned;
the recorded quorum sample is at 66.16 s. A new checkout was accepted with HTTP
202 during the outage, but its client poll timed out. There were no checkout
confirmations during the 90-second stop. Catalog returned 180/180 HTTP 200.

This run did **not** pass end to end. Debezium tasks failed with connection
timeouts during promotion, despite Connect reassignment at approximately 23 s.
The operator's CR task status was stale; direct REST showed FAILED tasks. The
runner now checks both sources before injection. Strimzi's existing automatic
restart policy remains finite (`maxRestarts: 10`); the HA-only operator profile
reduces its reconciliation interval from 120000 to 15000 ms. This does not
remove the restart policy's own backoff or establish a 15-second recovery RTO.

On worker restart, kube-proxy crashed with `too many open files`. The Linux
host limits were `max_user_instances=128`, `max_user_watches=124390`. Following
the authorized resource exception, they were raised **at runtime only** to
1024 and 524288 respectively. The broken kube-proxy Pod was recreated. DNS,
services and returning application Pods recovered; this assisted repair is
outside the measured run and is not automatic-recovery evidence. No persistent
sysctl file was written. The new preflight requires at least 512 instances and
524288 watches, as the limits are shared by Kind containers on the host.

At the original audit deadline, only one of five committed orders was confirmed.
The provider audit also found two unattributed successful sandbox charges of
EUR 49.90, whereas the run's fixtures cost EUR 24.90 each. Their hashes did not
match any local payment authorization at investigation time. Their origin is
unproven: they are retained as incomplete provider evidence, not excluded on an
assumption and not called proven duplicate charges. The original run and audit
remain failed. Fresh two-checkout baselines after repair passed the full audit.

A subsequent stop experiment declares **180 seconds before injection**, retaining
the original client deadlines and eight-attempt bound. This observes the full
automatic connector recovery window; it does not retroactively pass the
90-second experiment or impose a team-owned RTO target.

That final run, `30677fd63d`, stopped the worker hosting primary `-2`, one
Catalog replica, one frontend replica and a Kafka broker. The other worker
replicas remained available. Node NotReady was sampled at 47.60 s, primary
`-1` at 51.86 s and standby `-6` in synchronous quorum at 70.30 s. During the
stop, checkout resumed accepting purchases and iteration 6 was confirmed at
179.62 s, with Docker still reporting the worker stopped. The independent
watchdog then started it; the runner observed that at 181.86 s. This is one
sample close to the window boundary, not a reliable 180-second RTO guarantee.

The first automatic Debezium restart happened before PostgreSQL was usable and
failed. The next policy backoff delayed recovery; Orders and Payments reached
their second automatic restart near the end of the fault. No manual connector
restart, event replay or business-row repair occurred in this final experiment.
The returning node, kube-proxy and PostgreSQL instance recovered without the
earlier host repair being repeated.

The final financial audit passed: all five committed orders were confirmed,
with matching reservations/sold seats, correct amounts, five distinct successful
Stripe authorizations and **zero unattributed charges**. Two original client
polls had timed out while their orders were ACCEPTED; their final confirmations
remain in the separate audit. The other three post-startup attempts failed
admission. Catalog had one 504 among 251 requests while a replica was down.
The original k6 exit remains **99**, the aggregate `haObserved` gate remains
**false**, and the operator runner exits 1. Neither final-state correctness nor
one recovered checkout rewrites this overall partial verdict.

The final [Kafka CLI snapshot](evidence/2026-10-17/kind-ha-final-kafka.json)
found 194 partitions, all RF 3 with full ISR, and zero measured lag on the
committed partitions for Orders and Notifications. Nine refund/DLT partitions
had no committed offsets and an empty log; their lag was not reported as a
numeric metric. This is a post-recovery sample, not a during-fault maximum or a
replacement for the missing Prometheus series.

The final [health snapshot](evidence/2026-10-17/kind-ha-final-health.json)
records primary `-1`, both standbys streaming in quorum with zero replay lag,
about 3.4 GiB host memory available and the runtime inotify settings. All four
Kind containers were running and none paused; the smoke suite passed. Temporary
diagnostic Pods were removed. The three detached PVCs from earlier repairs
remain preserved. No AKS resource was modified.

## Diagnosis and changes

1. The first run motivated HA-only pool validation and bounded acquisition,
   creation and validation waits. This did not resolve the database stall.
2. A standby could remain Ready while following an incompatible timeline.
   Following promotion, the new primary had no streaming physical standby and
   writes waited on `IPC/SyncRep`. Recreating its Pod alone was insufficient.
3. Before run 3, the version-matched CNPG plugin replaced only that divergent
   standby with `destroy ... --keep-pvc`, after verifying the authoritative
   primary and a healthy synchronous standby. Its old volume was preserved.
   Run 3 nevertheless reproduced the stall despite zero initial replay lag.
4. During run 3, the surviving standby timed out/reconnected through the old
   `-rw` destination and resumed only when the original worker returned. CNPG
   changed primary labels while the worker was still frozen, but new-primary
   `pg_stat_replication` was empty at promotion. This points to the remaining
   replication connection as the immediate blocker; it is not proof that pool
   tuning alone restores HA.
5. The next configuration sets CNPG 1.26's supported
   `STANDBY_TCP_USER_TIMEOUT=5000` in the isolated Kind HA operator values. Both
   physical standbys must show that numeric setting before another injection.
   Required synchronous durability is retained. This setting alone failed in
   run 4. Three divergent standby replacements preserved all detached old PVCs.

`docker pause` suspends processes with the freezer cgroup; it does not switch
off the worker's kernel networking. In the observed freeze, connection attempts
initially timed out in about five seconds, but a later connection remained stuck
until the node resumed. This is consistent with a peer that accepts TCP but
does not complete the protocol. It is an inference from the timestamps, not a
packet-capture proof. PostgreSQL 16's WAL receiver uses asynchronous libpq
connection polling; setting `connect_timeout` alone must not be assumed to bound
that operation. Traefik 3.4 also disables retry after request headers have been
written, explaining why a response stall differs from an initial dial failure.

The runner therefore supports two explicitly distinct faults: `worker-freeze`
preserves this failed CPU/process-stall experiment; `worker-stop` sends SIGKILL
to exactly one verified Kind worker and starts that same container after 90
seconds. The latter tests abrupt worker termination, preserves its writable
layer and volumes, and never deletes/recreates the cluster. Passing a stop test
would not erase the failed freeze result.

The HA profile also bounds Connect reassignment delay to 10 seconds and offset
flushes to 5 seconds. Catalog's optional ingress retry covers GET transport
failures only, with a 500 ms dial timeout and 1 second response-header timeout;
it does not retry purchase POSTs. Dev and AKS profiles retain their previous
settings. See the [runbook](kind-ha-runbook.md) for reproduction and safety gates.

A further harness correction distinguishes the extension's temporary slot ownership
from a consumer. The original blanket `active=false` gate produced false negatives
during slot advancement. The corrected gate requires all three slots, initialized
restart/confirmed LSNs, and allows an active owner only when its backend type is
`pg_failover_slots worker`. Tests reject an external walsender, missing slot or
uninitialized LSN. A post-rollout baseline also timed out on both client polls
while Connect reconnected, then automatically converged to two confirmed orders
and two matching charges; the original failed baseline is preserved.

## Evidence, verification and limits

[Sanitized machine-readable evidence](evidence/2026-10-17/kind-ha-experiments.json)
retains run IDs, original outcomes, timing, resource observations, config hashes
and raw-artifact hashes. Raw API/database/provider evidence stays in ignored
`load-results/et-kind-*`. Failed setup and preflight attempts are retained
separately; they are not counted as injected experiments. One Kafka diagnostic
process coincided with broker exit 137 before injection; the preflight stopped.
Even a bounded 16–64 MiB CLI heap was insufficient to safely share a broker's
container budget: a post-run diagnostic also exited 137. Diagnostics now run in
a separate, temporary 256 MiB Pod with a 96 MiB heap, no service-account token
and bounded lifetime, which is deleted on exit. This changes the preflight
diagnostic placement, not the paid run's results. Exit 137 alone is not called
a confirmed broker OOM.

Prometheus collection succeeded, but the expected Kafka consumer-lag series was
absent. The missing metric remains an observability gap; checkout convergence
alone is not a consumer-lag measurement. This experiment does not prove a live
alert, distributed tracing, voluntary eviction/PDB enforcement, real AZ/host
failure tolerance or uninterrupted checkout. All Kind nodes share the same host.

Local validation: ten rendered-profile tests, ten existing verifier tests,
five audit/fault-state tests, Python compilation and shell syntax checks
passed. The attribution tests ensure that HTTP timeouts cannot mask duplicate
charges, incorrect seat ownership or missing provider evidence. k6 script
inspection also passed with the existing 0.57 runner image.

References: [CNPG 1.26 operator TCP timeout](https://cloudnative-pg.io/docs/1.26/operator_conf/),
[CNPG failover and rejoin](https://cloudnative-pg.io/docs/1.26/failure_modes/),
[CNPG instance replacement plugin](https://cloudnative-pg.io/docs/1.26/kubectl-plugin/),
[PostgreSQL 16 connection parameters](https://www.postgresql.org/docs/16/libpq-connect.html),
[Traefik 3.4 retry middleware](https://doc.traefik.io/traefik/v3.4/middlewares/http/retry/).
Additional implementation references: [Docker pause](https://docs.docker.com/reference/cli/docker/container/pause/),
[PostgreSQL 16 backend libpq connection helper](https://github.com/postgres/postgres/blob/REL_16_STABLE/src/include/libpq/libpq-be-fe-helpers.h),
[Traefik 3.4 retry implementation](https://github.com/traefik/traefik/blob/v3.4/pkg/middlewares/retry/retry.go).
Host limit reference: [Kind known inotify issues](https://kind.sigs.k8s.io/docs/user/known-issues/).
