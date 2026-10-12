# AKS inventory contention — 2026-10-12

## Hypothesis and execution

Five independent checkout attempts for the same available seat, issued with two
virtual users, should yield exactly one confirmed order. The other four should
fail with `SEATS_UNAVAILABLE`, without successful reservations or charges.

Run `et-8954366acc8f4d4b` executed from the workstation between
**2026-10-12, 21:13:27–21:13:32 UTC**, using the configuration-owned k6/Python
contention scenario: five bounded iterations, two VUs, and distinct idempotency
keys. All attempts targeted Torino–Milano (`rt-to-mi-001`), offer `of-001`,
2026-10-19, seat 3C, at EUR 24.90.

Before execution, the seat was available and had no previous fixture claim.
The capacity preflight passed with `saturated: false`. Faults remained prohibited;
this experiment injected no failure and added no cluster workload. The native
harness code came from configuration revision `412adc4`.

Deployed images remained unchanged across the run: Orders `bad4c04`, Inventory
and Payments `98bedf2` in `eurotransitregistry.azurecr.io/eurotransit`.

## Observed results

| Check | Observed result |
| --- | --- |
| Accepted checkout attempts | 5 HTTP 202 responses |
| Confirmed orders | 1 |
| Losing orders | 4 `FAILED`, each with `SEATS_UNAVAILABLE` |
| Harness result / exit code | `passed: true` / `0` |
| Confirmed reservations | 1, owned by the winning order |
| Owned inventory seat | 1 `SOLD`, matching the winning reservation |
| Application authorizations | 1, for the winning order |
| Independently enumerated Stripe sandbox charges | 1 matching charge of EUR 24.90 |
| Unmatched provider charges | 0 |
| Authorizations or provider charges for losing orders | 0 |
| Correctness verifier | `VERIFIED`, zero violations |

The read-only database collector and independent Stripe audit agree with the
client outcomes. The provider audit read all charge pages in the recorded run
window, padded by two seconds on each side, and matched amount, currency and
reference to the winning order. The verifier checked fixture ownership, durable
terminal states, reservation/seat correspondence and provider effects.

## Conclusion and limits

The hypothesis held for this bounded run: exactly one contender acquired the
seat, and no losing order was charged. This is contention evidence without
injected failure; it does not establish crash safety, partition recovery, event
redelivery safety or capacity at higher concurrency. Provider completeness
applies to the audited time window, not to future charges.

Prometheus collection returned the checkout and breaker series, but telemetry
remains `NOT_VERIFIED` because Kafka consumer lag was absent. This is separate
from the passing per-order correctness audit. The final collection used the
original run window, without rerunning checkouts.

## Evidence

Restricted artifacts are retained locally in
`load-results/contention-20261012T211324Z`: fixtures, run metadata, ledger,
summary, database evidence, complete provider audit, telemetry, verification and
before/after pod snapshots. Raw artifacts and credentials are excluded from Git.
Fixture claims and business records remain intact.
