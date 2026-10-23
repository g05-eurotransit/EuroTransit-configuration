# Security and Secrets

This document owns configuration-side security controls. Application-side authentication and authorization behavior is documented in the application repository.

On AKS the Sealed Secrets controller/key lifecycle is cluster-admin-owned.
Only application ciphertext under `platform/environments/aks/secrets` is
Argo-managed (wave 5); the Argo repository credential is versioned as ciphertext
under `platform/argocd/bootstrap/aks`, applied manually, and outside that path.
Ciphertext is cluster/key specific; Orders client
credentials are duplicated in `eurotransit` and `keycloak` for the Argo Job.

## Secret boundaries

Never commit plaintext credentials or controller private keys. Orders, Inventory and Payments receive their own logical database credentials; provider sandbox credentials belong only to Payments. Keycloak client secrets and bootstrap credentials are namespace-scoped. Application identities, roles and resource ownership are defined by the [API contract](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/api-design.md); cluster issuer/client provisioning is in [OIDC setup](keycloak-oidc.md).

## Current Manifests

- The cluster admin installs and upgrades the controller with the reviewed
  values in `platform/sealed-secrets/values.yaml`; it is not an Argo CD
  Application and its key backup/restore is an admin responsibility.
- The fourteen AKS runtime ciphertexts live in
  `platform/environments/aks/secrets/` and are owned by the Argo
  `eurotransit-secrets` Application at wave 5, with pruning and self-heal.
- `scripts/generate-aks-sealed-secrets.sh` creates those ciphertexts for the
  target controller without writing plaintext files;
  `scripts/validate-aks-sealed-secrets.sh` verifies their required inventory.
- For an existing cluster, the Catalog-only generator and [delivery procedure](../operations/catalog-postgres-aks.md)
  add its ciphertext without rotating any other credential. Generation writes
  local ciphertext and performs only cluster reads; applying it requires the
  separately approved GitOps delivery.
- The sole manual SealedSecret is the private Argo repository credential in
  `argocd`: it is generated and applied by the cluster admin before Argo can
  read the repository. Only its ciphertext is committed under
  `platform/argocd/bootstrap/aks`; it is outside the wave-5 app and every Argo
  kustomization. No decrypted Secret or controller private key belongs in Git.
- Database and payment credential templates live in
  `platform/cloudnativepg/templates/` and `platform/sealed-secrets/templates/`.
- Keycloak admin, database and Orders client-secret templates live in
  `platform/keycloak/templates/`; the Orders value is sealed identically for
  both `keycloak` and `eurotransit`.
- The Keycloak demo-user passwords are sealed only in the `keycloak` namespace
  and are consumed by an idempotent bootstrap Job.
- Keycloak multi-environment OIDC configuration lives in `platform/keycloak/` and is documented in `docs/platform/keycloak-oidc.md`.
- CloudNativePG database and role references live in `platform/cloudnativepg/postgres-cluster.yaml`.
- The executable sealing, bootstrap, upgrade, rotation and disaster-recovery
  workflow is documented in `docs/operations/aks.md` and
  summarized in `docs/operations/aks.md`.

## Rotation And Recovery

- Rotate application secrets by generating and reviewing replacement AKS
  ciphertext, merging it through protected `main`, and allowing Argo to sync
  wave 5. Rotate the Orders value in both namespaces and recreate the
  `orders-service-client-secret-bootstrap` Job as documented in the runbook.
- Rotate the repository credential with a manual cluster-admin apply before
  Argo needs it, then review and commit the replacement ciphertext. Argo never
  applies this bootstrap credential from Git. A new PC can reuse ciphertext on
  the same cluster; a new cluster needs the original controller keys restored
  or newly sealed credentials. An expired/revoked token needs replacement
  regardless of whether its ciphertext and controller keys remain available.
- Before every controller upgrade, inventory and back up its key Secrets using
  the approved encrypted off-cluster process. Recovery restores the original
  keys before reconciling ciphertext, then performs a tested DR validation.
