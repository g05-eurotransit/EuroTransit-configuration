# Observability Platform

This document owns the platform-side observability stack.

## Required Coverage

- RED metrics for application services.
- USE metrics for infrastructure.
- Checkout latency and success-rate dashboards.
- Symptom-based alerts tied to SLOs.
- Distributed tracing for the money path.

Service instrumentation conventions are coordinated with the application repository; dashboards, alert rules, and platform deployment live here.

## Current Manifests

- kube-prometheus-stack values live in `platform/kube-prometheus-stack/values.yaml`.
- Checkout symptom alerts live in `platform/kube-prometheus-stack/prometheus-rules.yaml`.
- Grafana dashboards live in `platform/kube-prometheus-stack/dashboards/` as ConfigMaps
  labelled `grafana_dashboard: "1"`, picked up by the Grafana sidecar
  (`sidecar.dashboards.searchNamespace: ALL`): RED per service, checkout SLO for the
  money path, and USE for nodes and pods. Their queries reuse the alert label scheme
  (`namespace="eurotransit"`, `app=...`) and mirror the `CheckoutFastBurn`,
  `CheckoutLatencyHigh`, and `KafkaPipelineStalled` thresholds, so a dashboard and the
  alert that pages on it never disagree.
- **Delivery path:** the `kube-prometheus-stack` Application installs the Helm chart only
  and never renders `platform/kube-prometheus-stack/kustomization.yaml`. The rules and
  dashboards are delivered by a separate `eurotransit-monitoring-config` Application
  (sync-wave 15, after the chart's CRDs at wave 10) that syncs that kustomization into the
  `monitoring` namespace. Both are removed by the kind overlay, so monitoring is AKS-only.
- Reconciliation safety alerts in that rule file use the bounded Orders metrics
  defined by the application repository's
  `docs/design/reservation-confirmation.md`; they do not put order IDs,
  correlation IDs, provider messages, or event payloads into Prometheus labels.
- Application ServiceMonitors are rendered from `charts/eurotransit/templates/servicemonitors.yaml`.
- Orders and Inventory outbox relays live in `platform/connectors`; their
  `KafkaConnect` and `KafkaConnector` status exposes worker, connector, task,
  and automatic-restart health through Strimzi.
- Chaos Mesh installation values live in `platform/chaos-mesh/values.yaml`; experiment manifests are still pending.

## Money-Path Proof Checklist

- Public Orders route rejects unauthenticated checkout.
- Catalog route is reachable according to the selected public/auth policy.
- Inventory and Payments have no public ingress.
- A checkout flow carries one `X-Correlation-Id` through Orders, Inventory, Payments, Kafka events, and Notifications where applicable.
- Duplicate order placement with the same idempotency key does not create a second logical order.
- Inventory idempotency retention is configured for 30 minutes while seat holds still expire after 10 minutes.
- Orders and Payments idempotency retention are configured for 24 hours.
- Payment sandbox credentials are loaded from Kubernetes secret material, not source code.
- Notifications outage does not fail an already confirmed checkout.

## Reconciliation Alert Policy

The reconciliation rules complement the checkout SLO alerts with durable
money-path safety signals. They use gauges for open incidents and non-terminal
orders because a counter rate would clear while an unresolved incident remains.
The rules are scoped to the Orders scrape target (`namespace="eurotransit",
app="orders"`).

| Alert | Signal and threshold | Response intent |
| --- | --- | --- |
| `ReconciliationRecordOpen` | Any open record, for 5 minutes | Create an operations ticket for the record kind. |
| `PaymentReversalFailure` | A `PAYMENT_REVERSAL_FAILURE` is recorded in 10 minutes | Page immediately: money is unresolved and the order remains `COMPENSATING`. |
| `InvariantViolation` | An `INVARIANT_VIOLATION` is recorded in 10 minutes | Page immediately and investigate before an operator resolves it. |
| `CheckoutStuckNonTerminal` | Oldest order in `PAYMENT_PENDING`, `CONFIRMING_INVENTORY`, or `COMPENSATING` exceeds 5 minutes for 2 minutes | Page while there is still time to recover before the 10-minute Inventory hold boundary. |
| `ReconciliationAgeHigh` | Oldest open reconciliation record exceeds 15 minutes for 5 minutes | Escalate a record that has not converged through normal redrive. |
| `InventorySeatConflict` | A `RESERVATION_SEAT_CONFLICT` confirmation refusal occurs in 5 minutes | Page; this is a direct no-oversell invariant signal. |
| `PoisonOrderEvent` | An unparseable `order-placed-dlt` event occurs in 5 minutes | Ticket; use the Kafka key and original offset in Orders logs, never the payload as a metric label. |
| `DeadLetterUnknownOrder` | A parseable `order-placed-dlt` event has no durable Orders record in 5 minutes | Ticket; investigate event/data retention before replay. |

The five-minute checkout age is intentionally below the ten-minute seat-hold
expiry, and the two-minute `for` duration filters one delayed gauge refresh
(the application publishes every 30 seconds). The five-minute open-record
delay filters incidents that automatic recovery closes promptly; the 15-minute
reconciliation age escalates an incident that has not converged. Counter-based
event alerts use `increase(...)`, which is reset-safe and simply remains
inactive before a matching series has ever been scraped.

These are deployable platform rules, not end-to-end proof. Alert firing and
clearing must be demonstrated after the application scrape authorization is
deployed and the Orders ServiceMonitor successfully scrapes
`/actuator/prometheus`.
