# kind Smoke and E2E Workflow

Docker Compose remains the fast developer loop. kind is the Kubernetes acceptance gate used by CI to prove that manifests, routing, authentication boundaries, readiness probes, and core e2e behavior work on Kubernetes.

**Owner:** Technical Coordinator + Gateway/Security Slice Owner.

## Expected Workflow

1. Check out the repository.
2. Set up Java 17.
3. Create a kind cluster.
4. Build Gradle modules.
5. Build Docker images for all services.
6. Load images into kind.
7. Apply Kubernetes manifests or Helm/Kustomize output.
8. Wait for Deployments and readiness probes.
9. Port-forward Traefik or the gateway service to `localhost:8080`.
10. Run `sh gradlew :e2e:test -DbaseUrl=http://localhost:8080` from the application repository.
11. On failure, collect pod descriptions, events, and logs.
12. Delete the kind cluster.

## PR Gate Scope

Keep the mandatory kind workflow small and reliable, ideally under 10-15 minutes.

Include:

- deployment and readiness checks;
- gateway routing checks;
- authentication smoke checks;
- public/internal route separation;
- React frontend route availability;
- a minimal checkout happy path when dependencies are available.

Exclude from the mandatory PR gate:

- ArgoCD reconciliation;
- full Prometheus/Grafana dashboards;
- full Strimzi and CloudNativePG failure scenarios;
- Chaos Mesh experiments.

Those heavier checks belong in manual, nightly, pre-demo, or target-cluster validation workflows.

## Required Inputs from Service Owners

- Services expose stable health/readiness endpoints.
- Service runtime variables are documented.
- E2E tests are kept aligned with API contracts.
- Local/CI auth material is available for smoke tests. Fixed development JWTs or a mock OIDC issuer are allowed only for local/kind smoke checks; target-cluster proof uses Keycloak.
- Payment provider sandbox/test credentials are available through the selected secret mechanism when the Payments slice is included in the smoke workflow.
