# Kind worker loss and PostgreSQL failover

Status: executable local profile and experiment runner; see the dated report for observed results.
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
  gates logical delivery on one physical standby. Verify all slots exist with
  initialized restart/confirmed LSNs on both standbys before injecting failure;
  no external consumer may own them. Initial slot synchronization
  can require further WAL activity; a loaded extension alone is insufficient.
  `platform/cloudnativepg/values-kind-ha.yaml` sets the operator's
  `STANDBY_TCP_USER_TIMEOUT` to 5000 ms. Verify `tcp_user_timeout=5000` on each
  standby without printing its complete connection string. The default in this
  operator version is the operating system timeout. Reload the operator after
  changing its ConfigMap and allow PostgreSQL's rolling update to finish.
- `platform/connectors/environments/kind-ha`: two workers in one distributed
  Connect group, three connectors, replicated internal topics and required
  worker separation. Each connector still has one active task. The HA profile
  bounds `scheduled.rebalance.max.delay.ms` to 10000 (the default can defer task
  reassignment for five minutes) and flushes offsets every 5000 ms. These are
  local Connect settings, not application retry or timeout changes.
  The HA-only Strimzi values reconcile every 15 seconds so its existing finite
  connector auto-restart policy can observe failed tasks sooner. The policy's
  own backoff still applies; this is not a 15-second pipeline recovery guarantee.
- `charts/eurotransit/values-kind-ha.yaml`: two replicas of Catalog, Orders,
  Inventory and Payments, required hostname anti-affinity and PDB minAvailable 1.
  Notifications stays single replica, with an interruption allowed in this scope.
  Frontend has two replicas; its node distribution must be checked separately.
- Ingress and identity are single replicas outside the fault target. Their HA is
  not demonstrated. PDBs govern voluntary eviction, not unexpected worker loss.
- Prometheus, Grafana and kube-state-metrics run on the control plane to retain
  evidence throughout the fault. Per-node exporters remain on all nodes.

The HA-only R2DBC pool override validates sessions with `SELECT 1`, limits
acquisition/creation to 3 seconds and validation to 1 second, and retires idle
connections after 10 seconds. These values were introduced after the first
worker-freeze run promoted PostgreSQL but failed all seven post-fault admission
attempts. Application images/code and the dev/AKS profiles are unchanged. This
experiment does not introduce additional application retries or admission control.
Subsequent runs still failed recovery during the freeze: the pool was not the
sole cause. A remaining standby was not streaming and later repeated the failure
even after a fresh rebuild. New-primary sessions waited on `IPC/SyncRep` while
the other standby's connection to the old primary remained stuck. Promotion
alone therefore did not restore writable synchronous replication.

The HA ingress optionally retries Catalog GET transport failures twice with a
500 ms dial timeout and 1 second response-header timeout. This never retries
checkout POSTs. Its failover claim requires a run that actually interrupts a
Catalog replica; a successful browse run with both replicas intact is insufficient.

Synchronous replication is an experimental profile choice for team review. It
adds commit latency and refuses writes if no required standby remains. No claim
of universal RPO zero, partition safety or production readiness follows from one
successful worker experiment.

## Bootstrap

The old single-node cluster was removed with user authorization. Do not delete
another cluster automatically. For a fresh install:

```bash
# On the Linux Docker host, qualify shared inotify limits before testing restarts:
sudo sysctl -w fs.inotify.max_user_instances=1024 fs.inotify.max_user_watches=524288
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

## Execute the bounded experiment

After bootstrap, use the host k6 binary and the local DNS entries for
`eurotransit.local` and `keycloak.eurotransit.local`, both resolving to loopback.
The runner permits self-signed TLS only for these fixed local endpoints.
Kafka diagnostics use short-lived Pods with separate memory limits rather than
launching another JVM inside a broker's memory cgroup. They have no API token,
a bounded lifetime and unconditional deletion on exit.

```bash
kubectl --context kind-eurotransit -n monitoring port-forward \
  --address 127.0.0.1 svc/kube-prometheus-stack-prometheus 19190:9090
