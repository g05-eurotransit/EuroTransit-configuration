# Observability Platform

This document owns the platform-side observability stack.

The application [SLO specification](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/slo.md) owns objectives and SLI semantics. This page maps those signals to deployment artifacts. Existing checkout dashboards and alerts use HTTP proxies; [Kind verification](../verification/kind/observability.md) documents the mismatch with asynchronous checkout outcomes. Do not read matching dashboard/alert thresholds as proof of a correct SLI.

## Current Manifests

- kube-prometheus-stack values live in `platform/kube-prometheus-stack/values.yaml`.
- Checkout symptom alerts live in `platform/kube-prometheus-stack/prometheus-rules.yaml`.
- Custom dashboards are ConfigMaps under `platform/kube-prometheus-stack/dashboards/`. Shared values use sidecar discovery; the AKS overlay mounts the pinned dashboard set as directories. The effective environment values decide delivery.
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

Use the application [recovery runbook](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/operations/orders-recovery-runbook.md) for incident inspection, redrive and settlement. Keep query selectors aligned with loaded Prometheus samples, including namespace, service labels and rollout hashes. Empty samples do not count as healthy gates.

[Kind monitoring verification](../verification/kind/observability.md) records actual metric coverage and committed lag. [AKS monitoring verification](../verification/aks/observability.md) records the injected alert. Trace export/backend deployment remains in [readiness](../readiness.md).

## Grafana directory provisioning

The pinned kube-prometheus-stack 75.15.1 chart still generates its datasources and
28 standard dashboard ConfigMaps. AKS disables both sidecars and mounts those
ConfigMaps plus the three EuroTransit and nine Strimzi dashboard ConfigMaps as
complete directories: 40 dashboards in total. The Strimzi 0.46.1 chart continues
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
admin Secret references. The 31 dashboards with explicit manifest UIDs retain
those UIDs; the nine Strimzi dashboards have no explicit UID, so Grafana may
regenerate their database IDs after a restart of its ephemeral storage, as before.
Compare all 40 titles and dashboard JSON, and the 31 explicit UIDs. Datasources are provisioned at startup: if their values
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
