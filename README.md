# EuroTransit Configuration

This repository owns Kubernetes deployment, GitOps, platform configuration and operational evidence for EuroTransit Marketplace. Application behavior, API/event contracts and SLOs are defined in [application](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/README.md).

[Interactive diagrams](https://g05-eurotransit.github.io/EuroTransit-configuration/) are published from `main` through GitHub Pages.

## Choose an environment

| Environment | Start and verify | Purpose |
| --- | --- | --- |
| Standard Kind | `just kind-up`, `just kind-test` | Single-node developer/acceptance loop |
| Kind HA | `just kind-ha-up`, `just kind-ha-test` | Isolated multi-node fault experiments |
| AKS | [AKS procedure](docs/operations/aks.md) | Constrained public cluster |

[Kind setup](docs/operations/kind.md) owns prerequisites, sandbox-key input, local images and cleanup. The direct script path is separate from [Argo CD bootstrap](docs/operations/gitops.md). To inspect declarations without deploying use `just render-kind`, `just render-kind-ha` or `just render-aks`; AKS fails closed without its required ciphertext inventory.

## Platform references

| Concern | Reference |
| --- | --- |
| Topology, exposure and environment differences | [Deployment](docs/platform/deployment.md) |
| Application ownership and reconciliation order | [GitOps](docs/platform/gitops.md) |
| Resource sizing and overlap capacity | [Capacity](docs/platform/capacity.md) |
| Outboxes, workers, slots and dead letters | [CDC](docs/platform/cdc.md) |
| Identity and secrets | [OIDC](docs/platform/keycloak-oidc.md), [security/secrets](docs/platform/security-and-secrets.md) |
| Monitoring, rules and dashboard delivery | [Observability](docs/platform/observability.md) |

## Operational procedures

| Task | Procedure |
| --- | --- |
| Bootstrap or maintain an environment | [Kind](docs/operations/kind.md), [AKS](docs/operations/aks.md), [GitOps](docs/operations/gitops.md) |
| Recover the identity bootstrap client | [Identity recovery](docs/operations/identity-recovery.md) |
| Migrate CDC workers with preserved offsets | [Connect migration](docs/operations/connect-migration.md) |
| Bootstrap/reset development Inventory data | [Inventory](docs/operations/inventory.md) |
| Promote, abort or roll back workloads | [Progressive delivery](docs/operations/progressive-delivery.md) |
| Launch bounded traffic and collect evidence | [Load runner](docs/operations/load-tests.md); [harness contract](load-tests/README.md) |
| Enable and test controlled checkout refusal | [Load shedding](docs/operations/load-shedding.md) |
| Run the isolated worker-loss experiment | [HA experiment](docs/operations/ha-experiment.md) |

## Evidence and acceptance

[Verification results](docs/verification/README.md) index environment/scenario findings and incident reviews. [Readiness](docs/readiness.md) records unresolved operational acceptance. [Agent threat model](docs/governance/agent-threat-model.md) and [agent log](docs/agent-log.md) retain actual permissions and mistakes. The application [DoD](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/capstone-dod.md) owns project criteria and demonstration material. Use the shared [documentation guide](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/templates/README.md) when editing either repository.
