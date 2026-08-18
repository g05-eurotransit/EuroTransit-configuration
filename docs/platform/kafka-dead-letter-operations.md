# Kafka dead-letter topic operations

`order-placed-dlt` is the dedicated dead-letter topic for the Orders consumer
of `order-placed`. It is declared as a Strimzi `KafkaTopic` in
`platform/strimzi/kafka-topics.yaml`; it is not an alias for the existing
`eurotransit-dead-letter` topic. That legacy topic remains declared because
removing it is outside this change; no current application consumer or
producer reference to it is known.

Kafka broker topic auto-creation is disabled and the Strimzi Topic Operator is
enabled. Consequently, the topic must be present in the GitOps desired state
before the Orders dead-letter recoverer is deployed. The base Strimzi
kustomization is included by both Kind and AKS; the Kind overlay changes every
managed topic to one replica for its single-broker topology, while the current
AKS overlay preserves the base replication factor of three. Rendering the AKS
overlay validates the manifest shape, but the existing constrained one-broker
AKS profile cannot reconcile any three-replica topic until its broader broker
and topic-replication mismatch is resolved.

## Partitioning and retention

`order-placed` has three partitions and `order-placed-dlt` also has three.
`DeadLetterPublishingRecoverer` defaults to publishing a failed record to the
same partition number as its source record. Matching the source partition count
therefore makes every possible `order-placed` source partition valid at the
destination and preserves the partition-level failure context. A smaller DLT
would make failures from an unavailable destination partition unrecoverable.

The DLT uses `cleanup.policy: delete` and retains records for 14 days
(`1209600000` ms). This is deliberately longer than the seven-day normal event
retention so on-call staff have two weekly operational-response cycles to
detect, investigate, and reprocess a poison record before automatic expiry.
It avoids treating the DLT as a permanent archive; durable incident evidence
must be captured in the incident record before that window ends.

The application-level recoverer destination and consumer behavior belong to
the application repository. Its deployment contract for this path is the
literal topic name `order-placed-dlt`; configuration must not redirect it to
`eurotransit-dead-letter`.
