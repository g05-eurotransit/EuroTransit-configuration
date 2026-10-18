# Observability Platform

This document owns the platform-side observability stack.

The application [SLO specification](https://github.com/g05-eurotransit/EuroTransit-application/blob/dev/docs/operations/slo-observability.md) owns objectives and SLI semantics. This page maps those signals to deployment artifacts. Existing checkout dashboards and alerts use HTTP proxies; [Kind verification](../reliability/kind-observability.md) documents the mismatch with asynchronous checkout outcomes. Do not read matching dashboard/alert thresholds as proof of a correct SLI.

## Current Manifests

- kube-prometheus-stack values live in `platform/kube-prometheus-stack/values.yaml`.
- Checkout symptom alerts live in `platform/kube-prometheus-stack/prometheus-rules.yaml`.
- Grafana dashboards live in `platform/kube-prometheus-stack/dashboards/` as ConfigMaps
  labelled `grafana_dashboard: "1"`, picked up by the Grafana sidecar
  (`sidecar.dashboards.searchNamespace: ALL`): RED per service, checkout SLO for the
  money path, and USE for nodes and pods. Their queries reuse the alert label scheme
  (`namespace="eurotransit"`, `app=...`) and include `CheckoutFastBurn`, `CheckoutLatencyHigh` and `KafkaPipelineStalled` views.
- **Delivery path:** the `kube-prometheus-stack` Application installs the Helm chart only
  and never renders `platform/kube-prometheus-stack/kustomization.yaml`. The rules and
  dashboards are delivered by a separate `eurotransit-monitoring-config` Application
  (sync-wave 15, after the chart's CRDs at wave 10) that syncs that kustomization into the
  `monitoring` namespace. Both are removed by the standard Kind GitOps overlay. The isolated Kind HA procedure enables its own monitoring stack.
  `eurotransit-monitoring-config` is the sole owner of these four resources;
  `platform/environments/aks` must not include `../../kube-prometheus-stack`,
  because that would also render them through `eurotransit-platform-runtime`.
  Before merging an ownership correction on an existing AKS cluster, verify
  that the three dashboard ConfigMaps and `PrometheusRule/eurotransit-money-path`
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

Use the application [recovery runbook](https://github.com/g05-eurotransit/EuroTransit-application/blob/dev/docs/operations/orders-recovery-runbook.md) for incident inspection, redrive and settlement. Keep query selectors aligned with loaded Prometheus samples, including namespace, service labels and rollout hashes. Empty samples do not count as healthy gates.

[Kind monitoring verification](../reliability/kind-observability.md) records actual metric coverage and committed lag. [AKS monitoring verification](../reliability/aks-observability.md) records the injected alert. Trace export/backend deployment remains in [readiness](../delivery/readiness.md).
