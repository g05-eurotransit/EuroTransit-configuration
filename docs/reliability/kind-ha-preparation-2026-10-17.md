# Kind HA preparation — 2026-10-17

Status: platform deployed; combined worker-loss/checkout proof **not executed**.

The previous single-node local cluster was deleted with explicit user approval.
The replacement `eurotransit` cluster runs Kubernetes v1.34.0 with one control
plane and three Ready workers. All deployment commands target
`kind-eurotransit` explicitly. AKS resources were not modified.

| Check | Observation | Verdict |
| --- | --- | --- |
| PostgreSQL instances | Three Ready instances on three different workers | Passed |
| PostgreSQL replication | Both standbys `streaming`, `sync_state=quorum`; `ANY 1` active | Passed |
| CDC prerequisites | `pg_failover_slots` loaded; one-standby delivery barrier configured | Prepared; logical slot initialization/failover still pending |
| Kafka | Three Ready broker/controllers on distinct workers; all 144 partitions across 26 topics have full ISR 3 | Baseline passed; fault recovery still pending |
| Identity | Realm and three bootstrap jobs completed; OIDC HTTP 200; technical token has valid issuer, subject and customer role | Baseline passed |
| Observability | Prometheus, Grafana and collection components running on the control plane | Prepared |
| Critical application replicas | Helm profile renders two replicas with required anti-affinity and PDBs | Render verified; runtime installation pending provider key |
| Checkout and provider audit | Sandbox provider credential not provisioned locally | Not executed |
| Worker loss and PostgreSQL promotion | No fault injected | Not executed |

Initial primary is `eurotransit-postgres-1` on `eurotransit-worker2`; standbys
`-2` and `-3` run on `eurotransit-worker` and `eurotransit-worker3`. Resolve the
primary again at injection time. These placements are observations, not static
assumptions for a future test.

Images were downloaded from the existing registry and loaded into all Kind nodes.
Orders uses `45357ef`, image ID
`sha256:8e142d64c8276d62e55688a5e1493904713070031fef28e29de193755b2198a5`.
The other backend tags are `98bedf2`; frontend uses `4364f1f`. Connect uses the
existing published digest. Full sanitized image provenance is in
[evidence](evidence/2026-10-17/kind-ha-images.json).

Verification: `scripts/render.sh kind-ha`, ordinary `scripts/render.sh kind`,
Helm lint, shell syntax checks, six rendered-profile invariant tests and
server-side dry-run of platform/connector resources passed. Grafana's inherited
secret key names did not match the chart-generated secret; the HA override now
uses `admin-user` and `admin-password`, and Grafana reached 3/3 Ready.
Initial Keycloak client bootstrap waits overlapped the slow realm import. The
HA-only override raises the bounded bootstrap Job CPU limit from 200m to one CPU;
the three idempotent local jobs were restarted after realm import.

At a preparation snapshot the host reported about 7.4 GiB available memory,
before the application replicas and Connect workers were installed. This is not
full-stack or post-failure capacity qualification. No per-worker AKS capacity
parity was imposed. Kind shares one physical host, so no real AZ/host failure
claim is made.

Follow the [runbook](kind-ha-runbook.md) to complete the baseline, initialize and
verify logical slots on both standbys, qualify runtime capacity, record team-owned
acceptance criteria, and execute the bounded combined experiment. Preserve client
errors and independent final-state/provider audits separately. Do not mark node
availability or PostgreSQL end-to-end failover complete from this preparation.