# In another terminal, from this repository:
python3 scripts/kind-ha-experiment.py baseline
# After an instance replacement, align the CDC barrier with live instance IDs:
python3 scripts/kind-ha-experiment.py prepare-cdc
# If standby logical slots are not initialized (including after primary rejoin):
python3 scripts/kind-ha-experiment.py warmup
python3 scripts/kind-ha-experiment.py fault --fault-mode worker-stop
# Explicit longer observation of the existing finite connector auto-restart policy:
# python3 scripts/kind-ha-experiment.py fault --fault-mode worker-stop --fault-seconds 180
# A different failure, retained because it exposed unresolved recovery problems:
# python3 scripts/kind-ha-experiment.py fault --fault-mode worker-freeze
```

The baseline makes two real sandbox checkouts. `warmup` checks the slot gate
and executes at most four such batches, stopping immediately once all standby
slots are initialized. Other preflight failures are never waived. Three bounded
seat-availability reads warm cold auth/JWK/database caches before the measured
harness; their responses remain in `setup-warmup.json`. A failed checkout setup
is preserved and never rewritten as a passing run. The fault run makes at most eight,
with one checkout VU, 12-second spacing after each outcome and one independent
Catalog VU for 180 seconds. By default it SIGKILLs the current primary's Kind
worker and starts the same container after 90 seconds, following the first
successful checkout. It preserves the node's writable layer and volumes. The
separate `worker-freeze` mode pauses processes instead; it is not equivalent to
node termination and failed checkout recovery in the recorded investigation.
An independent host process restores
the worker even if the runner exits; normal cleanup also unpauses it. The harness
has a 500-second operator deadline, and final-state polling is bounded to 120
seconds. No manual replay/redrive or database business-row cleanup is performed.

Only Kind's local provider Secret is read. The runner never retrieves an AKS
credential. It creates an exclusive run lock and persistent fresh-seat claims.
Private outputs go into ignored `load-results/et-kind-*` directories. Failed
client observations remain intact; the labelled `final-audit/` is separate.
`server-attribution/` also resolves known run idempotency keys in the database:
an HTTP timeout can hide a committed order. This audit verifies those orders and
provider charges without turning the original HTTP 0 into HTTP 202. The ordinary
verifier retains its acceptance failures; financial correctness is a separate result.
A zero runner exit for the fault requires a new primary and at least one checkout
confirmation while the worker is still unavailable, node NotReady observation, healthy
Catalog samples and an independently verified final state for all accepted orders.
It does not claim that all admission attempts succeeded or that an SLO was met.

Initial logical slot synchronization can require multiple warm-up batches and
Debezium offset flushes. Inspect all three slots on each standby and require initialized LSNs before
failure. An active slot is allowed only when `pg_stat_activity` identifies its
owner as the internal `pg_failover_slots worker`; an external walsender on a
standby is rejected. The original blanket `active=false` check produced false
negatives while the extension advanced a synchronized slot. One pre-experiment PostgreSQL checkpoint was used
in the recorded preparation to facilitate restart-LSN advancement. This is not a
slot drop/recreation or a repair of a failed order. Do not bypass the slot gate
or replay business events to manufacture a pass.

## Acceptance checklist before injection

1. Four Ready nodes, no pressure/OOM, enough host headroom for the experiment.
2. Three Ready PostgreSQL instances on distinct workers; inspect synchronous
   standby configuration and streaming state, not just the Cluster Ready flag.
3. Three Kafka brokers, RF 3 and full ISR for business and Connect topics.
4. Both Connect workers and all three tasks Ready; outbox slots initialized on
   both PostgreSQL standbys. Require both CR status and live REST task status;
   the operator's last status can be stale during failure.
5. Two Ready replicas on distinct workers for each critical backend. Identify
   the replicas that will be interrupted together with PostgreSQL.
6. Healthy Catalog, successful real sandbox checkout, independent provider
   audit, attributable fresh seats, working metrics and retained raw evidence.
7. Team-owned recovery and availability criteria recorded before the fault.

The runner requires both physical standbys to be streaming from the current
primary, with replay lag below 1 MiB before setup and zero at injection. Ready
3/3 alone was misleading during the initial attempts. A standby that has crossed
onto an incompatible timeline must be repaired before another experiment. In
the recorded investigation, the version-matched CNPG plugin replaced only the
divergent standby with `destroy ... --keep-pvc`, after checking an authoritative
primary and a healthy synchronous standby. The detached old PVC was preserved.
After such a repair, run `prepare-cdc`, then `warmup`; never drop logical slots
or replay orders to bypass these gates. This assisted repair is not evidence of
automatic recovery.

## Combined experiment

Proposed hypothesis for team ownership: a single worker loss triggers primary
promotion while surviving service replicas and Kafka quorum remain available;
accepted orders converge without operator replay, oversell or duplicate charges.
A database promotion can cause temporary HTTP errors; measure them explicitly.

1. Preserve node/pod UIDs, placements, PostgreSQL settings/LSNs/slots, Kafka ISR,
   metrics and the run ID. Generate bounded checkout and continuous Catalog load.
2. Resolve the current primary and its worker immediately before injection.
   Refuse a control-plane target, a non-Kind context or an unexpected container.
3. Stop only that worker container with SIGKILL for a bounded interval, with an
   independent host-side restart watchdog and unconditional restoration on exit.
   For a process-freeze experiment, explicitly select `worker-freeze` instead.
   Do not delete the worker or its PVCs. Keep one injected failure per experiment.
4. Observe node NotReady, primary promotion, `-rw` endpoint change, surviving
   API replicas, Kafka leaders/ISR and connector recovery. Continue traffic and
   polling; preserve original client deadlines and HTTP errors.
5. Restore the worker and verify old-primary rejoin, three Ready database
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

Connect configuration reference: [Apache Kafka worker rebalance delay](https://kafka.apache.org/38/configuration/kafka-connect-configs/).

Pool configuration references: [Spring Boot properties](https://docs.spring.io/spring-boot/3.4/appendix/application-properties/) and [R2DBC pool validation and eviction](https://github.com/r2dbc/r2dbc-pool).

TCP timeout reference: [CNPG 1.26 operator configuration](https://cloudnative-pg.io/docs/1.26/operator_conf/).
