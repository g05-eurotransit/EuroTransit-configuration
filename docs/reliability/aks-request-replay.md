# AKS checkout request replay

## Hypothesis and execution

Repeating a checkout with the same idempotency key and payload should return
the original order ID without another reservation or charge. Reusing that key
with a changed payload should return HTTP 409.

Run `et-d21995eaaa5d4093` executed from the workstation between
the recorded run window. The configuration-owned request-replay
scenario used five iterations and one VU. Each iteration submitted a checkout,
repeated the same payload/key, submitted a changed amount with that same key,
and polled the original order to terminal state.

Fixtures used Torino to Milano (`rt-to-mi-001`), offer `of-001`, travel date
2026-10-19, seats 3D, 4A, 4B, 4C and 4D, at EUR 24.90 each. Seats were available
and unclaimed before execution. Orders ran image `bad4c04`; Inventory and
Payments ran `98bedf2` in `eurotransitregistry.azurecr.io/eurotransit`.

The fresh preflight reported `saturated: true`. The operator explicitly
authorized bypassing only the saturation gate for this bounded workstation
run. All other preflight checks, fixture claims, run locking and deadlines
remained active. The override was transient, documented in
`capacity-override.json`, and did not modify repository code. No failure was
injected and no cluster workload was added.

## Observed results

| Check | Observed result |
| --- | --- |
| Original orders | 5 `CONFIRMED` |
| Identical payload/key replays | 5 HTTP 202 responses with the original order ID |
| Changed-payload key reuse | 5 HTTP 409 responses |
| Harness assertion failures | 0 |
| Harness result / exit code | `passed: true` / `0` |
| Confirmed reservations / owned SOLD seats | 5 / 5 |
| Application authorizations | 5, one per order |
| Independently enumerated Stripe sandbox charges | 5 matching charges of EUR 24.90 |
| Unmatched provider charges | 0 |
| Correctness verifier | `VERIFIED`, zero violations |

The k6 scenario checked replay response identity and changed-payload conflicts
for every iteration. Read-only database evidence matched the five original
orders to their reservations, seats and payment records. The independent Stripe
audit exhausted all charge pages in the recorded run window, padded by two
seconds on each side, and matched references, amounts and currencies. No
duplicate successful reservation, authorization or provider effect was found
for the five run orders.

## Conclusion and limits

The hypothesis held for sequential HTTP request replay. This does not prove
simultaneous first-request idempotency, Kafka event redelivery safety, or recovery
after a mid-stage crash. The authorized saturation override also means this run
does not establish safe capacity or overload behavior. Provider completeness
applies to the audited window, not to future charges.

Prometheus returned checkout and breaker series. Telemetry remains
`NOT_VERIFIED` because Kafka consumer lag was absent; this is separate from
the passing per-order correctness verifier.

## Evidence

Restricted local artifacts are retained in
`load-results/request-replay-20261012T212438Z`: fixture input, run metadata,
capacity preflight and override, ledger, summary, database evidence, independent
provider audit, telemetry, verification and pod snapshots. Raw artifacts and
credentials are excluded from Git. Business records and fixture claims remain
intact.
