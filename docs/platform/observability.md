# Observability Platform

This document owns the platform-side observability stack.

The application [SLO specification](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/slo.md) owns objectives and SLI semantics. This page maps those signals to deployment artifacts. Existing checkout dashboards and alerts use HTTP proxies; [Kind verification](../verification/kind/observability.md) documents the mismatch with asynchronous checkout outcomes. Do not read matching dashboard/alert thresholds as proof of a correct SLI.

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
  `monitoring` namespace. Both are removed by the standard Kind GitOps overlay. The isolated Kind HA procedure enables its own monitoring stack.
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

## Alert operations

[Prometheus rules](../../platform/kube-prometheus-stack/prometheus-rules.yaml) own exact thresholds and durations. Reconciliation alerts use durable open-record and nonterminal-age gauges so unresolved work remains visible. Labels are bounded; order IDs, correlation IDs, provider messages and event payloads belong in restricted logs/evidence.

Use the application [recovery runbook](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/operations/orders-recovery-runbook.md) for incident inspection, redrive and settlement. Keep query selectors aligned with loaded Prometheus samples, including namespace, service labels and rollout hashes. Empty samples do not count as healthy gates.

[Kind monitoring verification](../verification/kind/observability.md) records actual metric coverage and committed lag. [AKS monitoring verification](../verification/aks/observability.md) records the injected alert. Trace export/backend deployment remains in [readiness](../readiness.md).

### Reconciliation Alert Policy

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

### Inventory Alert Policy

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

## Grafana directory provisioning

The pinned kube-prometheus-stack 75.15.1 chart still generates its datasources and
28 standard dashboard ConfigMaps. AKS disables both sidecars and mounts those
ConfigMaps plus the six EuroTransit and nine Strimzi dashboard ConfigMaps as
complete directories: 43 dashboards in total. The Strimzi 0.46.1 chart continues
to own its monitoring-namespace dashboard ConfigMaps; include its render in the
mount-set validation.
Datasource names, URLs, default selection, settings and UIDs (`prometheus`,
`alertmanager`) come from the same chart template. A Helm-owned provider ConfigMap
is mounted at `/etc/grafana/provisioning/dashboards`; its file provider scans
`/var/lib/grafana/dashboards` every 30 seconds. All dashboard/provisioning mounts
use no nonempty `subPath`, allowing projected ConfigMap updates to reach Grafana.
The chart's independent `grafana.ini` mount remains chart-managed.

Validate the render's dashboard ConfigMap set against the mounted set on every
chart upgrade. A changed dashboard name needs a corresponding mount before the
upgrade. Grafana runs exactly one container. All dashboard ConfigMaps have one
GitOps owner: the chart owns standard dashboards and provisioning; the separate
`eurotransit-monitoring-config` Application owns the custom dashboards and rules;
the Strimzi Application owns the nine Strimzi dashboards.

After rollout, compare dashboard JSON/UIDs and datasource definitions with the
previous render, verify the live dashboard list, and perform a reversible custom
dashboard update to confirm polling sees the projected update. Preserve existing
admin Secret references. The 34 dashboards with explicit manifest UIDs retain
those UIDs; the nine Strimzi dashboards have no explicit UID, so Grafana may
regenerate their database IDs after a restart of its ephemeral storage, as before.
Compare all 43 titles and dashboard JSON, and the 34 explicit UIDs. Datasources are provisioned at startup: if their values
change later, roll Grafana or use the authorized Grafana provisioning reload API.

Rollback: restore the prior AKS Grafana values, roll Grafana, verify both sidecars
and the original dashboards/datasources. Do not delete custom ConfigMaps.

## Prometheus API server filter

The AKS API server ServiceMonitor retains the complete pinned chart default
noisy-bucket filter and appends only:

```text
apiserver_(request_duration_seconds|request_body_size_bytes|request_sizes|response_sizes|response_size_bytes)_(bucket|sum|count)
```

Helm replaces lists, so the default rule must be copied and verified on upgrades.
The rendered chart and custom dashboard/rule expressions have no dependencies on
the removed families. The filter does not drop `apiserver_request_sli_duration`,
`apiserver_request_total`, certificate-expiration, node/container or application
metrics; the existing chart filter still drops its selected SLI bucket boundaries.
Retention stays 2d on AKS, 7d in shared/Kind values; scrape intervals are unchanged.

Before release, inspect additional **live** dashboards, PrometheusRule objects,
recording rules and downstream consumers for dependencies on the dropped families.
Render-based checks cover Git and the pinned chart only. Verify API availability,
latency, certificate, infrastructure and application alerts after rollout. Rollback
by restoring the previous metricRelabelings; filtered samples during the release
window cannot be recovered retroactively.
