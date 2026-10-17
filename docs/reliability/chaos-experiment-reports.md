# Executed resilience experiments

These reports contain observations from the authorized AKS session on 2026-10-12.
Hypotheses, recovery objectives and conclusions require team ownership/review.
An initial failed client verdict remains failed even when a later correctness
audit verifies recovered orders. Raw evidence is restricted outside Git.

| Experiment | Observed result | Report |
| --- | --- | --- |
| Payments latency | Breaker OPEN/HALF_OPEN observed; Catalog 129/129 healthy. Eight orders confirmed after explicit replay; automatic recovery not demonstrated. | [Payments latency](payments-latency-2026-10-12.md) |
| Inventory kill plus duplicate events/HTTP retries | Verified reservation SQL overlap; one winner/four sold-out failures; one charge. Correctness passed after replay; client deadline failed. | [Inventory crash](inventory-kill-2026-10-12.md) |
| Kafka response partition | Four orders automatically confirmed after healing; final audit passed; initial client deadline failed. | [Kafka disruption](kafka-disruption-2026-10-12.md) |
| Selective application node drain | Availability failed; Orders Pending without spare capacity. Operator uncordon restored service; three accepted orders confirmed. Whole-node/AZ outage not tested. | [Node drain](node-drain-2026-10-12.md) |
| CNPG primary crash with temporary standby | New primary observed in ~3.5s; Orders read recovered in ~5.1s. One accepted order required replay; all three accepted orders finally verified. | [Primary failover](postgres-failover-2026-10-12.md) |
| Notifications process stopped | Four checkout confirmations entirely inside stop interval; original harness and independent audits passed; consumer caught up. | [Notifications down](notifications-down-2026-10-12.md) |
| Orders SIGTERM | Readiness refused, drain completed, exit 143; both accepted orders preserved. Four attempts failed during single-replica restart. | [Orders shutdown](orders-shutdown-2026-10-12.md) |
| Canary / blue-green | Live delivery not run: disabled Rollouts, schema/scrape-label fixes awaiting publication and overlap capacity needed. | [Delivery preflight](progressive-delivery-preflight-2026-10-12.md) |
| SLO / alert / tracing | Real reconciliation alert fired; collector metric coverage verified. SLO mapping and query selectors need alignment; tracing export/backend absent. | [Observability audit](observability-verification-2026-10-12.md) |

Application experiment design remains in the sibling repository's
`docs/operations/chaos-experiments.md`. These observations do not substitute for
team-authored consistency choices, SLOs, fault hypotheses or the final postmortem.
Sanitized aggregate audit and historical alert samples are versioned in
[the evidence exports](evidence/2026-10-12/README.md). Follow-up work is tracked in [the DoD](../dod.md) and the
[draft incident review](postmortem.md). The existing baseline/contention/replay
reports are proposed separately in configuration PR #55; load-shedding setup is
proposed in configuration PR #54 and is not included in these live proofs.
