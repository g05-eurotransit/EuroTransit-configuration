# Payments latency experiment

The current run tests the Orders recovery policy from application #139/#141, with an earlier-revision comparison retained below. A 45-second delay also restarted Payments: five of six purchases confirmed automatically and one required abandonment/refund. The original client run failed; this is distinct from the [latency-only experiment](payments-latency.md).

## Steady state and hypothesis

Orders ran `45357ef` (application `dev` with #139 and #141); Inventory and Payments ran `98bedf2`.
The reconciliation controllers were paused. The #46 preflight reported saturation,
so the harness proxy path (+576 MiB, a published proxy image, two GitOps changes and two Orders
rollouts) was not feasible; **a saturation override was authorized by the Orders owner** and the
earlier fault method was repeated: `load-tests/run.py` launched directly, fault injected by the operator.

Hypothesis: a slow Payments opens the Orders Payments breaker and leaves Catalog available; after the
fault is removed, the affected orders reach a terminal state within about a minute without an operator
(#139's retry budget), and any order that outlasts the budget is recovered through the runbook.

## Fault and observations

An ephemeral container in the running Payments pod, with only `NET_ADMIN` (`kubectl debug
--profile=netadmin`) and the netshoot image pinned to the pinned digest
`sha256:147f2c4cb0aa7a741151bce2bfef71d9e1a04631636e24665ee2a5ed799feb47`, attached a `netem` filter
delaying IPv4 TCP source port 8080 by 4000 ms from **15:52:21 to 15:53:06 UTC**; the container removed
the qdisc itself after 45 seconds and the original `noqueue` qdisc was restored. A one-second sampler
read the Orders Payments breaker state, a public Catalog probe and the Payments pod readiness.

The breaker started `CLOSED`: three warm-up orders (15:50 to 15:51) closed it after the earlier attempts
below. Run `et-pay3-20261016` (six attempts, two VUs) started at 15:52:25; recovery run
`et-pay3-rec-20261016` (two sequential attempts) at 15:54:21.

| Observation | Result |
| --- | --- |
| Payments breaker | `OPEN` first at 15:52:32; `OPEN`/`HALF_OPEN` alternated until `CLOSED` at 15:54:17 |
| Catalog probes during the fault | 26/26 HTTP 200, p95 183.5 ms (69/69 until 15:54:25) |
| Payments pod | NotReady 15:52:29 to 15:53:37 and **restarted once** (~15:53:05): the delay also times out its 2 s probes |
| Fault-run client result | Failed (exit 99): three orders nonterminal at the deadline |
| Orders placed during or after the fault | 5 of 6 `CONFIRMED` **automatically**, the last at 15:54:18.6 (≈72 s after the fault ended) |
| First order (placed 15:52:26) | Payments authorized at 15:52:27 but answered late; retry budget exhausted → `DELIVERY_EXHAUSTED` at 15:53:35 |
| Recovery run | 2/2 `CONFIRMED` (1.1 to 1.8 s) |
| Independent Stripe sandbox audit | 6 and 2 matching charges, zero unmatched |
| Verifier (derived final-state ledgers) | Recovery: VERIFIED. Fault run: one violation, `unexpected_checkout_outcome` (the abandoned order, below); all reservation, seat and payment checks pass |

**Operator recovery through the runbook.** The incident appeared in `GET /api/orders/reconciliation`.
The redrive was sent at 16:02:39, thirteen seconds after the order's seat hold expired (16:02:26), and
was refused with `409 RESERVATION_HOLD_EXPIRED` (audit `reconciliation.redrive rejected`). The operator
then abandoned it (step 5b) at 16:08:19 (`202`, `COMPENSATING`; audit `reconciliation.abandon
accepted`): Payments refunded the charge at 16:08:21 (`payment_refunds` `REFUNDED`), the reservation
was released, the order ended `FAILED` / `CHECKOUT_FAILED` at 16:08:22 and the incident closed. The
provider audit enumerates charges, not refunds, so it lists that charge as succeeded; the refund is
evidenced by Payments' refund row and log.

**Earlier attempts, excluded from the result.** Attempt 1: the six orders completed in 14 s before the
fault started (15:43:10 to 15:44:09); Payments still went NotReady and restarted with no traffic.
Attempt 2 (fault 15:47:17 to 15:48:02): the harness reused attempt 1's run id, so all six requests were
correctly refused as idempotency conflicts (`409`) and no order was created; one order of an
interrupted recovery run, placed at 15:47:36 during the fault, was confirmed automatically at 15:48:39.

## Comparison with

| | Earlier `bad4c04` | Current `45357ef` |
| --- | --- | --- |
| Fault | 4000 ms on Payments sport 8080, 45 s | Same method and image |
| Breaker | `OPEN`, `HALF_OPEN`, `CLOSED` observed | Same |
| Catalog | 129/129, p95 137.5 ms | 26/26 in the fault, p95 183.5 ms |
| Fault-run orders | Six `PAYMENT_PENDING`; explicit replay needed | **Five confirmed automatically**; one to the operator |
| Operator path | Replay of raw `order-placed` events | **Runbook**: listed, redrive refused (late), abandoned, refunded |
| Recovery run | One confirmed, one pending | 2/2 confirmed |

The #55 gate on automatic recovery holds for most orders; the one order that outlasted the budget was
settled through the runbook rather than by replaying raw events.

## Conclusion and follow-up

Breaker activation and Catalog isolation held, and automatic convergence replaced replay for five of
six orders. To record:

- **This method is latency plus a restart.** The delay also times out Payments' readiness and liveness
  probes, so Payments is removed from its Service and restarted once within the 45 s; the same was very
  likely true in the recorded run. A pure-latency variant would exclude probe traffic from the filter.
- **One order outlasted the budget** (Payments slow, then restarting, for about 75 s in total).
- **The operator missed the redrive window by 13 s.** On AKS no client allows a password grant, so the
  operations token had to be copied from the browser, and it expires after about five minutes. The
  runbook's response objective (redrive before the hold expires) is hard to meet on the cluster without
  a command-line way to obtain an operations token.

## Evidence

Run artifacts, injector logs, one-second samples, collector output, provider audits and verifications
are kept outside Git in the Orders owner's workspace (`resilience-evidence-2026-10-16/payments-latency-*`).
Raw identifiers and provider references are excluded from Git.

## Complementary recovery finding

An earlier latency experiment kept Catalog healthy (129/129 reads) and observed breaker OPEN/HALF_OPEN, but its eight accepted orders required explicit event replay. That result is superseded for the current automatic recovery policy; the [incident review](../incidents/payments-recovery.md) retains the diagnosis. It is not evidence of automatic convergence.
