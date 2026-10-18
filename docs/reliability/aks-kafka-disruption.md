# Kafka response partition

## Steady state and proposed hypothesis

The Orders consumer group had zero committed-offset lag on all three
`order-placed` partitions. Proposed hypothesis: a bounded broker-response
partition delays checkout but durable publication and consumption recover after
connectivity returns, without operator event replay or duplicate side effects.
The team must review acceptable checkout impact and this hypothesis.

## Fault and observations

An ephemeral, digest-pinned netshoot container in the sole broker pod applied
100% loss to outbound IPv4 TCP responses from port 9092, from **22:20:55 to
22:21:35 UTC**. It used NET_ADMIN without privilege or host networking. The
independent 40-second timer removed the filter; the injector log confirms the
original `noqueue` qdisc. Localhost administrative commands and KRaft ports were
outside the filter. This tests a client/broker response partition, not loss of
broker storage or a quorum failure.

Four fresh checkout fixtures ran sequentially. The initial harness failed with
exit 99 because its completion deadline was exceeded; the original verdict and
ledger are retained. After healing, fresh authenticated observations found
**4/4 CONFIRMED without event replay**. A derived final-state audit passed with
zero violations and four independently matched Stripe sandbox charges, with no
unmatched provider effects. Catalog returned HTTP 200 in all 102 probes.

Broker-side group descriptions before and after showed `order-placed` lag zero
on all three partitions. Log-end offsets moved from 118/100/110 to 121/100/112;
these are group-wide observations, not an exact count of this run's events.
Consumer commits caught up with those offsets. No business SQL writes or resets
of consumer offsets were used.

## Consumer lag telemetry

Orders and Notifications already expose
`kafka_consumer_fetch_manager_records_lag` in Prometheus. The collector previously
queried only `kafka_consumergroup_lag`, from an exporter not installed here. Its
new fallback collects the existing client metric and records the exact query
source. It preserves NOT_VERIFIED when neither source has samples.

Client fetch-position lag differs from broker-side committed-offset lag. It
cannot establish the backlog of a stopped consumer, and samples may disappear
or become stale during a fault. The broker CLI snapshots independently check
committed offsets; a persistent exporter remains useful for stopped groups.
No metric source is silently combined with another or treated as a correctness
verdict. Telemetry is attributed to namespace and time window, not exclusively
to the four test orders.

## Conclusion and evidence

Automatic convergence and final money-path invariants held after this bounded
partition. The client completion deadline did not hold. This does not establish
AZ tolerance, broker durability or a production latency SLO.

Restricted injector logs, Catalog probes and offset snapshots:
`.resilience-evidence/chaos-20261012/kafka-disruption-20261012T222044Z`.
Original run: `load-results/kafka-disruption-20261012T222044Z`.
Final audit: `load-results/kafka-disruption-20261012T222044Z-final-audit-20261012T222233Z`.
Resource-saturation overrides were authorized; other runner checks remained active.
