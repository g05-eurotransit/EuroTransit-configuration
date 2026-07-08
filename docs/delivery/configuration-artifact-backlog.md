# Configuration Artifact Backlog

This backlog tracks the Kubernetes/GitOps artifacts that must exist before final cluster/demo proof. It prevents the documentation from implying that manifests already exist while still making the expected repository shape explicit.

Application behavior and service contracts remain canonical in the sibling application repository. This repository owns the deployable configuration and operational proof artifacts.

## GitOps and Environments

- [x] ArgoCD Application definitions for platform and application workloads (initial app-of-apps manifests; cluster sync proof pending).
- [x] Environment layout for local/kind and demo namespace bootstrap (target-cluster overlays still pending).
- [ ] Image tag update strategy used by application CI.
- [ ] Rollback procedure for application services and frontend.

## Platform Components

- [x] Traefik ingress and middleware configuration (public Catalog/Orders/Notifications routes; forward-auth integration pending).
- [x] Keycloak/OIDC configuration references and Helm values for kind, proof, and production overlays.
- [x] SealedSecrets controller configuration and templates (real sealed values pending).
- [x] Strimzi Kafka cluster and topic manifests (Kafka users pending if TLS/SASL is enabled).
- [x] CloudNativePG cluster/database configuration for `orders_db`, `inventory_db`, and `payments_db` with separate service credential references.
- [x] kube-prometheus-stack configuration (tracing collector still pending).
- [x] Chaos Mesh installation values (experiment manifests still pending).

## Application Workloads

- [ ] React frontend deployment/service/route.
- [x] Catalog deployment/service/route (blue/green configuration still pending).
- [x] Orders deployment/service/route (canary configuration still pending).
- [x] Inventory deployment/service and internal-only routing baseline.
- [x] Payments deployment/service, internal-only routing, and sandbox provider secret references.
- [x] Notifications deployment/service, public read route toggle, and Kafka topic baseline.

## Observability and Reliability

- [x] PrometheusRule definitions for checkout success-rate and latency alerts.
- [ ] Grafana dashboards for service RED metrics and infrastructure USE/Golden Signals.
- [ ] Kafka lag and pipeline convergence dashboards.
- [ ] Inventory correctness and payment safety panels.
- [ ] Chaos Mesh experiment manifests for the required experiments.
- [ ] Links to completed chaos reports and postmortem evidence.

## Security and Governance

- [ ] RBAC and ServiceAccount definitions with least privilege.
- [x] Network/routing rules proving Inventory and Payments are not public.
- [x] Secret names documented through SealedSecret templates for Keycloak, payment sandbox provider, databases, and Grafana (rotation procedure pending).
- [ ] Service environment/config values for idempotency retention: Inventory 30 minutes, Orders 24 hours, Payments 24 hours.
- [ ] Policy or review checklist for generated manifests before merge.
