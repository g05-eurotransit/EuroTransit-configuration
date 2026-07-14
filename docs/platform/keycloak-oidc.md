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
`keycloak-db-credentials` in namespace `eurotransit`. Kind creates all of
these development values in-cluster.

Verify the operator and instance:

```bash
kubectl -n keycloak get deployment/keycloak-operator
kubectl -n keycloak get keycloak,keycloakrealmimport
curl -k https://g05.cpo2026.it/realms/eurotransit/.well-known/openid-configuration
```

The returned issuer must equal the value configured in the EuroTransit Helm
overlay for the selected environment.
