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

The [HA profile](../../operations/ha-experiment.md) uses one control plane and three workers on one workstation, Kubernetes v1.34.0, separated critical-service replicas, PostgreSQL 16 with three instances and required `ANY 1` synchronous replication, Kafka 3.9 with three persistent broker/controllers (RF 3, min ISR 2), and two shared Connect workers with three tasks. Traefik, identity, controllers and monitoring were outside the interrupted worker. All mutations targeted `kind-eurotransit`; AKS was unchanged.

Images were reused: Orders `45357ef`, other backends `98bedf2`, frontend `4364f1f`. [Image provenance](../evidence/2026-10-17/kind-ha-images.json) retains digests. Provider sandbox credentials were transferred in memory under authorization; raw credentials and financial identifiers remain outside Git.

Preflight requires Ready separated replicas, no node memory pressure, host headroom, full Kafka ISR, REST and custom-resource task health, physical standby streaming and initialized failover slots. PostgreSQL Ready counts alone do not prove a synchronous standby. The [runner](../../../scripts/kind-ha-experiment.py) and runbook define injection, watchdog and cleanup.

## Financial and availability interpretation

Two original polling timeouts later confirmed in the separate final-state audit; their HTTP/client evidence was preserved. The three failed admission attempts did not become successful client responses. The final audit checked amounts, reservation/seat ownership and independently enumerated provider effects.

A [Catalog-only investigation](ha-failover.md) attributed the 504 to the stopped replica. A controlled process stall reproduced five gateway timeouts while the healthy replica returned 52/52 successful responses. Errors stopped after endpoint withdrawal. This supports the routing diagnosis and does not erase the original errors or establish availability compliance.

The final [Kafka snapshot](../evidence/2026-10-17/kind-ha-final-kafka.json) found 194 partitions with RF 3/full ISR and zero sampled committed lag for Orders/Notifications. Nine empty refund/DLT partitions had no committed offsets, so their lag was not a numeric measurement. Continuous Prometheus consumer-lag series was absent during this fault. The later [Notifications experiment](notifications-lag.md) verifies that signal separately.

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

The [final health snapshot](../evidence/2026-10-17/kind-ha-final-health.json) records all workers running, both standbys streaming with zero replay lag and about 3.4 GiB host memory available. Smoke passed and temporary diagnostics were removed. The experiment does not establish real host/AZ tolerance, uninterrupted checkout, voluntary eviction/PDB behavior, a live alert or distributed tracing. Every Kind node shares one host.

## Evidence

[Sanitized run evidence](../evidence/2026-10-17/kind-ha-experiments.json) preserves run IDs, original outcomes, configuration/artifact hashes and resource observations. Raw API/database/provider artifacts remain in ignored `load-results/et-kind-*`. Skipped setup/preflight attempts are not counted as injected experiments. Local profile, verifier and attribution checks passed; they do not replace the live results above.

## Catalog failover verification

Outcome: the timeout was reproduced and attributed to an unavailable backend
still present in the gateway's routing set. No functional Catalog defect was
observed on the tested `GET /api/catalog/routes` path. Catalog failover is
demonstrated with measured transient errors. The specification does not require
zero errors during every failure: these timeouts must be assessed against the
applicable availability/latency SLO and error budget, rather than treated as an
automatic failure of the failover requirement. This check neither certifies all
Catalog functionality nor establishes SLO compliance. The original stricter
zero-error diagnostic result remains recorded unchanged.

### Historical timeout

The access log for worker-stop run `30677fd63d` records a request starting at
14:35:15 UTC, HTTP 504 after 1083 ms, with backend `10.244.3.21:8080`.
That was the Catalog replica on the worker stopped at 14:34:45.174. The runner
observed Node NotReady only at 14:35:32.776. Thus the gateway attempted that
replica approximately 30 seconds after its worker had stopped, while Kubernetes
had not yet withdrawn it. The historical response is a gateway timeout, not an
HTTP error returned by a running Catalog process on that stopped worker.

### Controlled Catalog-only check

Run `catalog-check-20261017T202233Z`, context `kind-eurotransit`, kept nodes,
PostgreSQL, Kafka and the other services running. No checkout or payment was
submitted; no application image, ingress configuration or probe was changed.

Two independent request loops ran every 250 ms after each response: one through
public Traefik and one directly to the healthy Catalog Pod through a private
localhost port-forward. All successful responses were validated as nonempty
JSON arrays and had identical body hashes.

After a six-second baseline, SIGSTOP suspended only the Catalog process in Pod
`catalog-649f7fd5d-n6x8b` on worker3, IP `10.244.2.12`. An independent watchdog
issued SIGCONT after 12 seconds, verifying the immutable container ID and process
ID before resuming it. The main process recorded recovery at 13.12 seconds and
observed another nine seconds. Phase labels refer to request start time; the
fault-labelled phase includes the short interval between watchdog resumption
and the main process recording recovery. Endpoint readiness was sampled separately.

| Path | Baseline | Fault-labelled phase | Recovery |
| --- | --- | --- | --- |
| Public ingress | 24/24 HTTP 200 | 25 HTTP 200, **5 HTTP 504** | 35/35 HTTP 200 |
| Healthy Pod directly | 24/24 HTTP 200 | **52/52 HTTP 200** | 35/35 HTTP 200 |

All five gateway access records name the suspended backend `10.244.2.12:8080`.
They took approximately 1000 to 1065 ms, consistent with the configured one-second
response-header timeout. The healthy control's maximum latency during the fault
was 6.15 ms; no successful response had an invalid or divergent body.

The first sampled Ready=false/endpoint withdrawal was 7.509 seconds after
SIGSTOP. All 21 subsequent ingress requests in the fault-labelled phase returned
200. No further timeout appeared during recovery. The Pod UID and container ID
were unchanged, restart count remained zero, and both Catalog Pods/endpoints
were Ready after cleanup. The private port-forward was terminated.

### Interpretation

The current availability gap is between a backend becoming unresponsive and its
removal from routing. The readiness probe did detect the suspended process and
traffic then used the healthy replica. The surviving Catalog instance continued
to return correct data throughout the experiment.

The configured two-attempt transport retry did not rescue these response stalls.
Traefik's retry is not a general retry of HTTP error responses; the observed 504s
must remain visible. Merely increasing its attempt count is not a demonstrated
fix. Faster application readiness may shorten the process-stall window, but it
does not by itself shorten node-failure detection when the kubelet is stopped.

The follow-up therefore belongs to routing/failure detection and handling of
in-flight read failures. The evidence does not currently justify changing Catalog
business logic. Detection latency and acceptable client errors still need to be
assessed against team-owned availability objectives.

[Sanitized observations](../evidence/2026-10-17/catalog-failover-verification.json)
contain timings, request counts, backend attribution and raw-artifact hashes.
Raw request/access logs, endpoint samples and the exact diagnostic script remain
in ignored `load-results/catalog-check-20261017T202233Z/`.

Reference: [Traefik 3.4 transport retry semantics](https://doc.traefik.io/traefik/v3.4/middlewares/http/retry/).
