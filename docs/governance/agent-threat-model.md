# Agent Threat Model

Canonical agentic coding rules and review expectations are defined in the sibling application repository at `../EuroTransit-application/docs/governance/agent-governance.md`.

This document owns the configuration-side threat model: the risk that an agent-generated change to this repository is reconciled by ArgoCD into the cluster.

## Blast Radius

- This repository contains desired Kubernetes state, delivery configuration, ingress/auth rules, observability artifacts, and secret references.
- A merged change can affect runtime routing, authentication boundaries, rollout behavior, alerting, and workload permissions after ArgoCD reconciliation.
- Agent-generated changes to manifests, Helm/Kustomize output, RBAC, SealedSecrets references, Traefik routes, Keycloak integration, or ArgoCD Applications are inside the delivery control loop.

## Credentials and Permissions

- Agents must not hold direct cluster credentials.
- Agents must not hold unsealed production secrets, payment provider sandbox secrets, Keycloak client secrets, or ArgoCD admin credentials.
- Agents may propose pull requests or patches, but merge authority remains human-owned.
- CI credentials must be scoped to build/publish/update desired state only; CI must not have broad target-cluster credentials.

## Review Requirements

- Human review is required before merging agent-generated configuration changes.
- Policy-as-code or manual checks must cover broad RBAC, privileged pods, plaintext secrets, unsafe probes, public exposure of internal services, auth bypass, and destructive manifests.
- Changes to Traefik ingress, Keycloak/OIDC configuration, SealedSecrets, ArgoCD Applications, and payment provider sandbox secret wiring require review by the Technical Coordinator + Gateway/Security Slice Owner and one peer.
- Generated observability changes must be checked against the canonical SLO document in the application repository.

## Worst Case Scenario

An agent proposes a configuration change that is merged and reconciled by ArgoCD, exposing an internal service, weakening authentication, granting broad ServiceAccount permissions, breaking checkout routing, or disabling meaningful alerts. The controls are mandatory review, least-privilege RBAC, no direct agent cluster credentials, no plaintext secrets, and policy checks before merge.

## Authorized experiment exception

The policy above describes the intended boundary. The recorded fault experiments used a broader
actual boundary: the user explicitly authorized autonomous AKS fault experiments
and resource waivers, and the agent used the workstation's `eurotransit` kube
context. It could delete targeted pods, cordon/uncordon a node, temporarily
change CNPG instance count and an Argo Application policy, and create ephemeral
containers with NET_ADMIN or KILL in a selected pod namespace. It also read
load-client, service-client and Stripe sandbox credentials into memory for
requests and independent audits. This is not evidence of least-privilege RBAC.

Faults used UID conditions where applicable, bounded cleanup, no host networking
and no SQL business correction. Raw credentials were not committed or printed;
restricted local evidence contains order/provider metadata. Existing controller
pause state was preserved. CNPG test setup separately saved and restored its
Application policy and instance count. These measures bound individual tests
but do not remove the broad credential blast radius: a bad action could disrupt
checkout, expose secrets or change reconciled infrastructure. A dedicated,
short-lived experiment identity and explicit RBAC review are still required.

CI must publish immutable images and update desired state without cluster credentials. Live fault injection is not proof of GitOps deployment.
The team must review and own this exception and threat-model assessment.
