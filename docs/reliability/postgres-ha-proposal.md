# PostgreSQL persistent HA proposal

Status: local proposal based on `e13c464`, 2026-10-17. **Not activated.**
The ordinary AKS owner and Argo source still select one instance. Nothing in
this proposal changes a running cluster, sync policy, PVC or application code.
The historical three-instance base is overridden by AKS's one-instance patch;
it is not evidence of deployed HA.

## Proposed profile and boundaries

`platform/environments/aks-ha` layers over the existing AKS runtime resources,
changing only the CNPG Cluster: two instances, required hostname anti-affinity,
explicit asynchronous replication (`minSyncReplicas: 0`, `maxSyncReplicas: 0`),
PDB enabled and zero additional failover delay. Existing per-instance budgets,
10Gi storage, roles, monitoring and bootstrap remain inherited.

Two instances are the smallest primary/standby profile that can promote an
already running standby after a primary pod or host failure. A third instance
provides a second standby and keeps a standby after one instance fails; it adds
another full instance's cost. Neither count guarantees application availability,
rescheduling after a host loss, or safe concurrent maintenance. Required hostname
placement intentionally leaves an instance Pending instead of co-locating it.
PDBs constrain voluntary evictions; they do not prevent a crash or node loss.
`failoverDelay: 0` adds no delay after detection; it is not a zero-second RTO.

| Profile | Instances | CPU request / limit | Memory request / limit | Requested storage |
| --- | ---: | ---: | ---: | ---: |
| Ordinary AKS (unchanged) | 1 | 50m / 500m | 192Mi / 512Mi | 10Gi |
| Proposed AKS HA | 2 | 100m / 1000m | 384Mi / 1024Mi | 20Gi |
| Three-instance alternative | 3 | 150m / 1500m | 576Mi / 1536Mi | 30Gi |

The two-instance increment is 50m CPU and 192Mi memory requested, 500m CPU and
512Mi memory in summed limits, and one 10Gi PVC. Recovery/clone jobs inherit the
192Mi/50m request and must be included for actual start sequencing; budget overlap
conservatively rather than assuming all jobs and rollouts fit simultaneously.
Storage totals describe desired instance volumes, not retained PVC history or
backup capacity. No PVC deletion is part of activation or rollback.

**Durability decision remains open.** Async failover can lose acknowledged seat,
order or payment database commits that have not replayed on the standby, while
customer-visible or external provider effects survive. This profile alone cannot
establish never-oversell or money-path durability under failover. The team must
review that risk and decide the required consistency/durability policy before
calling this a complete resilience solution. Synchronous replication trades
commit latency and write availability when standbys are unavailable for stronger
commit durability; no synchronous configuration is proposed or tested here.
The team owns RPO and RTO definitions and acceptance. No numeric objective is
invented and the previous timings are measurements, not a pass threshold.

The [2026-10-12 experiment](postgres-failover-2026-10-12.md) temporarily used two
instances: promotion was observed after approximately 3.51s and a successful
Orders GET after approximately 5.11s. One accepted order needed manual replay.
That experiment did not prove continuous checkout or automatic convergence.
Application recovery work belongs to the application repository; see its
[chaos plan](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/operations/chaos-experiments.md).

## Read-only capacity snapshot

Read on 2026-10-17 around 08:39 UTC using context `eurotransit`; node metrics
sampled 08:38:47–08:38:52 UTC over approximately one minute. All nodes were Ready
with MemoryPressure=False and no taints. Values are MiB except CPU in millicores.
Memory requests include active pods across all namespaces, effective init
requests and overhead; CPU uses the same effective init rule.

| Node suffix | Allocatable CPU / memory | Requested CPU / memory | Free CPU / memory requests | Node memory metric | Known memory limits |
| --- | ---: | ---: | ---: | ---: | ---: |
| vms208 | 1900 / 2789.72 | 1540 / 2444 | 360 / 345.72 | 2783.25 | 16752.28 |
| vms209 (primary) | 1900 / 2789.73 | 1342 / 2564 | 558 / 225.73 | 2882.02 | 11802 |
| vms210 | 1900 / 2789.72 | 1192 / 2404 | 708 / 385.72 | 2944.09 | 12632 |

Five containers per node have no memory limit; known limits are a lower bound,
not a physical reservation or safe simultaneous-use envelope. Node metrics
include consumption beyond workload requests and differ from allocatable
accounting. Existing primary `eurotransit-postgres-4` runs on vms209. A new
192Mi/50m standby has request-level room on either other node (153.72Mi or
193.72Mi residual after placement). This is necessary but not a scheduler proof:
volume attachment limits, topology, Pod counts and admission must be rechecked.
Runtime memory is already near or above allocatable, and the standby can consume
up to its 512Mi limit. **Startup, load and host-failure capacity are unqualified.**
A test resource waiver does not turn this observation into a safety pass.

All nodes advertise `topology.kubernetes.io/zone: "0"`; Azure disk CSI zone is
empty. Existing primary PVC uses `default`, a `StandardSSD_LRS` Azure disk class
with `WaitForFirstConsumer`. No distinct availability zones or zone-independent
storage were demonstrated. Hostname placement provides host separation only;
there is no AZ-failure claim. A zone-required profile would have no demonstrated
second eligible zone here. A third instance would need all three hosts and still
would not establish AZ HA or enough memory after a host loss.

