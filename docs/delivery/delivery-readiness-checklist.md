# EuroTransit Delivery Readiness Checklist

This checklist defines the configuration-side criteria for EuroTransit Marketplace to be considered ready to run and be demonstrated on Kubernetes. The general product Definition of Done lives in the application repository at `../EuroTransit-application/docs/capstone-dod.md` from the parent project directory.

## GitOps Delivery

- [ ] CI builds immutable service images.
- [ ] CI updates the configuration repository without holding cluster credentials.
- [ ] ArgoCD reconciles the expected cluster state.
- [ ] Rollback procedure is documented and tested at least once.

## Local Kubernetes Smoke Gate

- [ ] kind workflow creates a temporary Kubernetes cluster in CI.
- [ ] Service images are built and loaded into kind.
- [ ] React frontend image is built and loaded into kind when frontend routing is part of the check.
- [ ] Kubernetes manifests or Helm/Kustomize output deploy successfully.
- [ ] Readiness checks pass for all required services.
- [ ] Kotlin/JUnit e2e smoke tests run through the gateway.

## Gateway, Auth, and Routing

- [ ] React frontend route is exposed through the gateway.
- [ ] Traefik exposes only intended public APIs.
- [ ] Keycloak is configured as the OIDC provider for target-cluster proof.
- [ ] Protected APIs reject unauthenticated requests.
- [ ] Inventory and Payments are not publicly routable.
- [ ] Secret and config values are externalized and not committed as plaintext secrets.
- [ ] Payment provider sandbox/test credentials are configured through the selected secret mechanism.
- [ ] Final cluster/demo proof does not depend on mocked services.

## Progressive Delivery

- [ ] Canary delivery is demonstrated for Orders.
- [ ] Blue/Green delivery is demonstrated for Catalog.
- [ ] Promotion and rollback criteria are tied to observable signals.

## Observability and Reliability Proof

- [ ] Checkout latency and success-rate SLOs are defined.
- [ ] Dashboards cover RED metrics for services and USE metrics for infrastructure.
- [ ] Alerts are symptom-based and demonstrably fire under injected failure.
- [ ] Distributed tracing can follow one order across the money path.
- [ ] Chaos experiment reports and one blameless postmortem are completed.
