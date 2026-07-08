# EuroTransit Configuration Documentation

This repository owns deployment, GitOps, Kubernetes, delivery, observability, reliability, and operational governance documentation for EuroTransit Marketplace.

Application behavior, API contracts, service design, authentication model, idempotency semantics, and team implementation planning live in the sibling application repository: `../EuroTransit-application/docs`.

## Documentation Map

- `delivery/`: GitOps, CI/CD, kind smoke/e2e checks, progressive delivery, and delivery readiness.
- `platform/`: Kubernetes networking, ingress, identity, secrets, observability stack, cluster bootstrap runbooks, and references to application contracts.
- `reliability/`: SLOs, chaos experiment reports, and postmortems.
- `governance/`: agent threat model, agent activity log, and agent skill routing.

Keep this repository focused on how EuroTransit is deployed, operated, observed, and validated on Kubernetes. Do not duplicate service API or domain design documents here; link to the application repository instead.

The cluster bootstrap sequence is documented in [platform/cluster-bootstrap-runbook.md](platform/cluster-bootstrap-runbook.md). Keycloak/OIDC environment configuration is documented in [platform/keycloak-oidc.md](platform/keycloak-oidc.md). Remaining Kubernetes/GitOps artifact gaps are tracked in [delivery/configuration-artifact-backlog.md](delivery/configuration-artifact-backlog.md).

Agent skill drafts are canonical in the sibling application repository under `../EuroTransit-application/docs/agent-skills`; this repository keeps only the configuration-side routing note in [governance/agent-skill-recommendations.md](governance/agent-skill-recommendations.md).
