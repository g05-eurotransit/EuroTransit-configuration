# Keycloak Platform Configuration

EuroTransit uses the official Keycloak Operator `26.7.0`, installed by the
`keycloak-operator` Argo CD Application. The instance and realm are managed by
the `eurotransit-keycloak` Argo CD Application from this directory.

- `keycloak.yaml`: one Keycloak instance using the dedicated `keycloak_db` in
  CloudNativePG.
- `eurotransit-realm.yaml`: realm, roles, clients and scopes.
- `frontend-identity-claims-reconcile-job.yaml`: Argo CD PostSync Job that
  keeps the frontend identity mappers present in an already imported realm.
- `load-test-client-secret-bootstrap-job.yaml`: ordinary Job that creates or
  updates the confidential load-test client, reconciles its realm roles mapper
  and grants `customer` to its service account using the existing client secret.
- `ingressroute.yaml`: low-priority Traefik fallback route for Keycloak.

The production hostname is `g05.cpo2026.it`. The Kind overlay is under
`platform/environments/keycloak-kind` and uses
`keycloak.eurotransit.local`.

Required secrets in namespace `keycloak` are:

- `keycloak-admin-credentials` with `username` and `password` keys;
- `keycloak-db-credentials` with `username` and `password` keys;
- `eurotransit-load-test-credentials` with the `client-secret` key, matching
  the Secret with the same name in namespace `eurotransit`.

CloudNativePG also requires `keycloak-db-credentials` with the same keys in
namespace `eurotransit`, where it manages the database role.

For AKS commit only the corresponding SealedSecrets encrypted for the target
controller. The Kind script creates fixed development-only values at runtime.

Realm imports do not update an existing realm. The load-test bootstrap waits
for admin authentication and the realm, then reconciles the client in place;
repeated runs preserve the client and mapper IDs. Its full role scope matches
the realm import default, allowing the service account's `customer` role to
appear in `realm_access.roles`. Interactive and password grants are disabled.

An ordinary Job's Pod template is immutable and completed Jobs do not rerun.
After a template change is merged and Argo has refreshed the desired revision,
delete only `load-test-client-secret-bootstrap` and let Argo recreate it.
Follow the [AKS recovery procedure](../../docs/platform/aks-keycloak-cert-manager-recovery.md)
for the sync order and token-only verification.
