# Inventory kill and duplicate delivery — 2026-10-12

## Steady state and proposed hypothesis

The preceding contention and HTTP replay runs passed. This experiment adds a
verified process failure during a reservation SQL operation. Proposed hypothesis:
five buyers competing for one seat must produce at most one confirmed purchase,
one active reservation and one provider charge despite a crash and duplicate
delivery. The team must review the hypothesis and acceptable recovery impact.

## Injection and observations

Run `et-inv-c39f322e5588` submitted five attempts with two VUs for one fresh
fixture. A separate PostgreSQL transaction held that fixture's seat row for
45 seconds, then rolled back independently. It performed no business writes.
This synchronization barrier made the reservation overlap observable.

At **22:14:26.055 UTC**, PostgreSQL showed an Inventory connection waiting on
that transaction's lock; its query had started at 22:14:25.454 UTC. The observer
matched `host(client_addr)` to the Inventory pod IP and checked
`pg_blocking_pids`. A UID-conditioned force deletion then killed
`inventory-74b957b86-7wcht`, UID
`17b32ff0-5677-44be-95ab-6753fc6a8987`. Its replacement
`inventory-74b957b86-ft85v` became Ready before recovery replay.

| Observation | Result |
| --- | --- |
| Initial client verdict | Failed (exit 99); five orders nonterminal at collection |
| Recovery | Exact five original order-placed events replayed once after replacement readiness |
| Final order states | One CONFIRMED, four FAILED with SEATS_UNAVAILABLE |
| Subsequent same-key HTTP retries | Five HTTP 202 responses, each retaining its original order ID |
| Independent final provider audit | One matching sandbox charge, zero unmatched charges |
| Read-only correctness verification | VERIFIED, zero violations, before and after HTTP retries |

Initial ledgers and failed harness results remain unchanged. Final verification
uses a labelled derived final-state audit, fresh API observations, database
invariants and an independent provider window covering recovery and HTTP retries.
No records were deleted or corrected in SQL. Resource saturation was waived for
this bounded run; fixture ownership and health checks remained active.

Two earlier synchronization attempts did not kill a pod: their observer compared
`client_addr::text` (which includes `/32`) with an unmasked IP. They are excluded
from crash proof, and their pending orders were recovered and independently
audited. The corrected address comparison enabled the actual fault above.

## Conclusion and follow-up

The no-oversell and no-double-charge invariants held under an observed in-flight
crash, duplicate events and HTTP retries. Checkout completion within the client
deadline did not hold. Recovery required operator replay; this result establishes
correctness after controlled recovery, not automatic recovery or continuous
availability. Review exhausted-delivery handling before declaring the broader
resilience objective complete.

## Evidence

Restricted fault metadata, row-lock observations and HTTP replay responses:
`.resilience-evidence/chaos-20261012/inventory-kill-20261012T221416Z` in the
workspace. Original load artifacts:
`load-results/inventory-kill-20261012T221416Z`. Final audits:
`load-results/inventory-kill-20261012T221416Z-final-audit-20261012T221630Z`
and `load-results/inventory-kill-and-http-replay-final-audit-20261012T221728Z`.
Raw identifiers and provider references are excluded from Git.
