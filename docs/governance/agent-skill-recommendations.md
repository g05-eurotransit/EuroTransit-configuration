# Agent Skill Recommendations

Agent skill drafts are versioned in the sibling application repository at `../EuroTransit-application/docs/agent-skills`.

This repository must not duplicate those skill definitions. Configuration-side docs should only record which skills are relevant for GitOps, Kubernetes, operational proof, and generated-manifest review.

## Use From Application Repo

- `eurotransit-cross-repo-docs`: use before changing documentation that may affect both repositories.
- `kotlin-coroutines-webflux-pipeline`: use when application changes affect async service behavior that deployment or observability docs must reflect.

## Prioritize Next For Configuration Work

- `eurotransit-gitops-k8s`: Argo CD, Kubernetes manifests, Kustomize/Helm, probes, PDBs, Traefik, secrets, Strimzi, CloudNativePG, and progressive delivery.
- `eurotransit-resilience-observability-chaos`: SLOs, OpenTelemetry, Prometheus/Grafana, alerting, retries, load shedding, and Chaos Mesh evidence.
- `eurotransit-security-payments`: Keycloak/OIDC production assumptions, service-to-service auth, secret handling, sandbox payment providers, and audit-sensitive deployment boundaries.

Keep this file as a routing note. Change the actual skill content in the sibling application repository so teammates and agents have one canonical copy.
