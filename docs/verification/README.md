# Verification results

The reports below are the current evidence for each environment and scenario. Kind demonstrates failover and progressive-delivery controller behavior; constrained AKS records separate fault and financial audits. Results apply to the recorded revisions and fixtures. They do not establish production availability or long-window SLO compliance.

## Kind

| Scenario | Result and material limit | Report |
| --- | --- | --- |
| Worker loss / PostgreSQL primary | Promotion 51.86 s, synchronous quorum 70.30 s, checkout confirmation 179.62 s during a 180 s stop; 5 committed purchases finally confirmed with five independently audited charges. Client timeouts and Catalog 504 remain recorded; no RTO/SLO pass claimed. | [HA failover](kind/ha-failover.md) |
| Catalog replica failure | Replica attribution and endpoint withdrawal explain transient gateway timeouts; healthy replica returned 52/52 successful reads. | [Catalog failover](kind/ha-failover.md#catalog-failover-verification) |
| Orders shutdown | 4/4 confirmed with readiness refusal, endpoint withdrawal, bounded drain and independent payment audit. | [Orders shutdown](kind/orders-shutdown.md) |
| Checkout admission | Three controlled 429 responses had no business effects; five accepted checkouts confirmed and reads stayed available. A low test threshold does not establish saturation capacity. | [Load shedding](kind/checkout-load-shedding.md) |
| Progressive delivery | Orders canary and Catalog blue/green; controller results retain placement and delivery-proof limits. | [Experiments](kind/progressive-delivery.md) |
| Notifications pause | 2/2 purchases confirmed; committed lag 0 → 2 → 0 on the same process. | [Notifications lag](kind/notifications-lag.md) |
| CDC idle recovery | Transactional heartbeats advance all three logical slots after manual baseline repair. | [CDC recovery](incidents/cdc-slots.md) |
| Monitoring | Real asynchronous metrics and committed Kafka lag available; checkout dashboard/alert SLI mapping remains incorrect and queryable tracing is absent. | [Observability](kind/observability.md) |

## AKS

| Scenario | Result and material limit | Report |
| --- | --- | --- |
| Baseline | 5/5 confirmed, manual provider check; automated verifier NOT_VERIFIED. Separate 20-order baseline has its own independent provider audit. | [Baseline](aks/checkout.md#baseline) |
| Seat contention | Scoped no-oversell and one-charge correctness audit. | [Contention](aks/checkout.md#contention) |
| Request replay | Sequential HTTP replay/conflicts and financial effects checked within the run. | [Replay](aks/checkout.md#request-replay) |
| Rising traffic | Bounded ramp/spike observations, not maximum sustainable capacity. | [Ramp/spike](aks/checkout.md#ramp-and-spike) |
| Dependency recovery | Inventory, Kafka, Payments and Notifications; original client failures and final recovery audits remain separate. | [Experiments](aks/dependencies.md) |
| Workload and database recovery | Node evacuation, Orders shutdown and PostgreSQL promotion; availability failures and operator recovery remain recorded. | [Experiments](aks/recovery.md) |
| Alert injection | Real reconciliation symptom alert fired; target-cluster tracing absent. | [Observability](aks/observability.md) |

## Reproduce and assess

Use the [load runner](../operations/load-tests.md), [HA runbook](../operations/ha-experiment.md), [load-shedding procedure](../operations/load-shedding.md) and [progressive-delivery procedure](../operations/progressive-delivery.md). [Readiness](../readiness.md) records remaining acceptance work; the [incident review](incidents/payments-recovery.md) records the recovery failure and corrections. Application [fault hypotheses](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/verification/strategy.md) and [SLO definitions](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/slo.md) remain authoritative.

Original client verdicts remain unchanged when a later final-state audit verifies recovery. Preserve raw ledgers, hashes, revisions and provider audits; timestamps in evidence are correlation data. [Sanitized AKS aggregates](evidence/2026-10-12/README.md) and the linked JSON/CSV evidence support the reports. Restricted raw artifacts remain outside Git.

[AKS capacity verification](aks/capacity.md) records offline preservation and measured scheduling limits. Incident analyses cover [payment publication](incidents/payment-publication.md), [Payments recovery](incidents/payments-recovery.md) and [lost CDC slots](incidents/cdc-slots.md); they are separate from operational procedures.
