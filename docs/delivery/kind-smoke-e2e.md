# kind Smoke and E2E Workflow

Docker Compose remains the fast developer loop. kind is the Kubernetes acceptance gate used by CI to prove that manifests, routing, authentication boundaries, readiness probes, and core e2e behavior work on Kubernetes.

**Owner:** Technical Coordinator + Gateway/Security Slice Owner.

## Expected Workflow

1. Check out the repository.
2. Set up Java 21.
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

## Current Baseline

The application repository currently provides the first smoke-test baseline:

- `just smoke-kind` runs `scripts/smoke-kind.sh`;
- the script builds all Gradle modules with Java 21;
- local service images are built and loaded into kind;
- minimal Kubernetes manifests deploy Catalog, Orders, Inventory, Payments, and Notifications;
- rollout status and `/actuator/health` are checked for each service.

This baseline intentionally proves only that the service images can start on Kubernetes and expose health endpoints. It does not yet prove gateway routing, authentication, frontend behavior, database/Kafka integration, or checkout business flow.

## Evolution Path

Evolve the smoke workflow in small gates:

1. Keep the current health/readiness smoke stable and runnable locally through `just smoke-kind`.
2. Add the same smoke workflow to GitHub Actions as a manual or non-required job before making it a required PR gate.
3. Replace smoke-only manifests with the same Helm/Kustomize output used by the configuration repository.
4. Add Traefik or the selected gateway and verify public route availability.
5. Add public/internal route separation checks so Inventory and Payments are not externally routable.
6. Add local/kind authentication material, using fixed development JWTs or a mock OIDC issuer only for local and CI smoke checks.
7. Add a dedicated application `:e2e:test` suite that exercises the gateway base URL.
8. Expand the e2e suite to cover the minimal checkout happy path once Orders, Inventory, Payments, and Catalog contracts are implemented.
9. Include the React frontend route once the frontend image and route exist.

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
