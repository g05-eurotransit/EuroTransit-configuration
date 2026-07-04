# EuroTransit Configuration Documentation

This repository owns deployment, GitOps, Kubernetes, delivery, observability, reliability, and operational governance documentation for EuroTransit Marketplace.

Application behavior, API contracts, service design, authentication model, idempotency semantics, and team implementation planning live in the sibling application repository: `../EuroTransit-application/docs`.

## Documentation Map

- `delivery/`: GitOps, CI/CD, kind smoke/e2e checks, progressive delivery, and delivery readiness.
- `platform/`: Kubernetes networking, ingress, secrets, observability stack, and references to application contracts.
- `reliability/`: SLOs, chaos experiment reports, and postmortems.
- `governance/`: agent threat model and agent activity log.

Keep this repository focused on how EuroTransit is deployed, operated, observed, and validated on Kubernetes. Do not duplicate service API or domain design documents here; link to the application repository instead.

The expected Kubernetes/GitOps artifact shape is tracked in [delivery/configuration-artifact-backlog.md](delivery/configuration-artifact-backlog.md) until concrete manifests and Helm/Kustomize assets are added.
