# Operations

Choose an environment, then follow its setup and verification procedure.

## Setup and maintenance

- [Kind](kind.md): standard and HA local environments.
- [AKS](aks.md): public-cluster bootstrap and recovery.
- [GitOps](gitops.md): Argo CD, repository credentials and controlled maintenance.

## Recovery and data

- [Identity recovery](identity-recovery.md)
- [Connect migration](connect-migration.md): preserve CDC offsets during worker migration.
- [Inventory](inventory.md): development-data bootstrap and reset.
- [Catalog PostgreSQL on Kind](catalog-postgres-kind.md): provision, verify and roll back persistent offers.
- [Catalog PostgreSQL on AKS](catalog-postgres-aks.md): GitOps resources, startup gating and reviewed delivery.

## Delivery and experiments

- [Progressive delivery](progressive-delivery.md): promote, abort and roll back.
- [Load tests](load-tests.md): bounded traffic, faults and evidence collection. [Testing and tooling](../verification/testing-tooling.md) maps the workflow and tools to recorded experiments.
- [Load shedding](load-shedding.md)
- [HA experiment](ha-experiment.md): isolated worker loss and primary failover.

[Verification](../verification/README.md) contains results; [readiness](../readiness.md) tracks acceptance gaps. The [agent threat model](../governance/agent-threat-model.md) and [agent log](../agent-log.md) document automation controls and corrections. Documentation follows the shared [writing guide](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/templates/README.md).
