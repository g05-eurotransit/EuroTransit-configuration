# AKS memory reduction: offline verification

Both branches started at `7e4a146dcb2f1d8b6fdde704222b6f1d90dba5a4`
(`origin/main`, including monitoring single ownership). The resource budget branch
is based on the completed functional reduction branch. On 2026-10-05 both were
rebased onto `ce8f6cf1d465fb91086b710261084c6b44c8a3f2`, incorporating the
cert-manager/load-test recovery (#40) and PostgreSQL storage recovery (#43).
The original checkout and
its uncommitted report were preserved. The branches are prepared for remote
review; no cluster changes or merges were performed.

## Reproduce

Requires Python 3 with PyYAML, Helm and kubectl. The checker uses only
`helm template` and `kubectl kustomize`; it never queries the Kubernetes API.
It discovers pinned Helm archives from `~/.cache/helm/content`, or from a directory
of `.tgz` archives passed as `--chart-cache`. Populate that directory with the
versions below if the local Helm content cache is unavailable.

```bash
baseline_dir="$(mktemp -d)"
git archive ce8f6cf1d465fb91086b710261084c6b44c8a3f2 | tar -x -C "$baseline_dir"
python3 scripts/check-aks-memory.py \
  --baseline-root "$baseline_dir" \
  --output /tmp/eurotransit-memory-verification \
  --budgets
python3 scripts/test-check-aks-memory.py
python3 scripts/test-connect-offset-migration.py
scripts/render.sh kind
scripts/render.sh aks
```

For the functional branch alone, run the checker from the budget worktree with
`--root ../memory-reduction` and omit `--budgets`. The output contains per-owner
AKS/Kind manifests and `budget.json`. Keep render artifacts private: Helm can
produce bootstrap Secret payloads. Kind equality now compares every field,
including Secret data and references; the pinned Kind charts do not require
random-payload exclusions.

Optional saved inventories can be added without accessing a cluster:

```bash
python3 scripts/check-aks-memory.py \
  --baseline-root "$baseline_dir" \
  --output /tmp/eurotransit-memory-verification \
  --budgets --nodes 3 \
  --inventory-pods /secure/inventory/pods.json \
  --inventory-nodes /secure/inventory/nodes.json
```

Inventories must be refreshed before a future release. The node count must match
the intended topology. If no Eraser scan pod is present in an inventory, its
per-node request and the future simultaneous-scan scenario are reported as `null`
(unknown), rather than zero. The absence of active scans does not qualify future
scan capacity. The checker does not simulate placement, affinity, taints,
volume topology, CPU scheduling or pressure eviction. It renders local owner
sources; Kind's unchanged remote Keycloak Operator source remains pinned to
26.7.0. Its exact upstream files are vendored and checksum-verified for AKS.

## Verified on 2026-10-01

Pinned charts: Argo CD 10.2.2, Traefik 36.3.0, cert-manager v1.18.2,
CloudNativePG 0.24.0, Strimzi 0.46.1, kube-prometheus-stack 75.15.1,
Argo Rollouts 2.41.1 and Sealed Secrets 2.5.19. Helm includes CRDs and uses
Kubernetes 1.33 capabilities. Kustomize renders all local GitOps owners,
bootstrap/root Applications and both environments.

Checks passed:

- Both branches render Helm and Kustomize; Kind matches the baseline.
- AKS has one `orders-outbox-connect` worker and three connectors with unchanged
  complete specs, worker group/internal topics, 128m/512m heap and Secret references.
- Dex and Kafka User Operator are absent. ApplicationSet has zero replicas because
  the pinned chart renders its Deployment unconditionally. Topic Operator and
  Keycloak remain.
- Grafana has one container; its 40 dashboard ConfigMaps are mounted without
  `subPath`: 28 monitoring chart dashboards, three EuroTransit and nine Strimzi.
  Dashboard JSON and datasource provisioning data match the baseline exactly.
- All chart/custom alert and recording rules are preserved. The API server filter
  preserves the default relabeling list and adds only the requested families,
  with no matching dashboard/rule dependencies. Required metric families,
  retention and intervals are retained.
- The budget branch passes request ≤ limit checks for active Helm containers,
  init containers, hooks and owner CRs, including modeled config reloaders.
  Existing rendered CPU budgets are preserved. Rendered objects have one owner.
- All five Keycloak 26.7.0 upstream checksums pass. Of its 20 rendered objects,
  only the Deployment memory request differs from the upstream base; CRDs, RBAC,
  ServiceAccount, image and CPU are preserved.
- Ten scheduling-accounting/preservation tests and five REST migration simulator tests pass.
  The REST simulator covers fresh-offset rollback, stopped-only offset writes,
  missing/empty/mismatched offset guards, malformed status rejection and
  literal-credential rejection. Dashboard removal and Kind Secret changes are
  rejected; ownership checks include Argo destination namespaces.

## Requests and capacity

The final owner renders give these conservative memory scheduling requests:

| Scenario | MiB |
| --- | ---: |
| Project steady state, including three node-exporters and Argo Rollouts | 5,280 |
| All temporary jobs together, including realm import and CNPG bootstrap | 1,056 |
| Largest single Deployment rollout surge: orders | 320 |
| All rendered Deployment surges together | 2,592 |

Normal init containers use the maximum of regular-container sum and largest init
request; restartable init sidecars and Pod overhead are accounted for. The
Prometheus and Alertmanager pods include their 24Mi reloaders; init reloaders do
not add another steady 24Mi. Operator-created bootstrap/recovery/import pods use
the persistent CR budgets and must be checked against the next live inventory.
The temporary sum is an upper bound; some jobs run in sequence or instead of a
steady pod. It must not be treated as an assertion that all can start together.

The saved three-node inventory under `/tmp/eurotransit-memory-{nodes,pods}.json`
was used read-only for these estimates:

| Quantity | MiB |
| --- | ---: |
| Aggregate allocatable memory | 8,369.17 |
| Normal AKS-managed active pod requests, excluding Eraser scans | 2,172 |
| Estimated steady residual | 917.17 |
| One active Eraser scan in the saved snapshot | 550 |
| Residual including that active scan | 367.17 |
| Three simultaneous Eraser scans | 1,650 |
| Residual with three scans | −732.83 |
| Residual with all temporary jobs and one orders surge, excluding scans | −458.83 |

The plan's approximate 981Mi residual excluded the existing 64Mi Argo Rollouts
controller. The final calculation retains that controller and counts its request.
Allocatable already excludes kube/system reservations; subtract managed pod
requests once. These figures compare **requests**, not actual memory consumption
or simultaneous limits.

| Saved node suffix | Allocatable MiB | Normal managed requests MiB | Remaining before project pods, after node-exporter MiB |
| --- | ---: | ---: | ---: |
| vms37 | 2,789.73 | 556 | 2,217.73 |
| vms38 | 2,789.72 | 980 | 1,793.72 |
| vms39 | 2,789.73 | 636 | 2,137.73 |

These remaining capacities are not free space: all other project pods still need
placement. The active Eraser additionally uses 550Mi on vms39. Aggregate headroom
cannot establish that a particular 512Mi pod or an init job fits on a node.
One node unavailable and three simultaneous Eraser scans are not qualified.
Migration must also budget the two original Connect workers until retirement;
their pre-budget requests are 256Mi each. Follow the controlled pause and offset
transfer before pruning them.

Use the [release and offset-safe rollback runbook](aks-memory-reduction-runbook.md)
and [persistent resource budgets](aks-resource-budgets.md). Release one change at
a time; verify login, checkout, three outbox flows, dashboards and GitOps, then
qualify startup and at least 30 minutes of load without OOM, eviction or memory
Pending. These live checks remain future release gates.

## Refreshed verification on 2026-10-05

Both branch renders were compared with current `main` at `ce8f6cf`, rather than
the original baseline. All Helm/Kustomize, topology, provisioning, rule, CPU and
ownership checks passed. Kind matches current `main` exactly, including the
upstream load-test Job correction. Twelve budget/preservation tests and five
offset-migration simulator tests pass; all five Keycloak upstream checksums pass.

Rebase conflicts were resolved by retaining PostgreSQL storage at **10Gi** and
the cert-manager validating webhook namespace selector from #40, while adding
only the planned resource budgets. The load-test reconciliation Job script and
the other #40/#43 changes remain unchanged.

Read-only live checks found all 14 Applications Synced/Healthy, all 65 active pods
Ready, PostgreSQL Ready and all three connectors/tasks RUNNING. Monitoring's last
operation is still marked Failed, but it finished on 2026-08-19 after a Grafana
progress deadline; its current sync and health are good. There are no
ApplicationSet or KafkaUser resources, and no Dex/OIDC configuration keys in
`argocd-cm`. The 40 live dashboard ConfigMaps and 37 PrometheusRule resources have
no references to the proposed dropped metric families. These checks do not cover
dashboards stored only in Grafana's database or external metric consumers.

The refreshed inventory has 8,369.17Mi allocatable and 2,132Mi normal managed pod
requests. Final project requests remain 5,280Mi, leaving **957.17Mi** aggregate
request headroom. All temporary jobs plus one orders rollout would exceed that
headroom by 418.83Mi. No Eraser scan pod is present, so current scan sizing is
unknown; at the earlier observed 550Mi per scan, three scans would exceed the
new headroom by 692.83Mi. The historical size is an assumption, not a current
measurement.

The same live check reported node working-set memory of 3,204Mi, 2,507Mi and
3,134Mi (114%, 89%, 112% of allocatable) on nodes ending vms70, vms71 and vms72.
All three nodes are Ready with MemoryPressure=False. Working-set usage differs
from scheduling requests; healthy Applications do not establish rollout capacity.
Current requests on those nodes are respectively 2,370Mi, 1,492Mi and 2,368Mi.
Final placement, startup and the 30-minute load test remain release gates.

Root/child auto-sync and pruning still follow `main`; no merge, GitOps pause,
sync, migration or deployment was performed during this review. Complete the
pre-merge pause/pinning gate in the release runbook before merging either PR.

## Technical review before push

The review additionally checked the exact Kafka 3.9 and Debezium 2.7.0 source
versions used by the Connect image:
[Kafka SourceConnector](https://github.com/apache/kafka/blob/3.9.0/connect/api/src/main/java/org/apache/kafka/connect/source/SourceConnector.java)
and [Debezium BaseSourceConnector](https://github.com/debezium/debezium/blob/v2.7.0.Final/debezium-core/src/main/java/io/debezium/connector/common/BaseSourceConnector.java). Offset import must still be qualified against
the actual image during the maintenance window; the simulator exercises the
procedure and safeguards, not a running Debezium task.

Review fixes: the runbook now requires the GitOps pause and source pinning before
merging to `main`, with staged values/CR changes instead of an early whole-overlay
sync. Pre-start rollback explicitly retains stopped, paused connector CRs. The
REST helper rejects missing task lists, empty partition/offset objects and
malformed credential references; YAML parse errors are redacted. It ignores proxy
environment variables for loopback operations. Offline verification
compares complete Kind Secret data, checks the complete baseline dashboard set,
and resolves default destination namespaces for ownership.
