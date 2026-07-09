# Keycloak Platform Configuration

Keycloak is the EuroTransit Marketplace OIDC identity provider for cluster environments.

The chart values are split by responsibility:

- `values.yaml`: shared realm, clients, metrics, probes, and secret references.
- `values-kind.yaml`: local kind hostnames and lightweight resources.
- `values-production.yaml`: production-style hostnames, replicas, and external database references.

Argo CD currently uses `values.yaml` plus `values-kind.yaml` so the local path is runnable. For production-style deployment, change the second Keycloak value file and the second `charts/eurotransit` value file in `platform/argocd/platform-applications.yaml` after the target hostnames, TLS issuer, and sealed database credentials are ready.

No admin passwords, database passwords, client secrets, or test-user passwords belong in these values files.
