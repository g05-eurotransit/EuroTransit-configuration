# Configuration Artifact Backlog

This backlog tracks the Kubernetes/GitOps artifacts that must exist before final cluster/demo proof. It prevents the documentation from implying that manifests already exist while still making the expected repository shape explicit.

Application behavior and service contracts remain canonical in the sibling application repository. This repository owns the deployable configuration and operational proof artifacts.

## GitOps and Environments

- [ ] ArgoCD Application definitions for platform and application workloads.
- [ ] Environment layout for local/kind, target-cluster proof, and any demo namespace.
- [ ] Image tag update strategy used by application CI.
- [ ] Rollback procedure for application services and frontend.

## Platform Components

- [ ] Traefik ingress and middleware configuration.
- [ ] Keycloak/OIDC configuration references for the cluster/proof target.
- [ ] SealedSecrets or selected external secret mechanism.
- [ ] Strimzi Kafka topics/users required by the application.
- [ ] CloudNativePG cluster/database configuration for `orders_db`, `inventory_db`, and `payments_db` with separate service credentials.
- [ ] kube-prometheus-stack and tracing collector configuration.
- [ ] Chaos Mesh installation or reference.

## Application Workloads

- [ ] React frontend deployment/service/route.
- [ ] Catalog deployment/service/route and blue/green configuration.
- [ ] Orders deployment/service/route and canary configuration.
- [ ] Inventory deployment/service and internal-only routing.
- [ ] Payments deployment/service, internal-only routing, and sandbox provider secret references.
- [ ] Notifications deployment/service and Kafka consumer configuration.

## Observability and Reliability

- [ ] PrometheusRule definitions for checkout success-rate and latency alerts.
- [ ] Grafana dashboards for service RED metrics and infrastructure USE/Golden Signals.
- [ ] Kafka lag and pipeline convergence dashboards.
- [ ] Inventory correctness and payment safety panels.
- [ ] Chaos Mesh experiment manifests for the required experiments.
- [ ] Links to completed chaos reports and postmortem evidence.

## Security and Governance

- [ ] RBAC and ServiceAccount definitions with least privilege.
- [ ] Network/routing rules proving Inventory and Payments are not public.
- [ ] Secret names and rotation expectations documented for Keycloak, payment sandbox provider, databases, and Kafka.
- [ ] Service environment/config values for idempotency retention: Inventory 30 minutes, Orders 24 hours, Payments 24 hours.
- [ ] Policy or review checklist for generated manifests before merge.
