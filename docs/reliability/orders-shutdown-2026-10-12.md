# Orders SIGTERM under checkout traffic — 2026-10-12

## Steady state and proposed hypothesis

Orders `bad4c04` was Ready with one replica. Proposed hypothesis: SIGTERM flips
readiness while work drains, stops consumers cooperatively and preserves the
accepted orders without double processing. Continuous availability of a single
replica is assessed separately. The team must review this lifecycle hypothesis.

## Signal, drain and recovery

Run `et-stop-6bacc86a7bb7` made six ramp attempts with two VUs. A read-only snapshot
immediately before the signal found one CONFIRMED order and another in
**CONFIRMING_INVENTORY**. At **22:41:11.069 UTC**, SIGTERM was sent directly to
Java PID 1 in pod `orders-56b98b8cff-bxg97`; its UID was checked beforehand.
This exercises the application shutdown path, bypassing the Pod preStop sleep.
It is not a complete Pod termination/readiness-to-endpoint-removal proof.

| Observation | Result |
| --- | --- |
| Direct readiness HTTP 503 | 22:41:11.602 UTC; body `OUT_OF_SERVICE` |
| Consumer-stop log messages | 22:41:11.741–11.868 UTC |
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
into `dev` on 2026-10-08. Its local evidence is not AKS proof. The accompanying
lifecycle document describes a per-record `runBlocking` failure domain with
Kafka-owned shutdown; it does not claim a detached background coroutine scope.

## Conclusion and evidence

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
