# Migrate Kafka Connect workers without resetting offsets

Use this procedure only when the live source still has separate Orders, Inventory and Payments workers and the reviewed target consolidates them. AKS already declares a shared worker; Git alone does not prove whether a specific cluster completed migration. Inspect live topology and retained migration evidence first. A healthy shared deployment does not need this migration repeated.

## Prerequisites

Follow [controlled GitOps maintenance](gitops.md#controlled-maintenance), record source revision and resource capacity, retain original worker definitions and keep all internal Kafka topics, slots and publications. Inspect the [Kafka storage gate](aks.md#kafka-storage-before-maintenance) before any broker rollout. Ordinary connector restart is covered by [CDC](../platform/cdc.md).

## Migration procedure

The configured AKS overlay keeps `orders-outbox-connect`, its worker `group.id`, and its
three internal topics, and moves Inventory and Payments onto it. Connector names,
database credentials references, slots, publications, topic prefixes, transforms
and `tasksMax: 1` remain unchanged. The image/runtime is Kafka 3.9 with the existing
128m/512m heap. Do not change heaps during consolidation. Kafka internal topics,
replication slots and publications must never be reset or deleted during migration.

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
Confirm the [controlled-maintenance gate](gitops.md#controlled-maintenance) is still in place: root and connector
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
[SLO observability](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/slo.md).

Only after these checks, remove `spec.state: stopped` from the three connector CRs
and unpause shared-worker/connector reconciliation. Verify all remain healthy.
Advance only the `eurotransit-connectors` Application Git source to the reviewed
functional revision, keeping its automation disabled. Retire the old
Inventory/Payments worker CRs in that controlled sync; do not delete their
internal topics or state. Verify convergence to exactly one worker and three
connectors, and verify old internal topics still exist after pruning. Restore child/root policies only after qualifying the reviewed final topology, following the controlled-maintenance gate.
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
