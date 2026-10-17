# Kind worker loss and PostgreSQL failover

Status: deployment preparation; checkout baseline and fault experiment are pending.
This profile is isolated from AKS and is not selected by Argo CD.

## Scope

One control plane and three workers on one physical workstation. Interrupt the
worker hosting the current PostgreSQL primary while traffic goes through Traefik.
This is a worker failure test, not a real AZ or workstation failure test. The
control plane, Traefik, Keycloak, CNPG/Strimzi controllers and observability remain
outside the interrupted worker. No AKS resource or GitOps source is changed.
The host's memory is shared by all Kind nodes; this profile does not reproduce
AKS allocatable capacity or Azure CPU credits. Qualify runtime capacity before
injecting failure; configured requests alone are not evidence of spare capacity.

## Configuration

- `platform/kind/kind-ha-config.yaml`: four Kind containers, existing local ports.
- `platform/environments/kind-ha`: three PostgreSQL instances, required hostname
  separation, synchronous commit to one standby with required durability; three
  persistent Kafka broker/controllers, required separation, RF 3 and min ISR 2.
- PostgreSQL 16 and CNPG chart 0.24.0/operator 1.26.0 retain the current major
  versions. `pg_failover_slots` synchronizes the three outbox logical slots and
  gates logical delivery on one physical standby. Verify slots exist and are
  inactive on both standbys before injecting failure. Initial slot synchronization
  can require further WAL activity; a loaded extension alone is insufficient.
- `platform/connectors/environments/kind-ha`: two workers in one distributed
  Connect group, three connectors, replicated internal topics and required
  worker separation. Each connector still has one active task.
- `charts/eurotransit/values-kind-ha.yaml`: two replicas of Catalog, Orders,
  Inventory and Payments, required hostname anti-affinity and PDB minAvailable 1.
  Notifications stays single replica, with an interruption allowed in this scope.
  Frontend has two replicas; its node distribution must be checked separately.
- Ingress and identity are single replicas outside the fault target. Their HA is
  not demonstrated. PDBs govern voluntary eviction, not unexpected worker loss.
- Prometheus, Grafana and kube-state-metrics run on the control plane to retain
  evidence throughout the fault. Per-node exporters remain on all nodes.

Synchronous replication is an experimental profile choice for team review. It
adds commit latency and refuses writes if no required standby remains. No claim
of universal RPO zero, partition safety or production readiness follows from one
successful worker experiment.

## Bootstrap

The old single-node cluster was removed with user authorization. Do not delete
another cluster automatically. For a fresh install:

```bash
kind create cluster --config platform/kind/kind-ha-config.yaml
kubectl config use-context kind-eurotransit
# Set STRIPE_SECRET_KEY to a sandbox key in the invoking environment.
KIND_PROFILE=ha ENABLE_OBSERVABILITY=1 scripts/kind-up.sh
```

The bootstrap builds images unless `SKIP_BUILD=1`. For preloaded images, use
`KIND_IMAGE_TAG=kind-ha SKIP_BUILD=1`; all seven local image tags must already
exist. Record the source commits, registry digests and local image IDs. The local
technical Keycloak client secret is generated and retained in Kind. Provider
credentials must be supplied explicitly; this script never retrieves AKS secrets.
Database and demo-user credentials are the existing local-development credentials.
Do not expose this local profile as a public deployment.

Every kubectl/Helm cluster command in the bootstrap specifies the Kind context;
changing the default context in another terminal cannot redirect these commands.
The ordinary dev profile remains the default. HA bootstrap jobs retain their
bounded lifetime but receive one CPU to avoid spending that lifetime on repeated
JVM startup. `just kind-ha-test` checks the shared Connect group and local smoke
endpoints after application installation.

## Acceptance checklist before injection

1. Four Ready nodes, no pressure/OOM, enough host headroom for the experiment.
2. Three Ready PostgreSQL instances on distinct workers; inspect synchronous
   standby configuration and streaming state, not just the Cluster Ready flag.
3. Three Kafka brokers, RF 3 and full ISR for business and Connect topics.
4. Both Connect workers and all three tasks Ready; outbox slots initialized on
   both PostgreSQL standbys.
5. Two Ready replicas on distinct workers for each critical backend. Identify
   the replicas that will be interrupted together with PostgreSQL.
6. Healthy Catalog, successful real sandbox checkout, independent provider
   audit, attributable fresh seats, working metrics and retained raw evidence.
7. Team-owned recovery and availability criteria recorded before the fault.

## Combined experiment

Proposed hypothesis for team ownership: a single worker loss triggers primary
promotion while surviving service replicas and Kafka quorum remain available;
accepted orders converge without operator replay, oversell or duplicate charges.
A database promotion can cause temporary HTTP errors; measure them explicitly.

1. Preserve node/pod UIDs, placements, PostgreSQL settings/LSNs/slots, Kafka ISR,
   metrics and the run ID. Generate bounded checkout and continuous Catalog load.
2. Resolve the current primary and its worker immediately before injection.
   Refuse a control-plane target, a non-Kind context or an unexpected container.
3. Freeze only that worker container for a bounded interval with an independent
   host-side cleanup watchdog and unconditional unpause on exit. Do not delete
   the worker or its PVCs. Keep one injected failure per experiment.
4. Observe node NotReady, primary promotion, `-rw` endpoint change, surviving
   API replicas, Kafka leaders/ISR and connector recovery. Continue traffic and
   polling; preserve original client deadlines and HTTP errors.
5. Unpause the worker and verify old-primary rejoin, three Ready database
   instances, all Kafka ISR restored and consumer lag convergence.
6. Compare every accepted order with final order/reservation/payment state and
   an independent Stripe sandbox audit. Do not silently replay failed work or
   replace failed client observations with a passing final audit.

Record primary promotion time, first successful database write, first successful
checkout admission and confirmation, maximum Catalog outage, original client
outcomes and total convergence time separately. Recovery after worker restoration
must be distinguished from recovery while the worker remained down.

## Evidence and reporting

Keep raw API, provider and credential-bearing records outside Git. Commit a
sanitized report with hypothesis, steady state, exact topology and image digests,
injection timeline, observations, cleanup and a verdict for each criterion.
The report must distinguish preparation from an executed/passed experiment.

References: [CNPG synchronous replication](https://cloudnative-pg.io/docs/1.26/replication/),
[CNPG PostgreSQL 16 slot extension](https://cloudnative-pg.io/docs/1.26/postgresql_conf/#enabling-pg_failover_slots),
[pg_failover_slots readiness and barrier](https://github.com/EnterpriseDB/pg_failover_slots).
