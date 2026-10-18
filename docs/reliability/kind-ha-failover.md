# Kind worker loss and PostgreSQL failover

Worker termination demonstrated primary promotion and automatic checkout recovery with transient client errors. Five committed purchases finally confirmed with five independently audited charges and no unmatched charges. RTO/SLO compliance was not assessed. The original strict harness verdict remains failed; its zero-error diagnostic condition is separate from the project's failover requirement.

## Result

| Observation | Final worker-stop run `30677fd63d` |
| --- | --- |
| Declared worker stop | 180 s |
| Node NotReady | T+47.60 s |
| New PostgreSQL primary | T+51.86 s |
| Surviving synchronous quorum sampled | T+70.30 s |
| Checkout confirmation with worker still stopped | T+179.62 s, one observation close to the stop boundary |
| Worker restart observed | T+181.86 s |
| Final committed purchases | 5/5 confirmed, matching reservations/sold seats and five distinct Stripe charges; full invariant audit passed |
| Original client results | 3 confirmations, 2 polling timeouts, 3 technical admission failures across 8 attempts |
| Catalog | 250 HTTP 200 and one 504; p95 615.43 ms |
| Harness result | k6 exit 99; `haObserved=false`; operator runner exit 1 |

No connector restart, event replay or business-row repair was performed during the final run. A first automatic Debezium restart occurred before PostgreSQL was usable; subsequent policy backoff delayed recovery. One successful observation near 180 s is not a reliable 180 s recovery guarantee.

## Environment and hypothesis

The proposed hypothesis was that worker loss preserves Kafka quorum, promotes a standby and restores checkout before worker return, with every committed purchase converging without oversell or duplicate payment. No numeric team recovery objective was adopted by the experiment.

The [HA profile](kind-ha-runbook.md) uses one control plane and three workers on one workstation, Kubernetes v1.34.0, separated critical-service replicas, PostgreSQL 16 with three instances and required `ANY 1` synchronous replication, Kafka 3.9 with three persistent broker/controllers (RF 3, min ISR 2), and two shared Connect workers with three tasks. Traefik, identity, controllers and monitoring were outside the interrupted worker. All mutations targeted `kind-eurotransit`; AKS was unchanged.

Images were reused: Orders `45357ef`, other backends `98bedf2`, frontend `4364f1f`. [Image provenance](evidence/2026-10-17/kind-ha-images.json) retains digests. Provider sandbox credentials were transferred in memory under authorization; raw credentials and financial identifiers remain outside Git.

Preflight requires Ready separated replicas, no node memory pressure, host headroom, full Kafka ISR, REST and custom-resource task health, physical standby streaming and initialized failover slots. PostgreSQL Ready counts alone do not prove a synchronous standby. The [runner](../../scripts/kind-ha-experiment.py) and runbook define injection, watchdog and cleanup.

## Financial and availability interpretation

Two original polling timeouts later confirmed in the separate final-state audit; their HTTP/client evidence was preserved. The three failed admission attempts did not become successful client responses. The final audit checked amounts, reservation/seat ownership and independently enumerated provider effects.

A [Catalog-only investigation](kind-catalog-failover.md) attributed the 504 to the stopped replica. A controlled process stall reproduced five gateway timeouts while the healthy replica returned 52/52 successful responses. Errors stopped after endpoint withdrawal. This supports the routing diagnosis and does not erase the original errors or establish availability compliance.

The final [Kafka snapshot](evidence/2026-10-17/kind-ha-final-kafka.json) found 194 partitions with RF 3/full ISR and zero sampled committed lag for Orders/Notifications. Nine empty refund/DLT partitions had no committed offsets, so their lag was not a numeric measurement. Continuous Prometheus consumer-lag series was absent during this fault. The later [Notifications experiment](kind-notifications-lag.md) verifies that signal separately.

## Complementary failed diagnostics

These experiments explain repairs and remaining failure modes. They add no required fault scenario and their failures remain in the evidence.

| Run suffix | Fault / condition | Recorded outcome |
| --- | --- | --- |
| `f910496a33` | 90 s process freeze, initial HA profile | Promotion 49.66 s; 1/8 client confirmations; none during freeze; 0/179 Catalog errors |
| `a7fe5c86db` | Freeze, bounded pool; non-streaming standby escaped preflight | Promotion 51.85 s; 3/8 client confirmations; none during freeze; 8/139 Catalog errors |
| `1d68d06bdb` | Freeze, fresh streaming standby and Catalog GET retry | Promotion 51.81 s; 3/8 client confirmations; none during freeze; 0/179 Catalog errors |
| `9e174ad41d` | Freeze, standby TCP timeout 5 s and a Catalog replica affected | Promotion 56.14 s; 3/8 client confirmations; none during freeze; 10/161 Catalog errors |
| `7788dd4e18` | 90 s worker stop, connector tasks failed | Promotion 47.49 s; no checkout confirmation during stop; 180/180 Catalog reads; only 1/5 committed orders confirmed by original audit deadline |

All freeze client runs exited 99. Freeze runs 1/2/3/4 finally had 1/6/6/5 confirmed purchases with matching distinct charges. For timed-out requests, a SELECT-only audit recovered order IDs through exact idempotency keys. The ordinary verifier retained `invalid_acceptance_evidence`; financial correctness was assessed separately. No manual business-row repair was used.

The earlier stop audit found two unattributed successful EUR 49.90 sandbox charges outside its EUR 24.90 fixtures. Their origin was unproven and the audit remained incomplete. On restart, kube-proxy failed with `too many open files`; an authorized, runtime-only host inotify increase and Pod recreation restored service. That assisted repair is outside automatic recovery evidence. Fresh baselines passed afterward; the final 180 s run recovered without repeating that repair.

## Corrections and remaining limits

- Preflight now verifies actual physical streaming and a fixed replay position. Divergent standby replacement used the version-matched CNPG plugin with `--keep-pvc`; three old PVCs remain preserved.
- HA-only R2DBC validation/pool waits and `STANDBY_TCP_USER_TIMEOUT=5000` did not resolve process-freeze stalls. New-primary writes waited on `IPC/SyncRep` while no surviving physical standby streamed. A frozen process retains kernel networking, unlike a stopped worker; connection-stall attribution remains an inference without packet capture.
- HA operator reconciliation is 15 s; the finite automatic-restart policy retains its own backoff. Connect reassignment and offset flush are bounded separately. Catalog ingress retries apply only to GET transport failures, never purchase POSTs. These settings do not define a recovery SLO.
- Slot checks accept an active owner only when it is the `pg_failover_slots worker`, with initialized restart/confirmed LSNs; an external consumer is refused.
- Kafka diagnostics moved to a temporary, bounded Pod after in-broker CLI processes exited 137. Exit 137 alone was not classified as a proven broker OOM.

The [final health snapshot](evidence/2026-10-17/kind-ha-final-health.json) records all workers running, both standbys streaming with zero replay lag and about 3.4 GiB host memory available. Smoke passed and temporary diagnostics were removed. The experiment does not establish real host/AZ tolerance, uninterrupted checkout, voluntary eviction/PDB behavior, a live alert or distributed tracing. Every Kind node shares one host.

## Evidence

[Sanitized run evidence](evidence/2026-10-17/kind-ha-experiments.json) preserves run IDs, original outcomes, configuration/artifact hashes and resource observations. Raw API/database/provider artifacts remain in ignored `load-results/et-kind-*`. Skipped setup/preflight attempts are not counted as injected experiments. Local profile, verifier and attribution checks passed; they do not replace the live results above.
