# Inventory kill and duplicate delivery

The current run tests the Orders recovery policy from application #139/#141, with an earlier-revision comparison retained below. Five competing purchases converged automatically in 73 s: one confirmation, four sold-out refusals and one independently audited charge. The initial client deadline failed.

## Steady state and hypothesis

Orders ran `45357ef` (application `dev` with #139 `5674a3c` and #141 `0bb8d75`, deployed for the run); Inventory and Payments ran `98bedf2`. The reconciliation controllers
were paused (`scripts/demo-pause-controllers.sh`, 14:43:58 to 16:13:05 UTC) to free memory.

The #46 preflight still reported saturation (node `vms210` at 100 to 106 % of allocatable), so the runner
refused a two-VU contention run and `fault.py` refused the kill. **A saturation override was
authorized by the Orders owner**, using the earlier method: `load-tests/run.py` was launched directly with
the same scenario, and the pod was deleted by the operator with the same UID-conditioned forced
delete `fault.py` uses. Real headroom was about 0.9 GiB per node against a 100 MiB eviction threshold.

Hypothesis: five buyers competing for one seat produce at most one
confirmed purchase, one active reservation and one provider charge despite a crash during the
reservation and duplicate delivery. Added for this re-run: with #139's dependency retry budget (six
jittered redeliveries, about 1.5 to 2.3 minutes) the orders reach a terminal state without an operator.

## Injection and observations

Run `et-inv-20261016` submitted five contention attempts with two VUs for one fresh fixture. A
separate PostgreSQL transaction held that fixture's seat row (`SELECT … FOR UPDATE`, `pg_sleep(45)`,
`ROLLBACK`; no writes) from **15:25:17.0 to 15:26:02 UTC**. An earlier barrier at 15:22:31 expired
before any load and had no effect.

At **15:25:22.58 UTC** PostgreSQL showed an Inventory connection (pid 348, the Inventory pod IP)
waiting on that transaction's lock (`pg_blocking_pids` = the barrier); its query had started at
15:25:22.45. The operator then force-deleted `inventory-74b957b86-2wx9x` (UID
`dfa76c59-d7bd-4e81-a487-7eaf0ef3d7ac`, `gracePeriodSeconds: 0`, UID precondition) at about
**15:25:28**. Its replacement `inventory-74b957b86-262bc` started at 15:25:28 and was Ready at
15:26:04. No operator action followed.

| Observation | Result |
| --- | --- |
| Initial client verdict | Failed (exit 99): four orders nonterminal at the client deadline, one `SEATS_UNAVAILABLE` |
| Orders retries of the winning order | Attempts at 15:25:22, :30, :33, :36.7, :44.4, 15:26:03.4 and :31.1 |
| Winning order | `CONFIRMED` at 15:26:34.6, on the **sixth and last** redelivery |
| Other four | `FAILED` / `SEATS_UNAVAILABLE` at 15:26:35.2 to 35.7, processed after the winner on the same consumer |
| All five terminal | 73 s after the first acceptance, ~67 s after the kill, ~33 s after the barrier rollback |
| Reconciliation incidents | **None opened** |
| Database | One `CONFIRMED` reservation, the seat `SOLD` and linked to it, one `AUTHORIZED` payment |
| Independent Stripe sandbox audit | One matching charge, zero unmatched charges (window 15:25:18 to 15:26:40) |
| Correctness verifier (derived final-state ledger) | **VERIFIED, zero violations** |

The original ledger and its failed verdict are kept unchanged. The final verification uses a labelled
derived final-state ledger (each order re-read from the public API after convergence) and the provider
audit, as in the recorded run. No records were edited and nothing was replayed.

## Comparison with

| | Earlier `bad4c04` | Current `45357ef` |
| --- | --- | --- |
| Fault | Kill during a lock-held reservation | Same |
| Client verdict | Failed (deadline) | Failed (deadline) |
| Convergence | Operator replay of the five original `order-placed` events | **Automatic**, 73 s, no incident |
| Final states | 1 `CONFIRMED`, 4 `SEATS_UNAVAILABLE` | Same |
| Provider charges | 1, zero unmatched | 1, zero unmatched |
| Verifier | VERIFIED after replay | VERIFIED without replay |

The #55 gate on automatic recovery holds for this fault on the new code.

## Conclusion and follow-up

The no-oversell and no-double-charge invariants held under an observed in-flight crash, and the
orders converged without an operator. Two limits to record:

- **The margin was zero.** The winner was confirmed on the last of its six redeliveries. A few
  seconds more of lock or of Inventory start-up would have dead-lettered it as `DELIVERY_EXHAUSTED`,
  leaving it to the operator runbook (application `docs/operations/orders-recovery-runbook.md`).
- **Head-of-line waiting.** While the winner was being retried, the other four orders on the same
  consumer waited behind it, as the runbook documents.

Checkout completion within the client deadline still does not hold; this is a recovery result, not a
continuous-availability one.

## Evidence

Run artifacts, barrier and observer logs, collector output, provider audit and both verifications are
kept outside Git in the Orders owner's workspace (`resilience-evidence-2026-10-16/inventory-kill-run`
and `inventory-kill-fault`). Raw identifiers and provider references are excluded from Git.
