# Selective application node drain — 2026-10-12

## Steady state and proposed hypothesis

All three AKS nodes and the critical services were Ready. Orders, Catalog and
Inventory each had one replica on node `aks-eurotransit-76738666-vms77`.
Proposed hypothesis: evacuating that node's application workloads should retain
checkout availability. The observed deployment has no application PDBs and no
spare critical-service replica; this experiment tests those actual conditions,
not an assumed HA deployment. Team review of the hypothesis is pending.

## Injection and observations

At 22:24:40.783 UTC the node was cordoned. UID-conditioned `policy/v1` Evictions
of Catalog, Inventory and Orders succeeded at 22:24:40.990–41.401 UTC with the
normal 45-second termination grace. No forced bypass of a PDB was used. Other
workloads, the node, its volumes and its network remained running. This is a
selective application evacuation, not a whole-node crash or an AZ outage.

Six ramp attempts ran with two VUs. Three were accepted and three had technical
HTTP failures. The original harness failed (exit 99). All three accepted orders
later confirmed; their separately labelled final-state audit passed with three
matching Stripe charges, zero unmatched charges and zero invariant violations.
The three rejected attempts remain failures in the original ledger.

| Observation | Result |
| --- | --- |
| Catalog probes | 81/105 HTTP 200; 24 HTTP 503 |
| Catalog unavailable samples | 22:24:42.381–22:25:08.457 UTC |
| Replacement Catalog Ready | 22:25:09 UTC, node vms78 |
| Replacement Inventory Ready | 22:25:17 UTC, node vms76 |
| Orders scheduling | Pending: insufficient CPU/memory on the remaining nodes |
| Recovery intervention | Early uncordon to restore scheduling on vms77 |
| Replacement Orders Ready | 22:26:20 UTC, original node vms77 |
| Orders eviction to replacement readiness | Approximately 99 seconds; includes operator uncordon |

The scheduler explicitly reported `1 Insufficient cpu` and `2 Insufficient
memory`, alongside the cordoned node. Resource-waiver authorization cannot add
physical capacity. Cleanup confirms the node is schedulable again. No workload
requests, limits, replicas or PDBs were changed to manufacture availability.

## Conclusion and follow-up

Availability did not hold. Accepted work recovered without data correction,
with operator restoration of node scheduling. This is not an automatic node
recovery RTO or proof of AZ resilience. Reserve capacity for a failed node,
distribute multiple critical replicas and enable reviewed application PDBs
before repeating a genuine node/AZ experiment. A PDB alone cannot make a
single-replica application continuously available.

## Evidence

Restricted eviction responses, scheduler findings, pod readiness timestamps,
Catalog samples and cleanup: `.resilience-evidence/chaos-20261012/node-drain-20261012T222431Z`.
Original run: `load-results/node-drain-20261012T222431Z`.
Accepted-order audit: `load-results/node-accepted-orders-final-audit-20261012T222704Z`.
