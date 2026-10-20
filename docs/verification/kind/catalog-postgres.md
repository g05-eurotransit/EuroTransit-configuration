# Catalog PostgreSQL verification on Kind

Catalog now serves its existing API from PostgreSQL on `kind-eurotransit`. Two healthy replicas run on different workers. Checkout, commercial refund, pod replacement, database isolation and rollback passed in the bounded local trial. AKS was not changed; this result does not qualify Azure storage or production availability.

The [sanitized evidence](../evidence/2026-10-19/catalog-postgres-kind.json) records source fingerprints, image identities, test results, controller analysis and final state. The [runbook](../../operations/catalog-postgres-kind.md) contains the procedure; the [application reference](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/catalog-storage.md) owns behavior and ownership.

## Environment recovery and scope

The existing four-node Kind cluster initially had failing kube-proxy pods, unready CoreDNS and failing application dependencies. Kube-proxy logged `too many open files`; PostgreSQL instances could not reach the API Service, and Orders could not resolve the PostgreSQL Service hostname. Host inotify limits were 128 instances and 124390 watches. Raising them to 1024 and 524288 and replacing failed pods restored service networking and the application stack. Cluster and PVCs were retained.

The trial used the existing CNPG cluster with an isolated `catalog_db` and Catalog role. The role has no superuser, database-creation or role-creation privileges. Flyway applied the schema and seed migrations once. PUBLIC connection permission on `catalog_db` was revoked. The existing Orders, Inventory and Payments schemas were not migrated.

## Results

| Check | Observed result |
| --- | --- |
| Catalog regressions | 34 tests passed, including the PostgreSQL API suite, complete seeded-data comparison, constraints and repeat-migration preservation |
| Orders regressions | 46 Catalog/refund-related tests passed |
| Deployment wiring | All four combinations of storage mode and progressive delivery passed; the existing 15 Kind HA profile tests passed |
| API compatibility | Five routes, six offers and all six offer details matched, allowing only removal of the unsupported Standard exchange note |
| Baseline purchase | One-seat Standard and two-seat Business orders confirmed with reservations, notifications and independently checked Stripe sandbox charges |
| PostgreSQL purchase/refund | Both purchase shapes confirmed; changed client price rejected; Standard refund refused; Business fully refunded with seats returned and Stripe refund verified |
| Pod replacement | A temporary stored note survived replacement of an active Catalog pod; two successful migrations remained recorded; note restored afterward |
| Catalog database outage | New checkout returned `503 OFFER_UNRESOLVABLE` in 0.45 s; order, reservation and authorization counts remained unchanged; provider charge enumeration showed no new charge |
| Health during outage | Both active Catalog pods returned healthy liveness and HTTP 503 readiness |
| Historical orders during outage | Pre-migration orders remained readable, Standard refund was refused and the pre-migration Business purchase was fully refunded through Stripe |
| Recovery | Database connections restored; Catalog reads recovered; final purchase and refund checks passed after rollback/restoration |
| Rollback | Original image/template passed preview analysis, served public requests and completed new sandbox purchases and a Business refund |
| Final state | Rollout healthy with two ready Catalog replicas on distinct workers, both using the PostgreSQL image and reporting zero restarts |

Provider evidence retains charge hashes, sandbox flags, charged amounts and refunded amounts. Credentials and raw provider references are absent. Database counts in the isolated fault window were 184 orders, 184 reservations and 184 authorization rows both before and after the refused checkout; the historical refund was tested afterward.

## Scheduling and controller behavior

Legacy required anti-affinity selected every `app=catalog` pod. Two active and two preview replicas therefore could not coexist on three workers. The first promotion temporarily used one active replica. Catalog's progressive template now scopes anti-affinity to `rollouts-pod-template-hash`, preserving separation within one revision while allowing different revisions to share workers. Kubernetes v1.34 accepted and ran this configuration.

Three analysis runs succeeded: the initial PostgreSQL preview, the revision with corrected scheduling, and the legacy rollback preview. Returning to PostgreSQL restored the exact previously verified stable pod hash `79dc679f8c`; Argo fast-tracked that restoration and did not create a new analysis run. A subsequent full purchase/refund check passed. Two replicas were restored before the final-state audit.

The final local image is `eurotransit/catalog:pg-20261019-2036`; its manifest digest is `sha256:cb2a8b7556bc2fdda6122bb370cf948223393018a5a8084c10bf8fa1ebfea42c`. Both running containers report image configuration ID `sha256:eb769725a9559bb103a68200e667a75fffe01104d645ecc889fb33d15f4d0780`. Evidence records the application base and Catalog source hash because the trial image includes the coordinated working-tree implementation.

## Limits and follow-up

This was a functional migration and recovery trial with a temporary reduction in redundancy, not a zero-downtime or SLO qualification. All Kind workers share the workstation. Database primary failover and Azure infrastructure behavior were not exercised in this scenario.

Only Catalog's Deployment template was patched for the trial. An audit confirmed all other Deployment specifications and the Orders Rollout specification were unchanged. Helm's stored values remain unchanged; a future Helm upgrade must explicitly preserve the PostgreSQL selection and tested image. The application and chart defaults remain in-memory for environments awaiting database provisioning.

Offer-management APIs, Catalog revision history and separate read-only runtime credentials are outside this change. Returning to static offers is safe for the unchanged seed used here; it must be reassessed once live commercial data can diverge.

## Declarative provisioning and startup gate

The configuration follow-up adds a retained CNPG Database resource, the dedicated AKS managed role/ciphertext, and an authenticated database init container. These AKS resources were prepared locally and were not applied to AKS. The [delivery runbook](../../operations/catalog-postgres-aks.md) requires human review of both repository PRs and a separate delivery approval.

The Kind provisioning check used isolated temporary databases to verify that a missing database blocks startup, CNPG creation unblocks it, PUBLIC connection access is revoked, timeout is bounded, and an unexpected owner is rejected without ownership changes. It then adopted the existing `catalog_db` with the exact production Database manifest and verified that all six offers, five routes and two migrations remained intact. Temporary fixtures were reclaimed; the real database uses `retain`.

The final Catalog topology also uses `nodeTaintsPolicy: Honor`. The previous spread constraint counted the tainted control-plane node as an empty domain, preventing the fourth pod of a two-replica blue/green transition from scheduling. Excluding that ineligible domain allowed both old and new pairs to coexist on the three workers. Intermediate in-flight revisions were superseded during this correction; the final verification starts from a healthy revision and runs a fresh analysis before promotion.

The original database-outage and rollback observations above belong to the initial application trial. The follow-up specifically qualifies declarative adoption, startup gating and the corrected scheduling path; it does not extend the earlier results into an AKS deployment claim.

The [follow-up evidence](../evidence/2026-10-19/catalog-postgres-gitops-kind.json) records six successful provisioning cases and final revision `7787d7d74f`. A local verification annotation created a fresh revision after the scheduling correction. Analysis `catalog-7787d7d74f-13-pre` succeeded with 422 preview requests; all routes, offers and details matched. After promotion, Standard and two-seat Business purchases confirmed with independently verified sandbox charges. Standard refund returned `409 OFFER_NOT_REFUNDABLE`; Business refunded all 9980 cents, and client price tampering was rejected. Both active pods used the PostgreSQL image.

On October 20, a workstation restart restored the lower host inotify limits and broke kube-proxy again. Restoring the documented limits and recreating the two interrupted Catalog pods recovered both replicas on distinct workers; both database gates exited successfully. This recovery observation is separate from the previous day's completed purchase/refund trial.
