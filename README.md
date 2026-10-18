# EuroTransit Configuration

This repository defines Kubernetes deployment, GitOps delivery, platform configuration, and operational verification for EuroTransit Marketplace. Application behavior and contracts live in [EuroTransit Application](https://github.com/g05-eurotransit/EuroTransit-application/tree/dev).

## Choose an environment

| Environment | Purpose | Entry point |
| --- | --- | --- |
| Kind | Single-node local development | [Local setup](docs/platform/kind-local-setup.md) |
| Kind HA | Isolated worker-loss, failover, and delivery experiments | [HA runbook](docs/reliability/kind-ha-runbook.md) |
| AKS | Resource-constrained cluster deployment | [AKS setup](docs/platform/aks-production-setup.md) |

The [deployment reference](docs/platform/deployment.md) shows each topology and its limitations. Direct Kind setup uses local scripts and Helm; the GitOps path reconciles committed desired state through Argo CD. These are distinct deployment methods.

## Start with Kind

Prerequisites and application checkout requirements are in [local setup](docs/platform/kind-local-setup.md).

```bash
just kind-up
just kind-test
just kind-status
```

These commands create and modify a local cluster. To inspect configuration without deploying:

```bash
just render-kind
just render-aks
```

AKS rendering requires the documented secret inventory; a fail-closed render is a prerequisite failure, not live proof.

## Find the right document

| Need | Start here |
| --- | --- |
| Understand placement and topology | [Deployment](docs/platform/deployment.md) |
| Bootstrap or recover a cluster | [Platform](docs/platform/README.md) |
| Understand build, promotion, and rollback | [Delivery](docs/delivery/README.md) |
| Inspect executed experiments | [Reliability evidence](docs/reliability/chaos-experiment-reports.md) |
| See remaining environment gaps | [Readiness](docs/delivery/readiness.md) |
| Navigate all documentation | [Documentation](docs/README.md) |

Use the [shared documentation guide](https://github.com/g05-eurotransit/EuroTransit-application/blob/dev/docs/templates/README.md) when editing either repository.
