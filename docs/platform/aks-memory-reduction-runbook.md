# AKS memory reduction: release and rollback

This is a future release procedure. Preparing the branches and rendering them does
not authorize a cluster change. Kind keeps its original topology and values.
Deploy one change at a time: unused controllers, Grafana provisioning, Connect
consolidation, API server metric filter, then the resource budgets. Keep Keycloak,
Topic Operator, application APIs, scrape intervals and retention unchanged.

Before release, record the actual Git revision, Helm release values and versions,
Argo Application sources, node allocatable memory, all project pods, AKS-managed
pods, temporary jobs, Eraser scans, init containers and rollout overlap. Validate
placement on each node, not just the aggregate requests. The prior estimate of
about 981 MiB aggregate headroom is not a capacity guarantee for three simultaneous
Eraser scans or a node outage. Recalculate from a current inventory, including
DaemonSets, anti-affinity, taints and topology constraints.

After each stage, verify Argo login, marketplace Keycloak login, a complete checkout,
all three outbox flows, Grafana dashboards, active alerts and GitOps reconciliation.
After resource changes, test cold starts and at least 30 minutes of representative
load with no OOM, eviction or pod Pending for memory. Keep any evidence and offset
exports outside Git, with access restricted to the release operator.

## GitOps gate before merging to main

The root and child Applications follow `main` with automated sync and pruning.
**Pause and pin their sources before merging either branch into `main`.** A
branch push alone does not change the cluster; a merge can start reconciliation
immediately. Reviewing or merging a branch is not the controlled migration.

Before the first merge, preserve the current Application sources and sync policies,
then disable automated sync on `eurotransit-platform-root` and every affected
child Application. Include `eurotransit-connectors`,
`eurotransit-platform-runtime`, `kube-prometheus-stack`, and the Helm/operator/
marketplace owners affected by the later budgets. Terminate in-flight syncs and
wait for them to finish. Suspend any external automation that syncs these apps.
Do not manually sync the root while maintenance is in progress: it can restore
child automation and replace their pinned sources.

Pin each affected child Git source, including Helm's `$values` source, to the
recorded pre-release commit; keep chart versions unchanged. Keep Argo CD and
Sealed Secrets bootstrap releases at their recorded values until their own stage.
Once these gates are confirmed, the branches can be reviewed and merged in order:
functional reductions, then resource budgets. Automation remains paused and the
old sources remain pinned while each stage is qualified.

Do not sync the full new overlay to implement the early stages. Use the pinned
old render and reviewed temporary values/CR manifests for just that stage:

1. Disable unused controllers; change only Argo's Dex/ApplicationSet settings and
   Kafka's User Operator, retaining the old budgets and other CR settings.
2. Upgrade monitoring with only the new `grafana` values layered over the old
   values, preserving the old API server filter and memory budgets.
3. Perform the complete stopped-connector migration below. Preserve both old
   workers until backlog and checkout checks pass; then retire them explicitly.
4. Layer in only the new `kubeApiServer` filter, retaining the already-qualified
   Grafana provisioning and the old memory budgets.
5. Apply one controller/service budget at a time through its persistent owner.
   A Helm release can roll several Deployments together: use a temporary values
   overlay for the selected component and retain the other qualified settings.
   Verify actual rollout overlap and available capacity before each update.

Temporary manifests must keep a single owner and be rendered/reviewed before
use; keep them outside Git with private permissions. At the end, compare all live
owners to the reviewed final render. Advance child Git/value sources to the
reviewed final revision, perform the final controlled sync, and restore child
policies before the root policy. Confirm that `main` still matches the reviewed
release before returning any source to `main`. The root must remain paused until
all stages, including the offset migration, are complete.

## Kafka storage gate before any broker rollout

Inspect every live KafkaNodePool storage volume before changing broker resources.
The current AKS overlay inherits `ephemeral` storage from the shared base. A
request-only resource edit can recreate the broker Pod and erase its `emptyDir`,
including Kafka records and Connect config/offset/status state. Existing topic
names being recreated is not proof that their contents survived.

**Do not roll an ephemeral broker as part of this release.** Stop that stage and
prepare a separate durable-storage migration or a verified complete Kafka backup
and restore. Preserve Kafka metadata, application records, consumer offsets and
all three workers' internal topic contents. A PostgreSQL/CNPG snapshot does not
back up Kafka. Export fresh stopped-connector offsets again before any future
Kafka maintenance; pre-migration exports become stale after processing resumes.

## Unused components

Before disabling Dex or ApplicationSet and removing Kafka User Operator, inspect
all namespaces for `ApplicationSet` and `KafkaUser` objects and inspect the live
Argo `argocd-cm`, Helm values and external SSO integrations for `dex.config` and
Dex-dependent authentication. If any is in use, stop this stage and qualify its
replacement first. Confirm the current Argo login method still works without Dex.
The AKS bootstrap now uses `platform/argocd/values-aks.yaml`; Kind uses the shared
values only. The Kafka CR removes only `spec.entityOperator.userOperator`. Argo chart 10.2.2
creates the ApplicationSet Deployment unconditionally, so its supported
`applicationSet.replicas: 0` setting disables the controller pods while retaining
the inert Deployment/RBAC/Service. `applicationSet.enabled` is not a chart option.

