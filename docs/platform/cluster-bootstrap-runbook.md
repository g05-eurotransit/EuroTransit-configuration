# EuroTransit Cluster Bootstrap

EuroTransit has two supported Kubernetes paths:

- [AKS production setup](aks-production-setup.md) for the fixed three-node
  `Standard_B2als_v2` cluster and `g05.cpo2026.it`.
- [local Kind setup](kind-local-setup.md) for repeatable workstation validation.

## Shared Deployment Model

The application is packaged by `charts/eurotransit`. Stateful runtime objects
are composed by `platform/environments/<environment>`. Platform controllers
are installed with pinned upstream Helm charts.

AKS is reconciled by Argo CD. Kind installs the same controller families
directly to keep the developer loop short; `just render-kind` also validates
the declarative runtime overlay.

The deployment order is PostgreSQL and Kafka, then the marketplace workloads
and Flyway migrations, then the dedicated Debezium connector overlay. Argo CD
uses sync waves `20`, `30`, and `40`; Kind reproduces the sequence with a Helm
`--wait` followed by waits on the Strimzi custom resources.

## Validation Commands

```bash
just render-kind
just render-aks
```

Both commands must pass before configuration changes are merged. The Kind
acceptance workflow is:

```bash
just kind-up
just kind-test
just kind-down
```

## Ownership Boundary

This repository owns Kubernetes, GitOps, ingress, secrets, observability and
operational proof. API contracts, authentication semantics and service
implementation remain canonical in `../EuroTransit-application/docs`.

Production credentials are committed only as SealedSecrets. Local Kind
credentials are generated in-cluster by the setup script and are deliberately
non-production values.
