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

## To Document

- local development secrets;
- CI secrets;
- Keycloak realm, clients, roles/scopes, issuer URL, and JWKS configuration;
- payment provider sandbox secret names and rotation expectations;
- Kubernetes Secret or external secret strategy;
- rotation expectations;
- review requirements for auth, routing, and secret changes.