The owner-budget checker gives ordinary AKS steady requests **5280Mi**, proposed
HA **5472Mi**, three-instance arithmetic **5664Mi**. Temporary requests remain
1056Mi and the largest single rollout surge 320Mi. Against 8369.16Mi allocatable
and 2132Mi normal managed requests, modeled residuals are 957.16Mi ordinary and
765.16Mi HA; HA plus all temporary jobs and one Orders surge is **−610.84Mi**.
Live active requests total 7412Mi, which differs from owner models because live
replicas/jobs and operator pods differ. Use per-node live placement for release.
No Eraser scan was present; future scan cost is unknown. Do not substitute zero.

## Render, schema and placement validation

Chart `cloudnative-pg` 0.24.0 and live operator image 1.26.0 were verified.
The installed v1 CRD accepts the proposed fields. In the pinned operator's
[CreateGeneratedAntiAffinity implementation](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.26.0/pkg/specs/pods.go),
`required` generates `requiredDuringSchedulingIgnoredDuringExecution` matching
`cnpg.io/cluster=eurotransit-postgres` AND `cnpg.io/podRole=instance` at the
hostname topology key. The existing primary has exactly those labels and the
preferred form of that selector. Thus a newly generated required standby cannot
share its host. No required standby pod was created during this review; verify
the actual generated rule and node separation after an authorized activation.
This scheduling rule does not retrospectively relocate an existing pod.

Reproduce offline from this checkout (PyYAML, kubectl, Helm and cached pinned
charts required):

```bash
kubectl kustomize platform/environments/aks-ha > /tmp/postgres-ha-runtime.yaml
python3 scripts/check-aks-memory.py --budgets --output /tmp/postgres-default
python3 scripts/check-aks-memory.py --budgets --platform-profile aks-ha \
  --output /tmp/postgres-ha
python3 scripts/test-check-aks-memory.py
ALLOW_MISSING_AKS_SECRETS=1 scripts/render.sh aks
scripts/render.sh kind
```

`--platform-profile aks-ha` substitutes only the offline runtime Application's
source. It never changes tracked Argo configuration or the cluster. Optional
`--baseline-root` accepts an archived baseline; Kind equality includes every
field, including Secrets. Use `--inventory-nodes` and `--inventory-pods` with
fresh private JSON snapshots to reproduce owner estimates. Render outputs and
live inventories can contain sensitive data; retain them privately.

Strict server-side apply dry-run of only the rendered Cluster initially found
`.spec.instances` owned by `kubectl-patch`. Repeating with `--dry-run=server
--force-conflicts --field-manager=argocd-controller --validate=strict` passed
schema/admission and returned instances=2 plus all intended fields. The force
flag simulated ownership transfer only; no real ownership transfer or scale
occurred. Dry-run proves neither scheduling nor an operator-generated standby.
Future activation must inspect actual managedFields and Argo apply behavior;
this result does not authorize force adoption.

## Future activation and proof gates

These steps require separate review and authorization; they were not executed.

1. Team reviews async durability, node-only failure scope, capacity remediation,
   exact checkout recovery criteria, RPO and RTO. Qualify memory budgets with
   fresh per-node metrics, clone/startup and representative load. If capacity
   does not pass, add capacity or revise budgets with evidence before activation.
2. Save the complete owning Application source and sync policy, parent/root
   source and sync policy, Cluster, managedFields and current pod/PVC inventory
   privately. Review the exact rendered diff and field ownership. Follow the
   existing controlled GitOps release process; retain the full saved policies
   and do not install a permanent imperative pause or source override.
3. In a separately reviewed Git change, append this exact entry to `patches` in
   `platform/argocd/environments/aks/kustomization.yaml`:

   ```yaml
   - target:
       kind: Application
       name: eurotransit-platform-runtime
     patch: |-
       - op: replace
         path: /spec/source/path
         value: platform/environments/aks-ha
   ```

   This selects the existing runtime Application's sole source. Do not create a
   second Application owning the same Cluster or patch a generated pod. Current
   owners track `main` with automated prune/selfHeal; merge is an activation
   boundary and needs the controlled release window. Restore exact saved source
   and full sync policies after any authorized temporary operational controls.
4. Verify GitOps selects the reviewed revision/path, CNPG healthy 2/2, primary and
   standby on distinct hostnames, actual required selector, both PVCs Bound,
   physical replay and lag, no Pending/OOM/eviction, and all outbox tasks healthy.
   Capture a fixed pre-test WAL LSN and wait for standby replay before faulting;
   acknowledge that writes after that LSN remain asynchronous.
5. In an explicitly authorized fault window, record current primary identity/UID
   and inject one reviewed primary-pod failure. Node loss is a separate experiment
   requiring capacity and safety review; a pod kill cannot prove it. Preserve
   original request ledger, accepted and failed idempotency keys, primary timeline,
   read/write errors and recovery, order convergence, seat invariants and provider
   charge audit. Accepted work must converge without operator replay to pass an
   automatic-convergence claim. Manual recovery must be recorded as a failed
   automatic criterion, never rewritten into a pass.
6. Verify replacement standby, WAL catch-up, GitOps convergence, all service and
   connector health, and at least 30 minutes representative load. Compare measured
   results only with the team-approved objectives. Preserve failed runs.

Rollback is a reviewed Git revert of the source-path selection to ordinary AKS,
which requests one instance and removes HA protection. Review CNPG's primary
selection and retained PVC behavior before syncing; never manually delete PVCs
or force restoration of an old primary. Retain recovery evidence and verify
healthy 1/1 if rollback is chosen. If any source or sync policy was temporarily
changed through approved controls, restore the complete saved values, not a
handwritten subset. Nothing here requests a data restore or business replay.
