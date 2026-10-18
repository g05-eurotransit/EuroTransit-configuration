# Verification results

The reports below are the current evidence for each environment and scenario. Kind demonstrates failover and progressive-delivery controller behavior; constrained AKS records separate fault and financial audits. Results apply to the recorded revisions and fixtures. They do not establish production availability or long-window SLO compliance.

## Kind

| Scenario | Result and material limit | Report |
| --- | --- | --- |
| Worker loss / PostgreSQL primary | Promotion 51.86 s, synchronous quorum 70.30 s, checkout confirmation 179.62 s during a 180 s stop; 5 committed purchases finally confirmed with five independently audited charges. Client timeouts and Catalog 504 remain recorded; no RTO/SLO pass claimed. | [HA failover](kind-ha-failover.md) |
| Catalog replica failure | Replica attribution and endpoint withdrawal explain transient gateway timeouts; healthy replica returned 52/52 successful reads. | [Catalog failover](kind-catalog-failover.md) |
| Orders shutdown | 4/4 confirmed with readiness refusal, endpoint withdrawal, bounded drain and independent payment audit. | [Orders shutdown](kind-orders-shutdown.md) |
| Checkout admission | Three controlled 429 responses had no business effects; five accepted checkouts confirmed and reads stayed available. A low test threshold does not establish saturation capacity. | [Load shedding](kind-checkout-load-shedding.md) |
| Orders canary | Ordinary 10/25/50% gates, real traffic and automatic abort verified; 100% read check and promotion passed. Temporary placement exception; one batch retains a manual provider-evidence qualification. | [Canary](kind-orders-canary.md) |
| Catalog blue/green | Public 1316/1316 and preview 1042/1042 valid reads; rollback 1.575 s. Local configuration-only revisions, not proof of CI/GitOps delivery of a new application binary. | [Blue/green](kind-catalog-bluegreen.md) |
| Notifications pause | 2/2 purchases confirmed; committed lag 0 → 2 → 0 on the same process. | [Notifications lag](kind-notifications-lag.md) |
| CDC idle recovery | Transactional heartbeats advance all three logical slots after manual baseline repair. | [CDC recovery](kind-cdc-recovery.md) |
| Monitoring | Real asynchronous metrics and committed Kafka lag available; checkout dashboard/alert SLI mapping remains incorrect and queryable tracing is absent. | [Observability](kind-observability.md) |

## AKS

| Scenario | Result and material limit | Report |
| --- | --- | --- |
| Baseline | 5/5 confirmed, manual provider check; automated verifier NOT_VERIFIED. Separate 20-order baseline has its own independent provider audit. | [Baseline](aks-baseline.md) |
| Seat contention | Scoped no-oversell and one-charge correctness audit. | [Contention](aks-contention.md) |
| Request replay | HTTP/event replay and financial effects checked within the run. | [Replay](aks-request-replay.md) |
| Rising traffic | Bounded ramp/spike observations, not maximum sustainable capacity. | [Ramp/spike](aks-ramp-spike.md) |
| Inventory crash | One winner/four sold-out, one charge; automatic convergence in 73 s on the last redelivery. Original client deadline failed. | [Inventory crash](aks-inventory-crash.md) |
| Kafka disruption | Four automatic confirmations after healing; original client deadline failed. | [Kafka disruption](aks-kafka-disruption.md) |
| Payments latency only | Six automatic confirmations under 4 s delay for 45 s; Catalog/readiness 50/50. Two original client polling timeouts remain failures. | [Pure latency](aks-payments-latency.md) |
| Payments latency + restart | Five of six automatically confirmed; one abandoned/refunded. This compound fault stays separate from latency-only proof. | [Latency and restart](aks-payments-latency-and-restart.md) |
| Selective node drain | Availability failed without spare capacity; operator uncordon recovered service and three accepted orders confirmed. | [Node drain](aks-node-drain.md) |
| Temporary PostgreSQL standby | Primary promotion ~3.5 s and read recovery ~5.1 s; one accepted order needed replay. | [Primary failover](aks-postgres-failover.md) |
| Notifications stopped | Four confirmations during the stop, independent audits passed and consumer caught up. | [Notifications outage](aks-notifications-outage.md) |
| Orders SIGTERM | Accepted work preserved; four attempts failed during single-replica replacement. | [Orders shutdown](aks-orders-shutdown.md) |
| Alert injection | Real reconciliation symptom alert fired; target-cluster tracing absent. | [Observability](aks-observability.md) |

## Reproduce and assess

Use the [load runner](load-test-runner.md), [HA runbook](kind-ha-runbook.md), [load-shedding procedure](checkout-load-shedding.md) and [progressive-delivery procedure](../delivery/progressive-delivery.md). [Readiness](../delivery/readiness.md) records remaining acceptance work; the [incident review](postmortem.md) records the recovery failure and corrections. Application [fault hypotheses](https://github.com/g05-eurotransit/EuroTransit-application/blob/dev/docs/operations/chaos-experiments.md) and [SLO definitions](https://github.com/g05-eurotransit/EuroTransit-application/blob/dev/docs/operations/slo-observability.md) remain authoritative.

Original client verdicts remain unchanged when a later final-state audit verifies recovery. Preserve raw ledgers, hashes, revisions and provider audits; timestamps in evidence are correlation data. [Sanitized AKS aggregates](evidence/2026-10-12/README.md) and the linked JSON/CSV evidence support the reports. Restricted raw artifacts remain outside Git.
