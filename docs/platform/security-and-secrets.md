# Security and Secrets

This document owns configuration-side security controls. Application-side authentication and authorization behavior is documented in the application repository.

On AKS the Sealed Secrets controller/key lifecycle is cluster-admin-owned.
Only application ciphertext under `platform/environments/aks/secrets` is
Argo-managed (wave 5); the Argo repository credential is versioned as ciphertext
under `platform/argocd/bootstrap/aks`, applied manually, and outside that path.
Ciphertext is cluster/key specific; Orders client
credentials are duplicated in `eurotransit` and `keycloak` for the Argo Job.

## Required Controls

- No plaintext production secrets committed to the repository.
- Environment-specific values are externalized through Kubernetes-native mechanisms or the chosen secret management approach.
- CI must not hold broad cluster credentials.
- Public ingress must enforce the configured authentication boundary.
- Target clusters use Keycloak as the OIDC identity provider. Mock OIDC issuers and fixed JWTs are local-development substitutes only.
- Internal services must not be publicly routable.
- Final cluster/demo proof must not depend on mocked services or fake in-memory substitutes for core infrastructure.
- Payments must use sandbox/test provider credentials, such as Stripe test mode or PayPal Sandbox, stored through the chosen Kubernetes secret mechanism.
- Payment provider sandbox secrets, Keycloak client settings, database credentials, Kafka credentials, and signing material must never be committed as plaintext.
- `Idempotency-Key` must never be treated as an authorization credential. It is only a retry identifier; protected APIs still require JWT or service identity controls.
- Orders, Inventory, and Payments use separate logical PostgreSQL databases with separate credentials: `orders_db`, `inventory_db`, and `payments_db`.

## Keycloak Configuration

Cluster Keycloak configuration must define:

- realm name;
- public frontend client;
- Orders/API client or audience;
- customer role/scope;
- operations/admin role/scope;
- issuer URL;
- JWKS discovery URL;
- redirect origins for the frontend.

Fixed JWTs and mock OIDC issuers are local-development substitutes only and must not be the final cluster/demo proof.

## Database And Secret Boundaries

Configuration must provision:

- `orders_db` credentials exposed only to Orders;
- `inventory_db` credentials exposed only to Inventory;
- `payments_db` credentials exposed only to Payments;
- payment provider sandbox credentials exposed only to Payments;
- Kafka credentials only where the selected Kafka setup requires them.

One PostgreSQL cluster may host the three logical databases in local environments, but service users must not receive cross-database read/write access.

## Current Manifests

- The cluster admin installs and upgrades the controller with the reviewed
  values in `platform/sealed-secrets/values.yaml`; it is not an Argo CD
  Application and its key backup/restore is an admin responsibility.
- The eleven AKS application ciphertexts live in
  `platform/environments/aks/secrets/` and are owned by the Argo
  `eurotransit-secrets` Application at wave 5, with pruning and self-heal.
- `scripts/generate-aks-sealed-secrets.sh` creates those ciphertexts for the
  target controller without writing plaintext files;
  `scripts/validate-aks-sealed-secrets.sh` verifies their required inventory.
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
  workflow is documented in `docs/platform/aks-production-setup.md` and
  summarized in `docs/platform/cluster-bootstrap-runbook.md`.

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
