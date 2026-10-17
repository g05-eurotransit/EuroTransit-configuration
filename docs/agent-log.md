# Agent verification log

The historical application log is maintained in
[EuroTransit-application/docs/agent-log.md](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/agent-log.md).
The following configuration/test cases are observed on 2026-10-12. Detection
and corrections were performed during agent self-review; the team must review
these entries and record its own verification before claiming team ownership.

| Artifact | Concrete mistake | Detection and correction |
| --- | --- | --- |
| Inventory crash observer | Compared `client_addr::text`, e.g. `10.244.0.185/32`, with an IP without the mask. The first two synchronization runs killed no pod. | SQL inspection exposed the mismatch. Replaced the comparison with `host(client_addr)`, required an actual blocker PID and recorded the subsequent UID-conditioned crash. Earlier runs were excluded from crash proof. |
| Reliability telemetry collector | Queried only `kafka_consumergroup_lag` and reported Kafka telemetry missing despite Spring Kafka already exporting lag. | Live Prometheus discovery found per-partition client lag for Orders and Notifications. Added a fallback with an explicit query-source record; tests cover exporter precedence, fallback and both sources absent. Client-position lag is explicitly distinguished from committed-offset lag. |
| Orders rollout manifest | Used unsupported `spec.strategy.canary.canaryReplicaCount`. Helm rendering passed, but the installed CRD rejected it. | Strict server dry-run reproduced the rejection. Replaced it with a supported `setCanaryScale: {replicas: 1}` step. Both Rollouts then passed strict server dry-run. Live rollout proof remains separate. |
| CNPG pre-fault check | Required instantaneous zero lag against a moving WAL position and included logical Debezium replication rows. A healthy physical standby was 56 bytes behind. | The check conservatively skipped the fault. Filtered physical standby application names and waited for replay of a fixed pre-test WAL position. No crash is counted for the skipped attempt. |

Raw evidence is access-restricted under `.resilience-evidence/chaos-20261012` in
the workspace. This log does not turn missed injections or failed client runs
into passing tests. Human verification and merge review remain outstanding.

The live scrape audit also found that ServiceMonitor did not copy the Service
`app` label, although dashboards, alerts and canary HTTP queries filtered by it.
Actual samples carried `application="orders"` but no `app`; a healthy rule
expression could therefore return no samples. The proposed fix adds
`targetLabels: [app]` to every application ServiceMonitor. Its live effect must
be checked after GitOps publication; rendering alone is not sufficient proof.
