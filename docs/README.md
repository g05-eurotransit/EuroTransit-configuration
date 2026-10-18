# Configuration documentation

Use [deployment](platform/deployment.md) to choose an environment, [platform procedures](platform/README.md) to operate it, and the [experiment index](reliability/chaos-experiment-reports.md) to inspect verified results.

| Section | Contents |
| --- | --- |
| [Platform](platform/README.md) | Kind/Kind HA/AKS, identity, networking, secrets, databases and monitoring |
| [Delivery](delivery/README.md) | GitOps ownership, smoke tests, promotion, rollback and readiness |
| [Reliability](reliability/chaos-experiment-reports.md) | Current scenario reports, reproduction procedures and bounded evidence |
| [Agent threat model](governance/agent-threat-model.md) | Operational permissions and failure impact |
| [Agent log](agent-log.md) | Configuration-specific mistakes and corrections |

[Application documentation](https://github.com/g05-eurotransit/EuroTransit-application/blob/dev/docs/README.md) owns behavior, API/event contracts, domain decisions, SLO definitions and the project DoD. Both repositories use the [same writing guide and templates](https://github.com/g05-eurotransit/EuroTransit-application/blob/dev/docs/templates/README.md).
