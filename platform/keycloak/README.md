# Keycloak Platform Configuration

EuroTransit uses the official Keycloak Operator `26.7.0`, installed by the
`keycloak-operator` Argo CD Application. The instance and realm are managed by
the `eurotransit-keycloak` Argo CD Application from this directory.

- `keycloak.yaml`: one Keycloak instance using the dedicated `keycloak_db` in
  CloudNativePG.
- `eurotransit-realm.yaml`: realm, roles, clients and scopes.
- `frontend-identity-claims-reconcile-job.yaml`: Argo CD PostSync Job that
  keeps the frontend identity mappers present in an already imported realm.
- `ingressroute.yaml`: low-priority Traefik fallback route for Keycloak.

The production hostname is `g05.cpo2026.it`. The Kind overlay is under
`platform/environments/keycloak-kind` and uses
`keycloak.eurotransit.local`.

Required secrets in namespace `keycloak` are:

- `keycloak-admin-credentials` with `username` and `password` keys;
- `keycloak-db-credentials` with `username` and `password` keys.

CloudNativePG also requires `keycloak-db-credentials` with the same keys in
namespace `eurotransit`, where it manages the database role.

For AKS commit only the corresponding SealedSecrets encrypted for the target
controller. The Kind script creates fixed development-only values at runtime.
