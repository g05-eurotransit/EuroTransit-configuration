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
  money path, USE for nodes and pods, Payment Safety (circuit breaker and payment transitions),
  Inventory Correctness (hold lifecycle and invariant violation guards), and Kafka Pipeline
  (consumer group lag, in-flight pipeline age, DLT, and reconciliation incidents).
  Their queries reuse the alert label scheme (`namespace="eurotransit"`, `app=...`) and mirror
  the money path alert thresholds (`CheckoutFastBurn`, `CheckoutLatencyHigh`, `KafkaPipelineStalled`,
  `InvariantViolation`, `InventorySeatConflict`, etc.), so a dashboard and the alert that pages on
  it never disagree.
- **Delivery path:** the `kube-prometheus-stack` Application installs the Helm chart only
  and never renders `platform/kube-prometheus-stack/kustomization.yaml`. The rules and
  dashboards are delivered by a separate `eurotransit-monitoring-config` Application
  (sync-wave 15, after the chart's CRDs at wave 10) that syncs that kustomization into the
  `monitoring` namespace. Both are removed by the kind overlay, so monitoring is AKS-only.
  `eurotransit-monitoring-config` is the sole owner of these seven resources;
  `platform/environments/aks` must not include `../../kube-prometheus-stack`,
  because that would also render them through `eurotransit-platform-runtime`.
  Before merging an ownership correction on an existing AKS cluster, verify
  that the six dashboard ConfigMaps and `PrometheusRule/eurotransit-money-path`
  have `argocd.argoproj.io/tracking-id` annotations starting with
  `eurotransit-monitoring-config:`. If they still belong to the runtime
  Application, sync the monitoring Application first and verify ownership
  before allowing the runtime Application to prune resources removed from its
  desired state.
- Reconciliation safety alerts in that rule file use the bounded Orders metrics
  defined by the application repository's
  `docs/design/reservation-confirmation.md`; they do not put order IDs,
  correlation IDs, provider messages, or event payloads into Prometheus labels.
- Application ServiceMonitors are rendered from `charts/eurotransit/templates/servicemonitors.yaml`.
- Orders, Inventory and Payments outbox relays live in `platform/connectors`;
  their `KafkaConnect` and `KafkaConnector` status exposes worker, connector,
  task, and automatic-restart health through Strimzi.
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
| `ReconciliationRecordOpen` | Any open record, for 1 minute | Create an operations ticket for the record kind before the 10-minute hold window closes. |
| `PaymentOutcomeUnknown` | An open `PAYMENT_OUTCOME_UNKNOWN` record, for 1 minute | Page immediately: an abandoned order may have taken money but payment outcome is unknown. |
| `PaymentReversalFailure` | A `PAYMENT_REVERSAL_FAILURE` is recorded in 10 minutes | Page immediately: money is unresolved and the order remains `COMPENSATING`. |
| `InvariantViolation` | An `INVARIANT_VIOLATION` is recorded in 10 minutes | Page immediately and investigate before an operator resolves it. |
| `CheckoutStuckNonTerminal` | Oldest order in `PAYMENT_PENDING`, `CONFIRMING_INVENTORY`, or `COMPENSATING` exceeds 3 minutes for 2 minutes | Page while there is still time to recover before the 10-minute Inventory hold boundary. |
| `ReconciliationAgeHigh` | Oldest open reconciliation record exceeds 5 minutes for 2 minutes | Escalate an incident that has not converged through normal redrive. |
| `InventorySeatConflict` | A `RESERVATION_SEAT_CONFLICT` confirmation refusal occurs in 5 minutes | Page; this is a direct no-oversell invariant signal. |
| `PoisonOrderEvent` | An unparseable `order-placed-dlt` event occurs in 5 minutes | Ticket; use the Kafka key and original offset in Orders logs, never the payload as a metric label. |
| `DeadLetterUnknownOrder` | A parseable `order-placed-dlt` event has no durable Orders record in 5 minutes | Ticket; investigate event/data retention before replay. |
| `DeadLetterNotRecorded` | More than 3 dead-letter incident recording failures in 10 minutes | Ticket; a dead letter repeatedly failing to record an incident stalls its topic on that pod. |

The three-minute checkout age matches the Orders retry budget (1.5 to ~2.3 minutes)
plus execution pipeline margin, staying well inside the ten-minute seat-hold expiry.
The one-minute open-record delay gives the operator 7-8 minutes to intervene before
hold expiration, and the five-minute reconciliation age escalates incidents that
have not converged. Counter-based event alerts use `increase(...)`, which is
reset-safe and simply remains inactive before a matching series has ever been scraped.

## Inventory Alert Policy

The inventory rules protect seat consistency, prevent capacity leaks from stuck holds, and guard against service-level failures on the synchronous hold creation path. Scoped to the Inventory scrape target (`namespace="eurotransit", app="inventory"`).

| Alert | Signal and threshold | Response intent |
| --- | --- | --- |
| `InventoryReservationFailures` | Over 20% of seat holds rejected for 5 minutes | Page immediately: investigate seat contention or datastore lock degradation. |
| `InventoryHoldSweepFailure` | Any sweep error in 5 minutes | Page immediately: expired holds cannot be released, leading to artificial capacity loss. |
| `InventoryIdempotencyPurgeFailure` | Any idempotency purge error in 10 minutes | Ticket: cleanup of 30-minute idempotency records failed, risking datastore growth. |
| `InventoryServiceErrorsHigh` | HTTP 5xx error rate exceeds 5% for 5 minutes | Page immediately: internal failures on the synchronous hold path block checkout completion. |

These are deployable platform rules, not end-to-end proof. Alert firing and
clearing must be demonstrated after the application scrape authorization is
deployed and the ServiceMonitors successfully scrape `/actuator/prometheus`.
