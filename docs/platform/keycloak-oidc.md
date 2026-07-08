# Keycloak OIDC

Keycloak is the EuroTransit Marketplace OIDC provider for cluster and proof environments. Local fixed JWTs or mock issuers are development substitutes only; they are not the final cluster proof.

## Environment Values

The Keycloak Helm values live in `platform/keycloak/`:

| Environment | Value Files | Hostname | Database Mode |
| --- | --- | --- | --- |
| kind/local | `values.yaml`, `values-kind.yaml` | `keycloak.eurotransit.local` | embedded chart PostgreSQL |
| proof/demo | `values.yaml`, `values-proof.yaml` | `keycloak.gXX.cpo2026.it` | external PostgreSQL secret reference |
| production-style | `values.yaml`, `values-production.yaml` | `keycloak.eurotransit.example.com` | external PostgreSQL secret reference |

Argo CD currently uses the kind overlay for both Keycloak and the EuroTransit application chart. To target proof or production, change the second Keycloak value file and the second `charts/eurotransit` value file in `platform/argocd/platform-applications.yaml`, then update the hostnames, TLS issuer, and sealed database credentials first.

## Realm Contract

The shared values import a realm named `eurotransit` with:

- public frontend client: `eurotransit-frontend`;
- API audience client: `eurotransit-api`;
- realm roles: `customer`, `operations`, `admin`;
- client scopes: `eurotransit-customer`, `eurotransit-operations`.

Runtime URLs for kind:

- issuer: `https://keycloak.eurotransit.local/realms/eurotransit`;
- JWKS: `http://keycloak.keycloak.svc.cluster.local/realms/eurotransit/protocol/openid-connect/certs`.

The EuroTransit application chart passes these through:

- `SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_ISSUER_URI`;
- `SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_JWK_SET_URI`;
- `EUROTRANSIT_SECURITY_OIDC_AUDIENCE`.

Application environment overlays live beside the chart:

| Environment | Value Files | EuroTransit Hostname | Keycloak Issuer |
| --- | --- | --- | --- |
| kind/local | `values.yaml`, `values-kind.yaml` | `eurotransit.local` | `https://keycloak.eurotransit.local/realms/eurotransit` |
| proof/demo | `values.yaml`, `values-proof.yaml` | `eurotransit.gXX.cpo2026.it` | `https://keycloak.gXX.cpo2026.it/realms/eurotransit` |
| production-style | `values.yaml`, `values-production.yaml` | `eurotransit.example.com` | `https://keycloak.eurotransit.example.com/realms/eurotransit` |

## Secrets

Required sealed secrets:

- `keycloak-admin-credentials` in namespace `keycloak`;
- `keycloak-postgresql-credentials` in namespace `keycloak` for kind/local embedded PostgreSQL;
- `keycloak-external-db-credentials` in namespace `keycloak` for proof/production external PostgreSQL;
- `keycloak-client-settings` in namespace `eurotransit` for application-side client metadata when needed.

Templates live in:

- `platform/keycloak/templates/`;
- `platform/sealed-secrets/templates/`.

No Keycloak admin passwords, database passwords, client secrets, or test-user passwords should be committed as plaintext.

## Verification

After sync:

```bash
kubectl -n keycloak get pods,svc,ingress
kubectl -n keycloak logs statefulset/keycloak --tail=100
curl -k https://keycloak.eurotransit.local/realms/eurotransit/.well-known/openid-configuration
curl -k https://keycloak.eurotransit.local/realms/eurotransit/protocol/openid-connect/certs
```

The well-known issuer must match the issuer configured in the application chart for that environment.

