# Debezium connector lifecycle

Strimzi reconciles three PostgreSQL outbox connectors, for Orders, Inventory and Payments. Start them after application migrations and require both connector and task health. A Ready Connect process alone does not prove event delivery.

## Runtime and ordering

[Connector manifests](../../platform/connectors/base/kustomization.yaml) own configuration. Standard Kind and AKS use per-service Connect workers; [Kind HA](../../platform/connectors/environments/kind-ha/kustomization.yaml) uses two replicas in one distributed worker group. The application repository builds the Strimzi-compatible Debezium image from `connect/Dockerfile`; AKS pins its published digest.

[GitOps waves](../delivery/gitops-topology.md) place PostgreSQL/Kafka before application migrations and connectors after the marketplace. Direct Kind setup follows the same dependency order. Debezium reads `public.outbox_events`; Orders consumes `order-placed` and coordinates Inventory/Payments through HTTP. Inventory and Payments events do not form the checkout consumer chain. See the authoritative [event contract](https://github.com/g05-eurotransit/EuroTransit-application/blob/dev/docs/design/api-design.md).

Each KafkaConnector enables Strimzi automatic restart with a finite budget. Preserve its backoff: a reduced operator reconciliation interval does not imply the same recovery time. Worker heap limits are explicit because host-based heap sizing caused a worker OOM inside its container budget. Database passwords enter the worker through Secret-backed configuration-provider references.

## Verify and recover

1. Confirm marketplace migrations created the outbox tables before connector startup.
2. Check both custom-resource Ready conditions and the Connect REST connector/task status. A connector can be RUNNING while task 0 is FAILED; CR status can also lag the process.
3. Verify an existing outbox event reaches Kafka and the order progresses using the ordinary consumer. A terminal business failure can still demonstrate restored delivery.
4. For `No table filters found for filtered publication`, repair migration/order prerequisites before requesting a restart. Record-level error handling does not repair a failed startup publication.
5. Follow [Kind HA recovery](../reliability/kind-ha-runbook.md) for primary/slot checks and [CDC recovery evidence](../reliability/kind-cdc-recovery.md) for idle WAL progress. Transactional heartbeat messages advance slots without touching application rows.

```bash
kubectl -n eurotransit get kafkaconnect,kafkaconnector
kubectl -n eurotransit describe kafkaconnector orders-outbox-connector
```

Inspect only non-secret status fields. Never log a full connector PUT/config response. Automatic retries cannot correct permanent configuration errors; restore the reviewed manifest and verify Ready plus RUNNING tasks.

## Offset and recovery boundaries

Keep connector names, group IDs, internal topics, replication slots and publications when upgrading or rolling back. Changing worker topology requires an explicit offset migration; restoring an image alone does not establish safe replay. Do not delete durable state as a connector restart procedure. Primary failover also requires initialized standby slots and a streaming physical standby, not just PostgreSQL Ready counts.

Bootstrap from empty databases and migration to Strimzi were observed on Kind: connectors/tasks became RUNNING after Flyway, existing events progressed, and invalid configuration surfaced as NotReady before declarative repair. Current failover behavior and its restart delays are documented in the [HA report](../reliability/kind-ha-failover.md).

## Alternative considered

A post-install/post-upgrade Helm Job could wait for Flyway, PUT the connector configuration and restart a failed task. It reconciles only during deployment and leaves later runtime task failures unmanaged. Strimzi provides continuous desired-state reconciliation and task restart at the cost of CRDs, a compatible plugin image and explicit Argo health handling. The selected runtime uses Strimzi.
