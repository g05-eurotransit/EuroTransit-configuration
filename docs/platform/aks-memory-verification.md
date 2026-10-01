# AKS memory reduction: offline verification

Both branches started at `7e4a146dcb2f1d8b6fdde704222b6f1d90dba5a4`
(`origin/main`, including monitoring single ownership). The resource budget branch
is based on the completed functional reduction branch. The original checkout and
its uncommitted report were preserved. No cluster changes, merges or publication
were performed.

## Reproduce

Requires Python 3 with PyYAML, Helm and kubectl. The checker uses only
`helm template` and `kubectl kustomize`; it never queries the Kubernetes API.
It discovers pinned Helm archives from `~/.cache/helm/content`, or from a directory
of `.tgz` archives passed as `--chart-cache`. Populate that directory with the
versions below if the local Helm content cache is unavailable.

```bash
baseline_dir="$(mktemp -d)"
git archive 7e4a146dcb2f1d8b6fdde704222b6f1d90dba5a4 | tar -x -C "$baseline_dir"
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
produce fresh bootstrap Secret payloads. Kind equality excludes only those random
Secret payloads; all other rendered fields, including Secret references, match.

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
the intended topology. The checker does not simulate placement, affinity, taints,
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
- Seven scheduling-accounting/parser tests and three REST migration simulator tests pass.
  The REST simulator covers fresh-offset rollback, stopped-only offset writes,
  missing/empty/mismatched offset guards and literal-credential rejection.

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