Rollback: restore the previous AKS Argo values and Kafka CR, then verify controller
readiness and authentication. No application identity provider is changed.

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

## Kafka Connect migration

The final AKS overlay keeps `orders-outbox-connect`, its worker `group.id`, and its
three internal topics, and moves Inventory and Payments onto it. Connector names,
database credentials references, slots, publications, topic prefixes, transforms
and `tasksMax: 1` remain unchanged. The image/runtime is Kafka 3.9 with the existing
128m/512m heap. Do not change heaps during consolidation. Kafka internal topics,
replication slots and publications must never be reset or deleted for this release.

The procedure uses Kafka 3.9's
[stopped connector creation and offset REST endpoints](https://kafka.apache.org/39/kafka-connect/user-guide/)
and Strimzi's
[paused reconciliation](https://strimzi.io/docs/operators/0.46.1/deploying).
`PAUSED` does not release tasks and replication slots; use `STOPPED`.

`scripts/connect-offset-migration.py` performs one explicit REST step at a time.
It accepts only loopback URLs, exports offsets to newly created mode-0600 files,
requires stopped connectors with no tasks, registers with `initial_state: STOPPED`,
compares offset partitions and values before restart, rejects empty offset sets,
and refuses literal credentials in registration manifests. It never fetches a live
connector config or prints HTTP response bodies. Python 3 and PyYAML are required
for registration. Do not run shell tracing, dump Secrets, log connector configs or
place passwords in the commands, files or logs.

### 1. Prepare the controlled pause

Choose a maintenance window; pause new checkout traffic while keeping backend
consumers available to drain outstanding work. Take the normal platform backup.
Record the live connector definitions privately with credentials redacted, and
compare all non-secret settings with the render. Record slot `confirmed_flush_lsn`,
outbox backlog, Kafka offsets/consumer lag and a known completed checkout.

Pin a pre-migration Git revision and render both its connectors and the final AKS
overlay. Keep the original Inventory/Payments worker definitions for rollback.
Confirm the pre-merge GitOps gate above is still in place: root and connector
automation are suspended and their sources pinned. Terminate any already-running
sync operation and wait for it to finish. Preserve the original sync policy for restoration. A running
parent must not restore child automation during maintenance. Suspend any other
automation/operator job that edits these CRs.

Before moving connectors, apply **only** the final `orders-outbox-connect` CR
(which adds Inventory/Payments Secret references) while preserving all original
workers and connector labels. Allow Strimzi to reconcile, wait for the orders
worker rollout and Ready condition, and verify Orders still works. This is a
staged apply under the suspended GitOps controller, not a sync of the final overlay.

Annotate all three `KafkaConnect` and all three `KafkaConnector` resources with
`strimzi.io/pause-reconciliation=true`; wait for `ReconciliationPaused` conditions.
Pausing only Argo is insufficient: Strimzi could undo REST operations. Make sure
no concurrent reconciliation is in flight before proceeding. Keep this pause
until offsets and connector ownership have been verified.

### 2. Stop, wait for inactive slots, export

Forward each worker's REST Service on a separate loopback port (separate terminals):

```bash
kubectl -n eurotransit port-forward --address 127.0.0.1 svc/orders-outbox-connect-connect-api 18083:8083
kubectl -n eurotransit port-forward --address 127.0.0.1 svc/inventory-outbox-connect-connect-api 18084:8083
kubectl -n eurotransit port-forward --address 127.0.0.1 svc/payments-outbox-connect-connect-api 18085:8083
```

Create a private evidence directory outside the repository with `umask 077`.
For each connector, run `stop` against its **original** worker; for example:

```bash
python3 scripts/connect-offset-migration.py stop --url http://127.0.0.1:18084 --connector inventory-outbox-connector
```

Use 18083 for Orders and 18085 for Payments. The helper waits until state is
STOPPED and the tasks array is empty. With an existing authorized database session
(no password in command arguments), query:

```sql
SELECT slot_name, active, confirmed_flush_lsn
FROM pg_replication_slots
WHERE slot_name IN ('orders_outbox', 'inventory_outbox', 'payments_outbox');
```

All three expected slots must exist and be inactive. If task or slot shutdown
fails, keep traffic and reconciliation paused and investigate; do not create a
second slot reader. Monitor retained WAL/disk while stopped.

Export each connector against its original worker into a distinct file:

```bash
python3 scripts/connect-offset-migration.py export --url http://127.0.0.1:18084 --connector inventory-outbox-connector --file /secure/release/inventory-before.json
```

Export Orders and Payments similarly. Keep original offset, config and status
topics intact. Empty/missing offsets require investigation rather than a new
snapshot or offset reset. Protect all exports even though they contain no passwords.

### 3. Register stopped and import

Render the final connector overlay to a private temporary manifest:

```bash
kubectl kustomize platform/connectors/environments/aks > /secure/release/connectors-final.yaml
python3 scripts/connect-offset-migration.py create --url http://127.0.0.1:18083 --connector inventory-outbox-connector --manifest /secure/release/connectors-final.yaml
python3 scripts/connect-offset-migration.py import --url http://127.0.0.1:18083 --connector inventory-outbox-connector --file /secure/release/inventory-before.json
python3 scripts/connect-offset-migration.py verify --url http://127.0.0.1:18083 --connector inventory-outbox-connector --file /secure/release/inventory-before.json
```

Repeat for Payments. Orders already exists on the destination: verify its stopped
offsets against the Orders export without re-registering it. `create` intentionally
fails if a connector already exists. When resuming an interrupted procedure,
inspect the existing stopped registration privately, then continue with import
and verify; do not delete an existing connector to make `create` pass.

Apply only the three final `KafkaConnector` CRs with `spec.state: stopped` and
`strimzi.io/pause-reconciliation=true`, keeping all worker CRs for now. This changes
their cluster labels without enabling tasks. Unpause **only** the shared orders
worker and these three connector CRs, wait for Strimzi to observe the new labels
and stopped state, and re-check REST state, empty tasks, inactive slots and the
three offset comparisons. Old workers remain paused so their stopped registrations
cannot be restarted or concurrently reconciled.

### 4. Restart, drain, then retire original workers

While connector CRs remain `spec.state: stopped`, pause reconciliation on the
shared worker and connectors again. Use the helper's `resume` action against
18083 with each connector's own export; it verifies offsets again before resuming:

```bash
python3 scripts/connect-offset-migration.py resume --url http://127.0.0.1:18083 --connector inventory-outbox-connector --file /secure/release/inventory-before.json
```

Repeat Orders and Payments. If only some resume, keep old workers stopped and
investigate; never resume the old registrations alongside the shared worker.
Verify all three connectors and their single tasks RUNNING, each slot active with
only one reader, advancing source offsets, falling outbox/backlog/consumer lag,
and eventual checkout completion. Look for snapshot restarts, duplicate events,
dead letters and missed processing. Validate the application-owned expectations in
[SLO observability](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/operations/slo-observability.md).

Only after these checks, remove `spec.state: stopped` from the three connector CRs
and unpause shared-worker/connector reconciliation. Verify all remain healthy.
Advance only the `eurotransit-connectors` Application Git source to the reviewed
functional revision, keeping its automation disabled. Retire the old
Inventory/Payments worker CRs in that controlled sync; do not delete their
internal topics or state. Verify convergence to exactly one worker and three
connectors, and verify old internal topics still exist after pruning. Keep the
root and affected child automation suspended through the subsequent metric-filter
and resource-budget stages. Restore policies only at the end of the complete
release, as described in the pre-merge GitOps gate.
The normal final overlay is not safe to auto-sync before this migration completes.

### Rollback

Before any destination connector restarts, keep parent/child automation and
Strimzi reconciliation suspended. Stop and verify all destination tasks, confirm
inactive slots, and restore the original worker/connector topology with connector
CRs explicitly `spec.state: stopped` and `strimzi.io/pause-reconciliation=true`.
Verify original stopped registrations still have the exported offsets. Reconcile
stopped ownership, re-pause, then resume the original registrations one at a time
using their own verified exports. Remove the stopped state and restore
reconciliation only after checks.
Orders remains on its existing worker throughout.

**After any destination connector has restarted, pre-migration exports are stale.**
Suspend parent/child automation and relevant Strimzi reconciliation again. Stop
all three connectors on the shared worker, wait for no tasks and inactive slots,
and export **fresh current offsets** to new files, including Orders. Restore the
old worker CRs and their exact original config/internal-topic identities, but keep
connector CRs stopped and paused. Allow only worker rollout, then pause their
reconciliation before REST operations. Verify old registrations are stopped; if
missing, register them with `initial_state: STOPPED` from the preserved manifest.
Import Inventory/Payments' **fresh** offsets into their original workers and
compare them byte-semantically by partition with `verify`. Orders uses its current
shared-worker offsets and is verified against the fresh Orders export.

Restore old cluster labels with `spec.state: stopped`; carefully unpause only the
intended workers/connector CRs to reconcile stopped ownership, and verify inactive
slots and matching fresh offsets again. Pause reconciliation while issuing guarded
`resume` with the fresh files, then remove the stopped state and restore policies.
Verify backlog recovery, checkout completion and three single readers. Never
reset offsets, recreate publications/slots, or reuse the earlier exports after
processing resumed. If fresh offset import cannot be verified, remain stopped.

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
