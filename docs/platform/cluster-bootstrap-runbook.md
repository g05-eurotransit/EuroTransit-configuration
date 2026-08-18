# EuroTransit Cluster Bootstrap

EuroTransit has two supported Kubernetes paths:

For AKS, Sealed Secrets is cluster-admin-owned and application ciphertext is
the Argo `eurotransit-secrets` wave-5 prerequisite. `just render-aks` fails
until current-cluster ciphertext is generated; see the linked AKS runbook.

- [AKS production setup](aks-production-setup.md) for the fixed three-node
  `Standard_B2als_v2` cluster and `g05.cpo2026.it`.
- [local Kind setup](kind-local-setup.md) for repeatable workstation validation.

## Shared Deployment Model

The application is packaged by `charts/eurotransit`. Stateful runtime objects
are composed by `platform/environments/<environment>`. Platform controllers
are installed with pinned upstream Helm charts.

AKS is reconciled by the `eurotransit-platform-root` Argo CD Application after
the private configuration-repository credential is bootstrapped. Kind installs
the same controller families directly to keep the developer loop short;
`just render-kind` also validates the declarative runtime overlay. The separate
Argo-on-Kind acceptance procedure is documented in `argocd-bootstrap.md`.

For AKS, the cluster admin installs and upgrades the Sealed Secrets controller
outside Argo CD, then Argo applies application SealedSecrets in wave `5` and
waits for them to become `Synced=True`. The complete root order is wave `5`
application secrets, wave `10` platform operators (Traefik, cert-manager,
Strimzi, CloudNativePG and monitoring), wave `15` Keycloak Operator, wave `20`
runtime and TLS, wave `25` Keycloak and the Orders client bootstrap Job, wave
`30` marketplace workloads and Flyway migrations, and wave `40` the dedicated
Debezium connector overlay. Kind reproduces the runtime portion with explicit
waits and a Helm `--wait` followed by waits on the Strimzi custom resources.

## Validation Commands

```bash
just render-kind
just render-aks # only after AKS ciphertext generation; otherwise use scaffold validation
```

`ALLOW_MISSING_AKS_SECRETS=1 just render-aks` validates only the AKS scaffold;
it does not make an AKS release renderable. Both `just render-kind` and the
normal `just render-aks` must pass before merging the final configuration
revision that contains the generated ciphertext. The Kind acceptance workflow
is:

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
