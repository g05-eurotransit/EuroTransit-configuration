# Security and Secrets

This document owns configuration-side security controls. Application-side authentication and authorization behavior is documented in the application repository.

## Required Controls

- No plaintext production secrets committed to the repository.
- Environment-specific values are externalized through Kubernetes-native mechanisms or the chosen secret management approach.
- CI must not hold broad cluster credentials.
- Public ingress must enforce the configured authentication boundary.
- The cluster/proof target uses Keycloak as the OIDC identity provider. Mock OIDC issuers and fixed JWTs are local-development substitutes only.
- Internal services must not be publicly routable.
- Final cluster/demo proof must not depend on mocked services or fake in-memory substitutes for core infrastructure.
- Payments must use sandbox/test provider credentials, such as Stripe test mode or PayPal Sandbox, stored through the chosen Kubernetes secret mechanism.
- Payment provider sandbox secrets, Keycloak client settings, database credentials, Kafka credentials, and signing material must never be committed as plaintext.
- `Idempotency-Key` must never be treated as an authorization credential. It is only a retry identifier; protected APIs still require JWT or service identity controls.
- Orders, Inventory, and Payments use separate logical PostgreSQL databases with separate credentials: `orders_db`, `inventory_db`, and `payments_db`.

## Keycloak Configuration

The cluster/proof Keycloak configuration must define:

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

One PostgreSQL cluster may host the three logical databases in local/proof environments, but service users must not receive cross-database read/write access.

## To Document

- local development secrets;
- CI secrets;
- Keycloak realm, clients, roles/scopes, issuer URL, and JWKS configuration;
- payment provider sandbox secret names and rotation expectations;
- Kubernetes Secret or external secret strategy;
- rotation expectations;
- review requirements for auth, routing, and secret changes.
