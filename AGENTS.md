# Agent Project Notes

- The product/system name is **EuroTransit** or **EuroTransit Marketplace**.
- Treat academic assignment wording as external context, not as product identity.
- Follow assignment-mandated deliverable names exactly when the specification names a required file or path, even if that filename contains academic wording. Do not generalize that wording into product names, service names, APIs, Docker images, Helm releases, or user-facing copy.
- This repository owns Kubernetes, GitOps, ingress, secrets, observability, reliability, and operational proof for EuroTransit Marketplace.
- Application behavior, API contracts, service design, authentication/authorization semantics, and team implementation planning live in the sibling `EuroTransit-application` repository.
- Agents expect `EuroTransit-application` and `EuroTransit-configuration` to be checked out in the same parent folder. If either repository is missing, ask the user to clone it into that same folder before making cross-repository documentation changes.
- When updating documentation, always evaluate both repositories and keep them aligned: application docs own behavior/contracts/team planning, while configuration docs own Kubernetes, GitOps, ingress, secrets, observability, and operational proof.
- Do not duplicate application service contracts here unless needed for deployment or operational validation; prefer linking to the application repository docs.
