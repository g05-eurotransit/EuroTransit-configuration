# Orders Pod shutdown

## Result

**PASS for this bounded shutdown/recovery experiment.** All four fresh checkout
requests returned HTTP 202 and reached `CONFIRMED` within the original 30-second
client polling deadline. The original verifier and the separately labelled final
and server-attribution audits passed. Independent Stripe sandbox extraction was
complete: four authorizations, one per order, no unmatched charge. Inventory
reservation/seat and payment invariants passed the existing verifier.

This run followed a separately recorded, manually authorized CDC baseline
repair. That repair is not counted as automatic shutdown recovery.

## Method and observations

Run `et-kind-shutdown-3663800ab3`, context `kind-eurotransit`, existing published
Orders image `eurotransit/orders:kind-ha`; no application code change.
The team must review the proposed operational hypothesis: terminating the
listener Pod while a reservation is in progress should withdraw its HTTP
endpoint, stop within its grace period and allow durable work to converge
without duplicate reservation or charge.

A fresh fixture's seat row was held with `SELECT FOR UPDATE` for 18 seconds,
with a 24-second statement timeout and unconditional `ROLLBACK`; no business row
was modified by this barrier. The listener log identified the processing Pod and
the public order API showed `RESERVING` before normal Pod deletion at
21:00:38.055 UTC. No force deletion or grace-period override was used.

| Observation | Evidence |
| --- | --- |
| Endpoint withdrawal | First sampling cycle overlapping DELETE observed the old endpoint `ready=false` |
| Readiness refuses traffic | Direct old-Pod probe first returned 503 at 21:00:48.241 UTC, after the configured 10-second preStop |
| Listener lifecycle | Pending record remained in retry; consumer left the group and logged `Consumer stopped` |
| HTTP drain | `Graceful shutdown complete` at 21:00:50.228 UTC |
| Old container exit | Exit 143 at 21:00:52.636 UTC, about 14.6 seconds after DELETE, within the 45-second Pod grace |
| Recovery | Two Orders replicas ready and harness complete by 21:01:04.972 UTC |

Endpoint observation timestamps mark the start of a sampling cycle, before its
API reads. The first cycle overlaps DELETE; it is not evidence that withdrawal
preceded DELETE or an exact subsecond propagation measurement. Readiness 503
was measured directly through the old Pod port-forward, independently from
normal ingress withdrawal.

Observed confirmation durations were 19.354, 3.881, 1.935 and 2.339 seconds.
Acceptance durations were approximately 49.7, 26.6, 23.1 and 753.6 ms. The
deliberate lock explains the first order's delay; these four samples do not
establish compliance with the rolling latency SLO.

## Conclusion and scope

This run demonstrates ordinary Pod endpoint withdrawal, readiness refusal,
graceful process termination and successful recovery of an interrupted durable
checkout without duplicate financial effects. No SIGKILL/OOM exit was observed.
It does not exercise every coroutine cancellation branch, prove absence of
all possible orphan tasks, or replace the unit/integration lifecycle checks.
No retry, timeout, admission-control or pool setting was added for this test.

The exclusive test lock and owned port-forward/log streams were removed; fixture
claims and business/audit rows remain. Raw artifacts are private under
`load-results/et-kind-shutdown-3663800ab3`; the [sanitized result and
hashes](evidence/2026-10-17/orders-pod-shutdown.json) are versioned here.
