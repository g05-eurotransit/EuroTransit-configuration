# AKS dependency resilience

Each section records a separate experiment with its own verdict, tested configuration and evidence.

| Scenario | Result and material limit | Details |
| --- | --- | --- |
| Inventory crash | One winner/four sold-out, one charge; automatic convergence in 73 s on the last redelivery. Original client deadline failed. | [Inventory crash](#inventory-crash) |
| Kafka disruption | Four automatic confirmations after healing; original client deadline failed. | [Kafka disruption](#kafka-disruption) |
| Payments latency only | Six automatic confirmations under 4 s delay for 45 s; Catalog/readiness 50/50. Two original client polling timeouts remain failures. | [Pure latency](#payments-latency) |
| Payments latency + restart | Five of six automatically confirmed; one abandoned/refunded. This compound fault stays separate from latency-only proof. | [Latency and restart](#payments-latency-and-restart) |
| Notifications stopped | Four confirmations during the stop, independent audits passed and consumer caught up. | [Notifications outage](#notifications-outage) |

<a id="inventory-crash"></a>

## Inventory kill and duplicate delivery

The current run tests the Orders recovery policy from application #139/#141, with an earlier-revision comparison retained below. Five competing purchases converged automatically in 73 s: one confirmation, four sold-out refusals and one independently audited charge. The initial client deadline failed.

| Report element | Summary |
| --- | --- |
| Hypothesis (accepted by the team) | Five buyers competing for one seat produce at most one confirmed purchase, one active reservation and one charge despite an Inventory crash mid-reservation and duplicate delivery; with #139's retry budget the orders reach a terminal state without an operator. |
| Steady state | Orders `45357ef` (#139, #141), Inventory and Payments `98bedf2`, all Ready; reconciliation controllers paused; saturation override authorized by the Orders owner. |
| Injected fault | The seat row locked for 45 s, then the Inventory pod force-deleted while a reservation waited on that lock. |
| Observations | One `CONFIRMED` on the sixth redelivery, four `SEATS_UNAVAILABLE`, all terminal in 73 s with no incident; one charge, zero unmatched ([details](#inventory-crash-injection-and-observations)). |
| Conclusion | Held: no oversell, no double charge, automatic convergence. The client completion deadline failed. |
| Follow-up change | No code change. The zero retry margin and head-of-line waiting stay documented limits. |

<a id="inventory-crash-steady-state-and-hypothesis"></a>

### Steady state and hypothesis

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

<a id="inventory-crash-injection-and-observations"></a>

### Injection and observations

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

<a id="inventory-crash-comparison-with"></a>

### Comparison with

| | Earlier `bad4c04` | Current `45357ef` |
| --- | --- | --- |
| Fault | Kill during a lock-held reservation | Same |
| Client verdict | Failed (deadline) | Failed (deadline) |
| Convergence | Operator replay of the five original `order-placed` events | **Automatic**, 73 s, no incident |
| Final states | 1 `CONFIRMED`, 4 `SEATS_UNAVAILABLE` | Same |
| Provider charges | 1, zero unmatched | 1, zero unmatched |
| Verifier | VERIFIED after replay | VERIFIED without replay |

The #55 gate on automatic recovery holds for this fault on the new code.

<a id="inventory-crash-conclusion-and-follow-up"></a>

### Conclusion and follow-up

The no-oversell and no-double-charge invariants held under an observed in-flight crash, and the
orders converged without an operator. Two limits to record:

- **The margin was zero.** The winner was confirmed on the last of its six redeliveries. A few
  seconds more of lock or of Inventory start-up would have dead-lettered it as `DELIVERY_EXHAUSTED`,
  leaving it to the operator runbook (application `docs/operations/orders-recovery-runbook.md`).
- **Head-of-line waiting.** While the winner was being retried, the other four orders on the same
  consumer waited behind it, as the runbook documents.

Checkout completion within the client deadline still does not hold; this is a recovery result, not a
continuous-availability one.

<a id="inventory-crash-evidence"></a>

### Evidence

Run artifacts, barrier and observer logs, collector output, provider audit and both verifications are
kept outside Git in the Orders owner's workspace (`resilience-evidence-2026-10-16/inventory-kill-run`
and `inventory-kill-fault`). Raw identifiers and provider references are excluded from Git.

<a id="kafka-disruption"></a>

## Kafka response partition

| Report element | Summary |
| --- | --- |
| Hypothesis (accepted by the team) | A bounded broker-response partition delays checkout, but publication and consumption recover once connectivity returns, without operator replay or duplicate side effects. |
| Steady state | The Orders consumer group at zero committed lag on all three `order-placed` partitions. |
| Injected fault | 100% loss of the sole broker's outbound TCP responses from port 9092 for 40 s. |
| Observations | 4/4 `CONFIRMED` after healing without replay; four matching charges, zero unmatched; lag back to zero; Catalog 102/102 ([details](#kafka-disruption-fault-and-observations)). |
| Conclusion | Held for convergence and money-path invariants. The client completion deadline failed. |
| Follow-up change | The lag collector falls back to the Spring Kafka client metric when the exporter is absent ([telemetry](#kafka-disruption-consumer-lag-telemetry)). |

<a id="kafka-disruption-steady-state-and-proposed-hypothesis"></a>

### Steady state and hypothesis

The Orders consumer group had zero committed-offset lag on all three
`order-placed` partitions. Hypothesis: a bounded broker-response
partition delays checkout but durable publication and consumption recover after
connectivity returns, without operator event replay or duplicate side effects.
The team accepted this hypothesis.

<a id="kafka-disruption-fault-and-observations"></a>

### Fault and observations

An ephemeral, digest-pinned netshoot container in the sole broker pod applied
100% loss to outbound IPv4 TCP responses from port 9092, from **22:20:55 to
22:21:35 UTC**. It used NET_ADMIN without privilege or host networking. The
independent 40-second timer removed the filter; the injector log confirms the
original `noqueue` qdisc. Localhost administrative commands and KRaft ports were
outside the filter. This tests a client/broker response partition, not loss of
broker storage or a quorum failure.

Four fresh checkout fixtures ran sequentially. The initial harness failed with
exit 99 because its completion deadline was exceeded; the original verdict and
ledger are retained. After healing, fresh authenticated observations found
**4/4 CONFIRMED without event replay**. A derived final-state audit passed with
zero violations and four independently matched Stripe sandbox charges, with no
unmatched provider effects. Catalog returned HTTP 200 in all 102 probes.

Broker-side group descriptions before and after showed `order-placed` lag zero
on all three partitions. Log-end offsets moved from 118/100/110 to 121/100/112;
these are group-wide observations, not an exact count of this run's events.
Consumer commits caught up with those offsets. No business SQL writes or resets
of consumer offsets were used.

<a id="kafka-disruption-consumer-lag-telemetry"></a>

### Consumer lag telemetry

Orders and Notifications already expose
`kafka_consumer_fetch_manager_records_lag` in Prometheus. The collector previously
queried only `kafka_consumergroup_lag`, from an exporter not installed here. Its
new fallback collects the existing client metric and records the exact query
source. It preserves NOT_VERIFIED when neither source has samples.

Client fetch-position lag differs from broker-side committed-offset lag. It
cannot establish the backlog of a stopped consumer, and samples may disappear
or become stale during a fault. The broker CLI snapshots independently check
committed offsets; a persistent exporter remains useful for stopped groups.
No metric source is silently combined with another or treated as a correctness
verdict. Telemetry is attributed to namespace and time window, not exclusively
to the four test orders.

<a id="kafka-disruption-conclusion-and-evidence"></a>

### Conclusion and evidence

Automatic convergence and final money-path invariants held after this bounded
partition. The client completion deadline did not hold. This does not establish
AZ tolerance, broker durability or a production latency SLO.

Restricted injector logs, Catalog probes and offset snapshots:
`.resilience-evidence/chaos-20261012/kafka-disruption-20261012T222044Z`.
Original run: `load-results/kafka-disruption-20261012T222044Z`.
Final audit: `load-results/kafka-disruption-20261012T222044Z-final-audit-20261012T222233Z`.
Resource-saturation overrides were authorized; other runner checks remained active.

<a id="payments-latency"></a>

## Payments latency without probe disruption

| Report element | Summary |
| --- | --- |
| Hypothesis (accepted by the team) | Orders' Payments breaker opens while Catalog stays available, then accepted orders converge without an operator after the fault heals. |
| Steady state | Orders `45357ef` (#139, #141); health checks passed; no image, retry budget, probe or GitOps change. |
| Injected fault | A 4000 ms delay on Payments responses to the Orders pod only, for 45 s, leaving probes untouched. |
| Observations | Breaker `OPEN`, `HALF_OPEN`, `CLOSED`; Catalog 50/50 and Payments Ready throughout; six confirmations within 6.43 s of the fault's removal; six charges, zero unmatched ([details](#payments-latency-observations)). |
| Conclusion | Held. Two client polling cycles missed their deadline. |
| Follow-up change | No application change. The injection method now scopes the delay to Orders so that probes are not disrupted. |

<a id="payments-latency-question-and-preceding-evidence"></a>

### Question and preceding evidence

Configuration [#60](https://github.com/g05-eurotransit/EuroTransit-configuration/pull/60)
reports that five of six orders confirmed automatically on Orders `45357ef`.
The sixth had an authorization but exhausted delivery; redrive arrived after its
hold expired, and operator abandonment refunded it and ended it FAILED. It was
not a sixth confirmed order.

That experiment delayed all Payments TCP responses from port 8080 by 4000ms.
Readiness and liveness also use port 8080, with a 2s timeout; Payments became
NotReady and restarted. The report explicitly calls this latency plus restart,
with approximately 75s total disruption. It does not isolate a 45s dependency
latency fault. The observed exhaustion alone therefore does not demonstrate a
new Payments defect or justify extending the bounded recovery policy.

The hypothesis for this verification is the same bounded latency case:
Orders' breaker opens while Catalog stays available, then accepted orders
converge without operator action after the fault heals. The team accepted this
hypothesis.

<a id="payments-latency-controlled-verification"></a>

### Controlled verification

Run `et-pay-pure-74a6ce370600` used six fresh fixtures, two VUs and the existing
configuration-owned k6 runner. Orders already ran `45357ef`, containing #139 and
#141. No application image, retry budget, probe or GitOps configuration changed.
Health checks passed; the existing user authorization waived only resource
saturation for bounded workstation traffic, not health or fixture ownership.

An ephemeral netshoot container, pinned to
`sha256:147f2c4cb0aa7a741151bce2bfef71d9e1a04631636e24665ee2a5ed799feb47`,
used only NET_ADMIN with other capabilities dropped, no privilege or host
networking. Its qdisc delayed outbound IPv4 TCP responses from port 8080 **only
to the captured Orders pod IP /32**. The kubelet and monitoring destinations
were outside that filter. Both pod UIDs/IP scope were checked; this method must
be invalidated if the target Orders pod is replaced during a run.

The filter matches transport traffic, including TCP handshake packets; it is
not an application handler sleep or a URL-specific delay. Its independent timer
removed it after 45s. Logs contain actual delayed packet counts and restoration
to `qdisc noqueue`, from **08:56:36 to 08:57:21 UTC**. No replica, resource limit,
Service routing, business SQL row or consumer offset was changed.

<a id="payments-latency-observations"></a>

### Observations

| Observation | Result |
| --- | --- |
| First Payments breaker OPEN | 08:57:01.261 UTC |
| First HALF_OPEN | 08:57:18.262 UTC |
| First CLOSED after OPEN | 08:57:23.368 UTC |
| Catalog probes | 50/50 HTTP 200; nearest-rank p95 145.82ms |
| Payments readiness samples | 50/50 Ready |
| Payments container restarts | 5 before, 5 after; same Pod UID |
| First authorization persisted | 08:56:44.198 UTC, during the fault |
| Confirmation audit events | Six, from 08:57:22.658 to 08:57:27.426 UTC |
| Last confirmation after fault removal | Approximately 6.43s |
| Operator redrive, replay or compensation | None |
| Run-owned reconciliation rows | Zero, including resolved records |
| Final correctness audit | VERIFIED, zero violations |
| Independent Stripe sandbox extraction | All pages read; six matching charges, zero unmatched charges |

The first authorization existed well before healing while Orders still awaited
a usable response. Its automatic retry converged under the existing idempotent
money path. The scoped final database/provider verification found no duplicate
reservation, charge or seat ownership violation. Its guarantee is bounded to
this evidence window, not all future traffic.

The **original client harness failed with exit 99**: two of six client polling
cycles exceeded their completion deadline, recording ACCEPTED/PAYMENT_PENDING.
The other four completed within their polling windows. The original ledger and
failed verdict are unchanged. A separate, explicitly labelled derived final-state
audit uses fresh API/database observations after automatic convergence; it does
not convert the original client run into a pass or demonstrate the normal
checkout latency SLO during an injected four-second delay.

<a id="payments-latency-conclusion-and-follow-up"></a>

### Conclusion and follow-up

The bounded pure-latency hypothesis held for breaker containment, Catalog
isolation and automatic final convergence of all six orders with unique payment
and reservation effects. The client completion-deadline criterion failed for two
orders. No new operational Orders/Payments change is proposed from this result.

Keep #60 as the historical compound-fault/runbook result. Longer outages,
Payments process crashes and service restart recovery remain distinct cases;
this run neither makes them pass nor proves every provider failure safe. The
injection-method correction is to scope delayed traffic to Orders, preserving
probes, rather than increasing liveness timeouts or retry budgets to mask it.
The application [postmortem](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/operations/payments-latency-postmortem.md) assesses the operator response window against the adopted recovery objectives.

<a id="payments-latency-evidence-and-cleanup"></a>

### Evidence and cleanup

[Sanitized verification summary](../evidence/2026-10-17/payments-pure-latency-summary.json)
contains aggregate outcomes, timestamps and source artifact hashes only.
Restricted fault metadata, logs, packet counters, pod samples and reconciliation
SELECT output are under `.resilience-evidence/payments-20261017/payments-pure-latency-20261017T085630Z`
in the workspace. Source run artifacts are in
`load-results/payments-pure-latency-20261017T085630Z`; the verified derived audit
is `load-results/payments-pure-latency-20261017T085630Z-final-audit-20261017T085745Z`.
Raw provider references, order IDs and credentials are not published.

The fault container terminated after its independent cleanup. The added
19180/19190 port-forwards were removed after collection; user-owned forwards and
existing controller pauses were preserved. No permanent rollout or deployment
was performed.

<a id="payments-latency-and-restart"></a>

## Payments latency experiment

The current run tests the Orders recovery policy from application #139/#141, with an earlier-revision comparison retained below. A 45-second delay also restarted Payments: five of six purchases confirmed automatically and one required abandonment/refund. The original client run failed; this is distinct from the [latency-only experiment](dependencies.md#payments-latency).

| Report element | Summary |
| --- | --- |
| Hypothesis (accepted by the team) | A slow Payments opens the Orders breaker and leaves Catalog available; after the fault, orders reach a terminal state within about a minute without an operator, and any order that outlasts the budget is recovered through the runbook. |
| Steady state | Orders `45357ef`, Inventory and Payments `98bedf2`; breaker `CLOSED` after three warm-up orders; controllers paused; saturation override authorized by the Orders owner. |
| Injected fault | A 4000 ms delay on all Payments responses from port 8080 for 45 s; it also timed out Payments' probes, which restarted it once. |
| Observations | Five of six `CONFIRMED` automatically, the last about 72 s after the fault; the sixth exhausted its budget, its redrive was refused 13 s after its hold expired, and the operator abandoned and refunded it; Catalog 26/26 ([details](#payments-latency-and-restart-fault-and-observations)). |
| Conclusion | Held for five orders. The sixth reached the operator as designed, but the redrive missed the hold window. |
| Follow-up change | The [postmortem](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/operations/payments-latency-postmortem.md) tracks them: the operations console (application #152) and alerts within the hold window (#57). The pure-latency case runs separately. |

<a id="payments-latency-and-restart-steady-state-and-hypothesis"></a>

### Steady state and hypothesis

Orders ran `45357ef` (application `dev` with #139 and #141); Inventory and Payments ran `98bedf2`.
The reconciliation controllers were paused. The #46 preflight reported saturation,
so the harness proxy path (+576 MiB, a published proxy image, two GitOps changes and two Orders
rollouts) was not feasible; **a saturation override was authorized by the Orders owner** and the
earlier fault method was repeated: `load-tests/run.py` launched directly, fault injected by the operator.

Hypothesis: a slow Payments opens the Orders Payments breaker and leaves Catalog available; after the
fault is removed, the affected orders reach a terminal state within about a minute without an operator
(#139's retry budget), and any order that outlasts the budget is recovered through the runbook.

<a id="payments-latency-and-restart-fault-and-observations"></a>

### Fault and observations

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

<a id="payments-latency-and-restart-comparison-with"></a>

### Comparison with

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

<a id="payments-latency-and-restart-conclusion-and-follow-up"></a>

### Conclusion and follow-up

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

<a id="payments-latency-and-restart-evidence"></a>

### Evidence

Run artifacts, injector logs, one-second samples, collector output, provider audits and verifications
are kept outside Git in the Orders owner's workspace (`resilience-evidence-2026-10-16/payments-latency-*`).
Raw identifiers and provider references are excluded from Git.

<a id="payments-latency-and-restart-complementary-recovery-finding"></a>

### Complementary recovery finding

An earlier latency experiment kept Catalog healthy (129/129 reads) and observed breaker OPEN/HALF_OPEN, but its eight accepted orders required explicit event replay. That result is superseded for the current automatic recovery policy; the [incident timeline](../incidents/payments-recovery.md) and the application [postmortem](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/operations/payments-latency-postmortem.md) retain the diagnosis. It is not evidence of automatic convergence.

<a id="notifications-outage"></a>

## Notifications stopped while checkout succeeds

| Report element | Summary |
| --- | --- |
| Hypothesis (accepted by the team) | Stopping the whole Notifications JVM leaves checkout functional, and notification consumption catches up after it resumes. |
| Steady state | All application services Ready. |
| Injected fault | SIGSTOP to the Notifications JVM for 25 s. |
| Observations | 4/4 checkouts accepted and `CONFIRMED` during the stop; four matching charges; the `notifications` group back at log end on all partitions ([details](#notifications-outage-fault-and-observations)). |
| Conclusion | Held. |
| Follow-up change | None for checkout. Notification history across restarts is best effort by decision (application #131). |

<a id="notifications-outage-steady-state-and-proposed-hypothesis"></a>

### Steady state and hypothesis

All application services were Ready after the preceding experiments.
Hypothesis: stopping the entire Notifications JVM must leave checkout functional,
while notification consumption catches up after it resumes. The team accepted
this hypothesis.

<a id="notifications-outage-fault-and-observations"></a>

### Fault and observations

An ephemeral container targeted only the Notifications process namespace and
used KILL (without privilege or host networking) to send SIGSTOP to Java PID 1.
The process was stopped from **22:39:55 to 22:40:20 UTC**. An independent
25-second timer and cleanup trap sent SIGCONT. No Deployment scaling, routing,
GitOps setting or business data changed. The netshoot image was digest-pinned.

The four sequential checkout attempts ran from **22:39:59.964 to
22:40:09.234 UTC**, entirely inside the stop interval. All received HTTP 202 and
reached CONFIRMED while Notifications could execute no code. The original
harness passed (exit 0). Original and final-state correctness verifications both
returned VERIFIED with zero violations. Independent Stripe audits found four
matching charges and no unmatched effects.

After SIGCONT, the broker-side `notifications` group description showed committed
offset equal to log end on all three `notification-requested` partitions:
97/97, 101/101 and 120/120. This proves group catch-up, not external email delivery
or exclusive processing of just these four messages. No consumer-offset reset or
manual event replay was used. The original pod UID was preserved.

One earlier attempt stopped at an ephemeral-container startup check before
SIGSTOP; it is excluded from failure evidence.

<a id="notifications-outage-conclusion-and-evidence"></a>

### Conclusion and evidence

Checkout independence from a completely stopped Notifications process held for
this bounded interval. Consumption caught up after resumption. This test does
not prove notification-history durability across restart or a third-party
notification delivery guarantee. Those are separate from checkout degradation.

Restricted injector log, group offsets and result:
`.resilience-evidence/chaos-20261012/notifications-down-20261012T223951Z`.
Original run: `load-results/notifications-down-20261012T223951Z`.
Final audit: `load-results/notifications-down-20261012T223951Z-final-audit-20261012T224038Z`.
Resource saturation was waived for bounded workstation traffic; other runner
checks remained active. Injector cleanup restored the running JVM.
