# Security and Secrets

This document owns configuration-side security controls. Application-side authentication and authorization behavior is documented in the application repository.

## Required Controls

- No plaintext production secrets committed to the repository.
- Environment-specific values are externalized through Kubernetes-native mechanisms or the chosen secret management approach.
- CI must not hold broad cluster credentials.
- Public ingress must enforce the configured authentication boundary.
- Internal services must not be publicly routable.

## To Document

- local development secrets;
- CI secrets;
- Kubernetes Secret or external secret strategy;
- rotation expectations;
- review requirements for auth, routing, and secret changes.
