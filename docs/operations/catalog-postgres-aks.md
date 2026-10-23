# Catalog PostgreSQL delivery on AKS

The production profile declares PostgreSQL Catalog storage and provisions its dedicated database through CloudNativePG. Merge is an AKS deployment action because Argo CD automatically reconciles `main`. This change must remain unmerged until both repository PRs have passed human review and AKS delivery is explicitly approved. The implementation and failure contract are defined in the [application reference](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/catalog-storage.md).

## Release prerequisites

1. Review [application PR #167](https://github.com/g05-eurotransit/EuroTransit-application/pull/167) and the companion configuration PR together. Prepare and review their changes before starting AKS delivery.
2. After approval, integrate the application change and wait for its CI image publication and automated configuration image-tag update. Refresh this branch so it preserves the published tag. Do not merge the activation with the older Catalog image: it does not implement PostgreSQL storage selection.
3. Require successful AKS rendering, sealed-secret inventory checks and the Catalog configuration tests. The new ciphertext must belong to the target AKS Sealed Secrets controller and use the exact `eurotransit/catalog-db-credentials` identity. Before approval, inspect any existing `catalog_db`: it must be absent or already owned by `catalog` with the intended data. CNPG reconciles the declared owner; this migration must not take over an unrelated database with the same name.
4. Schedule and approve AKS delivery separately. Kind proof establishes local behavior; no AKS deployment, purchase test or availability claim is included in that proof.

## Resources and startup order

The existing Argo root synchronizes runtime Secrets before the platform and marketplace applications. The platform overlay appends the non-administrative `catalog` managed role without replacing other roles. Its `Database` resource creates or reconciles `catalog_db` on the existing CNPG cluster, with `catalog` ownership and `databaseReclaimPolicy: retain`. It does not depend on first-cluster bootstrap SQL.

Sync waves alone do not establish database usability. In PostgreSQL mode, the Catalog Deployment includes `catalog-database-ready`, an init container that authenticates using only the Catalog Secret, verifies the database owner and revokes PUBLIC connection permission. It retries within a 180-second budget with bounded connection and statement timeouts; a final in-flight attempt can extend the budget by its bounded timeout. Failed provisioning prevents application startup and is visible in init-container status without exposing credentials.

The gate requires no service-account token or Kubernetes permissions. It runs as a non-root user with a read-only filesystem and dropped capabilities, requesting 10m CPU and 16Mi memory with 100m/64Mi limits. Its database credential is the same owner credential used by Catalog migrations; no administrative PostgreSQL credential is mounted.

When the gate succeeds, the application runs its Flyway migrations. Existing identifiers, prices, zones and refund policies are seeded once. The rolling strategy retains `maxUnavailable: 0`, so an unready replacement does not deliberately remove the previous pod. The constrained cluster still needs capacity for the surge pod; this is not an availability or headroom qualification.

## Catalog-only ciphertext preparation

The PR includes the new ciphertext. To prepare it on another branch or workstation when it is absent:

```bash
python3 scripts/generate-catalog-sealed-secret.py --context eurotransit
scripts/validate-aks-sealed-secrets.sh platform/environments/aks/secrets
scripts/render.sh aks
```

The generator performs only cluster reads: it obtains any existing Catalog credential and the public sealing certificate. It writes one local ciphertext file and never applies it. Existing credentials are preserved; an existing output file is not overwritten. An optional `--cert` supplies an already retrieved public certificate. Plaintext travels only through process memory and stdin.

Use this targeted generator for the Catalog addition. The older full-inventory generator now supports fourteen Secrets, but executing it rotates the other credentials too and is not part of this migration. Existing key backup and recovery responsibilities remain those of the [secret lifecycle](../platform/security-and-secrets.md).

## Approved delivery verification

After the separate approval and merge, observe Argo reconciliation, the Catalog role and Database resource, the new pod's init-container completion and application readiness. Confirm the active image/tag and storage selection, then run a bounded customer purchase/refund test with provider-side evidence under the approved AKS test procedure. Until these observations exist, label the AKS path as configured, not verified.

No routine manual SQL or administrative provisioning Job is required. Controller, Secret or migration failures require diagnosis; neither application nor infrastructure silently falls back to static offers.

## Rollback

Revert only production `catalog.storage` to `in-memory` and restore the previously approved application image through a reviewed configuration change. Database settings and the init container disappear from the application pod; preserve the Database resource, credentials and stored Catalog data. The `retain` policy also protects database contents if the resource is pruned, but ordinary rollback should leave it declared.

Once commercial data diverges from the original seed, switching to static offers can restore obsolete terms and is no longer a safe default rollback. Use application recovery against the retained database instead. Never replace the PostgreSQL cluster or delete PVCs as a Catalog rollback.
