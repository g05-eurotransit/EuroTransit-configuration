# GitOps Topology

A push to application `main` triggers conditional image builds and publication to ACR. CI commits the image references to configuration Git; Argo CD reads that desired state, renders Helm/Kustomize sources and reconciles AKS. CI needs registry/repository credentials and no cluster credentials. The [release evidence gap](../readiness.md) remains distinct from this configured path.

[![GitOps delivery from application push through CI, configuration Git and the Argo CD Application hierarchy to Helm and Kustomize sources](../diagrams/delivery/gitops.svg)](https://g05-eurotransit.github.io/EuroTransit-configuration/delivery/gitops.html)

[Full-size SVG](../diagrams/delivery/gitops.svg) · [Open interactive diagram](https://g05-eurotransit.github.io/EuroTransit-configuration/delivery/gitops.html)

The viewer has two views: the delivery flow and the Application inventory. The inventory names all 13 child Applications, their sync waves, the Helm chart or Kustomize source and the resources each installs. Operators and the database or identity instances they manage have separate entries.

[![AKS Application inventory with Helm chart names, Kustomize sources and installed resources](../diagrams/delivery/gitops-applications.svg)](https://g05-eurotransit.github.io/EuroTransit-configuration/delivery/gitops.html#applications)

[Full-size inventory SVG](../diagrams/delivery/gitops-applications.svg) · [Open interactive inventory](https://g05-eurotransit.github.io/EuroTransit-configuration/delivery/gitops.html#applications)

The children are siblings under one root, and wave numbers define their synchronization order. Helm and Kustomize run within Argo CD; Kubernetes controllers create workloads and pull the declared images.

**Owner:** Technical Coordinator + Gateway/Security Slice Owner.

## Responsibilities

- Application CI builds immutable images.
- The configuration repository stores Kubernetes desired state.
- ArgoCD reconciles the target cluster from this repository.
- CI must not hold direct cluster credentials.
- The Technical Coordinator + Gateway/Security Slice Owner owns the GitHub Actions workflows, image build/publish automation, configuration-repository update automation, and delivery rollback procedure.

## Required Inputs from Service Owners

- Service build and test commands remain valid.
- The application repository maintains one parameterized Dockerfile for all
  backend services; service-specific builds select the target with the
  `SERVICE` build argument.
- The application repository also maintains `connect/Dockerfile`. CI publishes
  the Strimzi-compatible Debezium image to ACR and the AKS connector overlay
  pins the resulting digest.
- Runtime environment variables are documented.
- Health/readiness behavior is implemented and stable.

## Application Order

- `eurotransit-platform-root` reconciles the selected
  `platform/argocd/environments/<environment>` overlay and is the parent of
  every platform and workload Application. It is the only Application applied
  imperatively after Argo CD and its private-repository credential exist.
- Application secrets reconcile at wave `5`; platform operators generally install at wave `10`. Monitoring configuration and `keycloak-operator` follow at wave `15`. Argo Rollouts installs at wave `29`, before marketplace Rollout resources.
- `eurotransit-platform-runtime` installs PostgreSQL, Kafka and topics at wave
  `20`.
- `eurotransit-keycloak` creates the identity runtime at wave `25`.
- `eurotransit-marketplace` starts the services and runs Flyway at wave `30`.
- `eurotransit-connectors` starts Debezium at wave `40`.

The parent Application treats child Applications and the Strimzi
`KafkaConnect`/`KafkaConnector` resources as healthy only when their reported
health is ready. A connector failure is therefore visible in GitOps instead of
being hidden by a healthy Kafka Connect HTTP process.

Applying an Argo environment overlay directly creates independent auto-sync
Applications and does not enforce ordering between them. The normal AKS
bootstrap must apply `apps/argocd-apps/environments/aks` instead.

## Image update boundary

The application [image workflow](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/.github/workflows/docker-gitops.yml) builds from the resolved source revision, publishes SHA-tagged images and updates `charts/eurotransit/values.yaml` using the scoped configuration-repository credential. Its current implementation commits and pushes the values change directly. The connector image has its own [digest update workflow](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/.github/workflows/connect-gitops.yml). Review branch protection and credential scope before claiming that every generated change passed human merge review.

The diagram describes the AKS app-of-apps. Standard Kind removes some monitoring applications; isolated Kind HA uses a direct setup procedure. Rollouts owns active selectors/Traefik weights while Argo ignores those controller-managed fields. Rollback steps and gates belong to [progressive delivery](../operations/progressive-delivery.md).
