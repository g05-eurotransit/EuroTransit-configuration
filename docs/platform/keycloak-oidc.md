# Keycloak OIDC

Keycloak is operated by the official Keycloak Operator `26.7.0`. Argo CD first
installs the operator, then syncs the EuroTransit Keycloak instance and realm
from `platform/keycloak`.

The Keycloak instance uses the dedicated `keycloak_db` database and
`keycloak` role managed by CloudNativePG. It does not run an embedded chart
database.

| Environment | Public hostname | Issuer |
| --- | --- | --- |
| Kind | `keycloak.eurotransit.local` | `https://keycloak.eurotransit.local/realms/eurotransit` |
| AKS | `g05.cpo2026.it` | `https://g05.cpo2026.it/realms/eurotransit` |

The realm import defines `eurotransit-frontend`, `eurotransit-api`, roles
`customer`, `operations`, `admin`, and the customer and operations scopes.
The frontend client explicitly maps `preferred_username` and `email` into its
ID token and UserInfo response. Those two mappers match the Docker Compose realm
in the application repository. The frontend requests `openid` and uses those
claims for the signed-in name and avatar.

`KeycloakRealmImport` creates a realm only once. The Argo CD PostSync Job
`frontend-identity-claims-reconcile` applies the same two mappers idempotently
to an existing realm on each Keycloak application sync. For a cluster not yet
synced to this revision, apply the Job once and wait for completion:

```bash
kubectl apply -f platform/keycloak/frontend-identity-claims-reconcile-job.yaml
kubectl -n keycloak wait --for=condition=complete \
  job/frontend-identity-claims-reconcile --timeout=10m
```

After applying the change, sign out and sign in again to obtain a fresh ID
token. Confirm that it includes `preferred_username` and `email`.

Required `keycloak` namespace secrets are `keycloak-admin-credentials` and
`keycloak-db-credentials`, each with `username` and `password` keys. For AKS
they must be SealedSecrets; CloudNativePG also needs
`keycloak-db-credentials` in namespace `eurotransit`.
`orders-service-credentials` is required in both `keycloak` and
`eurotransit`, with the identical rotated `client-secret` value. The
`keycloak` copy is consumed by the Argo-managed wave-25 client-bootstrap Job;
the `eurotransit` copy is consumed by Orders. Kind remains a development demo
and creates all of these values in-cluster.

The load runner requires `eurotransit-load-test-credentials` with matching `client-secret` values in `keycloak` and `eurotransit`. The ordinary `load-test-client-secret-bootstrap` Job reconciles the confidential service-account client and customer role without interactive/password grants. Follow [identity recovery](../operations/identity-recovery.md) when a changed Pod template needs a new Job instance.

## Demo accounts

The following accounts are provisioned by `keycloak-demo-users-bootstrap` for
development and acceptance testing. The AKS values are stored in the
`keycloak-demo-users-credentials` SealedSecret.

| Username | Password | Realm role |
| --- | --- | --- |
| `alice` | `Alice!Metro#2026` | `customer` |
| `bruno` | `Bruno!Route#2026` | `customer` |
| `chiara` | `Chiara!Ticket#2026` | `operations` |

These are intentionally known demo credentials. Replace or remove them before
any real-user or internet-facing production use.

Verify the operator and instance:

```bash
kubectl -n keycloak get deployment/keycloak-operator
kubectl -n keycloak get keycloak,keycloakrealmimport
curl -k https://g05.cpo2026.it/realms/eurotransit/.well-known/openid-configuration
```

The returned issuer must equal the value configured in the EuroTransit Helm
overlay for the selected environment.
