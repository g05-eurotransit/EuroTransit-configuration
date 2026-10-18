# Outbox delivery and dead letters

Strimzi reconciles the three PostgreSQL outbox connectors, for Orders, Inventory and Payments. Start them after application migrations and require both custom-resource health and RUNNING connector/tasks. The application [event contract](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/api-design.md#kafka-events) owns producers, consumers and payloads.

## Worker topology

| Environment | Effective worker layout | Source |
| --- | --- | --- |
| Standard Kind | Three per-service workers, one replica each | [Kind overlay](../../platform/connectors/environments/kind/kustomization.yaml) |
| Kind HA | Two replicas in one shared group, three single-task connectors | [HA overlay](../../platform/connectors/environments/kind-ha/kustomization.yaml) |
| AKS | One shared worker, three single-task connectors | [AKS overlay](../../platform/connectors/environments/aks/kustomization.yaml) |

[Base connector definitions](../../platform/connectors/base/kustomization.yaml) own slot, publication, transform and credential references. The application builds its Strimzi-compatible image from `connect/Dockerfile`; AKS pins the published digest. Worker heaps are explicit because automatic host-based sizing previously caused a container OOM. Secret-backed configuration-provider references keep database passwords out of tracked connector configuration.

The [GitOps dependency order](gitops.md) puts migrations before connector startup. Orders consumes `order-placed` and calls Inventory/Payments through HTTP; those services' published events do not form the checkout consumer chain.

## Health and restart

```bash
kubectl -n eurotransit get kafkaconnect,kafkaconnector
kubectl -n eurotransit describe kafkaconnector orders-outbox-connector
```

A connector may be RUNNING while task 0 is FAILED, and CR status can lag REST status. Verify both before experiments or acceptance. `No table filters found for filtered publication` requires the outbox table/migration prerequisite repaired before task restart; record-level error handling cannot fix startup publication errors.

Each connector enables finite Strimzi automatic restart with backoff. A reduced reconciliation interval does not define the task recovery time. Verify that an existing outbox event reaches Kafka and the ordinary consumer progresses; a terminal business refusal can still prove restored delivery. Inspect only non-secret status fields and never log full connector configuration responses.

## Slots and upgrade boundaries

Preserve connector names, group/internal-topic identities, publications and replication slots during upgrades. Worker consolidation requires the [offset-safe migration](../operations/connect-migration.md); restarting an image is not a replay guarantee. Primary failover requires a streaming physical standby and initialized failover slots, not merely PostgreSQL Ready counts.

Kind HA emits transactional logical heartbeats without application-row changes so idle slots can acknowledge shared WAL. Technical topics must exist because auto-creation is disabled. Compare confirmed LSN progress while outbox counts stay unchanged. [CDC repair evidence](../verification/incidents/cdc-slots.md) records an exceptional manual rebase with complete event coverage; it is not a general instruction to drop slots.

## Dead-letter topics

[KafkaTopic manifests](../../platform/strimzi/kafka-topics.yaml) declare `order-placed-dlt` and `refund-requested-dlt`. They are distinct from the legacy `eurotransit-dead-letter` topic. Provision them before deploying the corresponding recoverer; automatic topic creation is disabled.

Each DLT matches its source topic's partition count because the recoverer targets the original partition. A smaller destination would make failures from some source partitions unrecoverable. Exact partitions and retention live in the manifests: DLT retention gives operators a longer response window than ordinary events, but is not a permanent incident archive.

The [Kind](../../platform/environments/kind/kafka-topics-kind-patch.yaml) and [AKS](../../platform/environments/aks/kafka-topics-aks-patch.yaml) overlays both reduce topic replication to one for their single broker. Kind HA retains RF 3/min ISR 2. Render the selected overlay before judging feasibility from base topic replication alone.

Application DLT consumers record incidents without inferring a business outcome. Use the application [recovery runbook](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/operations/orders-recovery-runbook.md) for redrive and settlement.
