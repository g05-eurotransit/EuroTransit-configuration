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

Required `keycloak` namespace secrets are `keycloak-admin-credentials` and
`keycloak-db-credentials`, each with `username` and `password` keys. For AKS
they must be SealedSecrets; CloudNativePG also needs
`keycloak-db-credentials` in namespace `eurotransit`.
`orders-service-credentials` is required in both `keycloak` and
`eurotransit`, with the identical rotated `client-secret` value. The
`keycloak` copy is consumed by the Argo-managed wave-25 client-bootstrap Job;
the `eurotransit` copy is consumed by Orders. Kind remains a development demo
and creates all of these values in-cluster.

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
