# Orders shutdown and load-shedding preflight

## Status

At the initial preflight, none of these experiments had run. The healthy-state check stopped before fixture
allocation, checkout traffic, a seat lock or Pod deletion. No failed preflight is
reported as a successful resilience experiment. After explicit user
authorization, the CDC baseline was repaired. [Orders shutdown](kind-orders-shutdown.md)
and [cluster load shedding](kind-checkout-load-shedding.md) subsequently
passed; their evidence remains separate from this setup repair.

## Baseline failure

All three Debezium 2.7.0 tasks were `RESTARTING`. Kubernetes connector readiness
alone concealed this state; the runner also checks live task status. PostgreSQL
had three healthy physical instances, but the `orders_outbox`,
`inventory_outbox` and `payments_outbox` logical slots had `wal_status=lost` and
no restart LSN. Their confirmed positions remained near the last business
traffic at 14:37 UTC. Shared WAL subsequently advanced beyond the HA profile's
1 GB slot retention limit while these databases had no captured activity.

Read-only source inspection found 76 orders, all `CONFIRMED`, no reconciliation
records, and 380 retained outbox rows: 228 Orders, 76 Inventory and 76 Payments.
An isolated Kafka consumer read headers, without values or committing offsets,
from all five populated business topics. **Every one of the 380 outbox event IDs
was present in Kafka.** Orders and Notifications had committed lag zero on all
six populated partitions. Empty refund/DLT partitions had no committed offset;
their lag is undefined rather than a measured numeric zero.

The source rows, source offsets, slot status and Kafka header/lag snapshots are
retained privately under `load-results/cdc-repair-20261017T205210Z`. The
[sanitized evidence](evidence/2026-10-17/orders-shutdown-load-preflight.json)
contains counts and artifact hashes without financial payloads or credentials.

## Authorized restoration and prevention

The Kind-only procedure rechecked unchanged outbox IDs, terminal orders
and empty reconciliation state, acquired the exclusive test lock, paused
connector reconciliation, stopped the three connectors and archived their final
source offsets. It then removed the already-invalidated logical slots,
cleared their source offsets and initialized new streaming positions with a
one-time `snapshot.mode=no_data`. Existing business rows, Kafka records and
application consumer offsets remained intact. After streaming offsets were
committed, normal CR reconciliation resumed with the usual snapshot policy.

This rebase was a **manual baseline repair**, never evidence of automatic
recovery or continuity through the lost WAL interval. Complete outbox-to-Kafka
coverage is a prerequisite; a missing event or changed source blocks it.
Automatic approval review initially rejected execution because dropping slots
and clearing offsets are irreversible. The user then explicitly authorized
repair of this test cluster and execution proceeded. The procedure and original
offsets remain in the private evidence; no second reset was needed.

The HA-only connector patch now emits a transactional logical heartbeat every
10 seconds without changing application tables. A topic predicate applies the
outbox transform only to outbox events. The logical message prefix is explicitly
included; technical message and heartbeat topics are provisioned with RF 3/min
ISR 2 because Kafka disables automatic topic creation. A 35-second idle window
verified advancement of all three confirmed slot positions with unchanged
outbox counts (240/80/80 after the shutdown run).

Two initial prevention checks failed and remain in the private evidence:
missing heartbeat topics prevented offset persistence, and nontransactional
logical messages did not advance confirmed LSNs over the sampled idle windows.
Provisioning the topics and using transactional messages fixed the observed
behavior. No failure was rewritten as a pass. The default Kind and AKS profiles are
unchanged. Debezium documents the [idle database/shared WAL
problem](https://debezium.io/documentation/reference/2.7/connectors/postgresql.html#postgresql-wal-disk-space),
[logical message filtering](https://debezium.io/documentation/reference/2.7/connectors/postgresql.html#postgresql-property-message-prefix-include-list)
and [selective outbox transformation](https://debezium.io/documentation/reference/2.7/transformations/outbox-event-router.html#options-for-applying-the-transformation-selectively).

## Unaffected preparation

The local branch now includes the existing opt-in load-shedding implementation
and the already-merged progressive-delivery/telemetry prerequisite correction.
Rendering verifies exact checkout POST scope, disabled defaults and stable or
weighted service selection. Tests using real Traefik 3.4.3 and a mock backend
passed for both service modes: immediate 429, refused requests not reaching the
backend, unaffected reads/refunds and successful admission after refill. These
tests create no real order or payment and **do not prove cluster load shedding**.

The prepared shutdown experiment will delete the Pod whose Kafka listener is
observed processing a fresh order. A bounded, rolled-back seat-row lock holds
the operation in flight. It will capture readiness, EndpointSlice withdrawal,
shutdown logs and exit status, original client results, eventual ledger state
and an independent Stripe sandbox audit. Normal Pod grace periods apply.

After the CDC baseline is healthy: run shutdown, then the bounded 429/recovery
experiment, then progressive delivery. No remote push or merge was performed.
