# GitOps Topology

This document owns the delivery topology for EuroTransit Marketplace.

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
- Platform operator Applications install their CRDs and controllers at wave
  `10`; `keycloak-operator` follows at wave `15`.
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
