# Deployment environments

Choose standard Kind for development, Kind HA for isolated multi-node experiments, or AKS for the constrained public environment. Kind HA declares replicated application/data workloads; standard Kind and AKS retain single-instance failure points. Configuration describes intended topology, while the [verification index](../verification/README.md) records what was observed.

## Deployment views

### Kind

[![Kind deployment: workstation ingress, application pods, Keycloak, single-instance PostgreSQL and Kafka, and optional GitOps control](../diagrams/deployment/kind.svg)](https://g05-eurotransit.github.io/EuroTransit-configuration/deployment/kind.html)

[Open the full-size SVG](../diagrams/deployment/kind.svg) · [Open interactive diagram](https://g05-eurotransit.github.io/EuroTransit-configuration/deployment/kind.html)

### Kind HA

[![Kind HA: separated critical replicas, synchronous PostgreSQL, replicated persistent Kafka and two shared Connect workers](../diagrams/deployment/kind-ha.svg)](https://g05-eurotransit.github.io/EuroTransit-configuration/deployment/kind-ha.html)

[Full-size SVG](../diagrams/deployment/kind-ha.svg) · [Open interactive diagram](https://g05-eurotransit.github.io/EuroTransit-configuration/deployment/kind-ha.html)

The [HA runbook](../operations/ha-experiment.md) owns the isolated setup, host capacity gates and fault cleanup. All nodes share one workstation; this is not a physical-host/AZ failure topology.

### AKS

[![AKS deployment: public LoadBalancer, application pods, identity, PostgreSQL, Kafka, outbox connectors, monitoring, and Argo CD](../diagrams/deployment/aks.svg)](https://g05-eurotransit.github.io/EuroTransit-configuration/deployment/aks.html)

[Open the full-size SVG](../diagrams/deployment/aks.svg) · [Open interactive diagram](https://g05-eurotransit.github.io/EuroTransit-configuration/deployment/aks.html)

The views show the ingress path, grouped application workloads, identity, persistence, outbox relay, and deployment control. AKS also shows its configured monitoring stack. Namespaces identify placement; they do not by themselves prove network isolation. Operator internals and individual service interactions are omitted; see the [microservice architecture](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/architecture.md) for the application view.

The diagrams describe the committed configuration. Use the scenario reports for live observations; declared replicas alone do not prove availability.

## Environment differences

| Concern | Kind | AKS |
| --- | --- | --- |
| Application values | [Base](../../charts/eurotransit/values.yaml) + [Kind overrides](../../charts/eurotransit/values-kind.yaml) | Base + [production overrides](../../charts/eurotransit/values-production.yaml) |
| Ingress | Traefik ClusterIP with host ports mapped to the workstation | Traefik LoadBalancer with an Azure DNS label |
| Public identity | Separate `eurotransit.local` and `keycloak.eurotransit.local` hosts | Application and Keycloak paths share `g05.cpo2026.it` |
| TLS | Local certificates issued by a self-signed issuer | Production certificates use the configured Let's Encrypt issuer |
| Application replicas | One per service and frontend | One per service and frontend |
| PostgreSQL | One instance, 2 Gi storage | One instance, 10 Gi storage |
| Kafka | One dual-role broker/controller, replication factor 1 | One dual-role broker/controller, replication factor 1 |
| Monitoring | Kind GitOps excludes the monitoring applications; the direct setup script has an optional stack | Argo CD installs Prometheus, Grafana, and Alertmanager plus monitoring configuration |
| Trace export | Disabled in effective chart values | Disabled in effective chart values |
| Secret provisioning | Direct setup creates local Secrets; the separate GitOps procedure uses Sealed Secrets | Controller-bound SealedSecrets through GitOps |
| Reconciliation | Optional Argo CD Kind overlay; direct setup also exists | Argo CD applications select AKS overlays and production values |

The [Kind runtime overlay](../../platform/environments/kind/kustomization.yaml) and [AKS runtime overlay](../../platform/environments/aks/kustomization.yaml) override the larger base PostgreSQL and Kafka topologies. Kafka inherits ephemeral storage from the [base cluster definition](../../platform/strimzi/kafka-cluster.yaml), including on AKS.

## Kind HA profile

[HA values](../../charts/eurotransit/values-kind-ha.yaml) run two Catalog, Orders, Inventory, Payments and frontend replicas, and one Notifications replica, with required critical-service anti-affinity. The [four-node Kind configuration](../../platform/kind/kind-ha-config.yaml) has one control plane and three workers. [PostgreSQL](../../platform/environments/kind-ha/postgres-patch.yaml) uses three persistent instances and required `ANY 1` synchronous replication; [Kafka](../../platform/environments/kind-ha/kafka-patch.yaml) retains three broker/controllers, persistent storage, RF 3 and min ISR 2. [Connect](../../platform/connectors/environments/kind-ha/shared-ha-patch.yaml) uses two replicas in one shared distributed group. Monitoring and committed-lag export are enabled by the HA procedure; tracing export remains disabled.

## Operational constraints

Catalog's application/chart default remains in-memory. The production profile declares PostgreSQL storage, a dedicated managed role and a retained CNPG Database resource; its [AKS delivery procedure](../operations/catalog-postgres-aks.md) requires reviewed application publication before the activation is merged. The [Kind procedure](../operations/catalog-postgres-kind.md) verifies local behavior separately. Both ordinary Deployment and progressive `workloadRef` use the same database variables and authenticated startup gate. Database health participates in readiness; liveness remains independent. These production manifests were prepared without applying them to AKS.

In standard Kind and AKS, single service replicas interrupt their own traffic during replacement. A single PostgreSQL instance has no standby for primary promotion; a single Kafka broker with ephemeral storage provides neither broker redundancy nor a durable replicated log. Node capacity and persistent storage behavior require separate operational verification.

PDBs differ between the overlays. The [PDB template](../../charts/eurotransit/templates/poddisruptionbudgets.yaml) reads `global.podDisruptionBudget.enabled`: production disables it at that path, but Kind's override sets a top-level `podDisruptionBudget.enabled` and leaves the base global setting enabled. Kind therefore renders five PDBs with `minAvailable: 1` for single-replica services, which can block voluntary eviction. The mismatch is documented here for a later configuration fix.

[Ingress routes](../../charts/eurotransit/templates/ingressroutes.yaml) expose the frontend, Catalog, Orders, and the enabled Notifications API. Inventory and Payments have no public IngressRoute. Forward-auth is disabled in the [base values](../../charts/eurotransit/values.yaml); JWT checks remain in the services. This differs from the gateway-authentication requirement in the [application DoD](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/capstone-dod.md) and must remain an explicit gap.

Argo CD reconciles platform controllers, runtime resources, application workloads, and connectors in ordered waves. Rollouts is installed by the platform applications, while progressive-delivery resources remain disabled by default in the marketplace values. Their existence in the chart does not prove a canary or blue/green execution.

Application ServiceMonitors are disabled in Kind. Installing the optional monitoring stack alone does not enable them. AKS configures ServiceMonitors, but an allowed scrape endpoint and matching selectors still require verification. Neither environment enables trace export through these values.

## Exposure and source configuration

| Endpoint | Exposure | Configuration |
| --- | --- | --- |
| Frontend and public APIs | Traefik routes to service ClusterIPs | [Application IngressRoutes](../../charts/eurotransit/templates/ingressroutes.yaml) |
| Inventory / Payments | Internal services; baseline NetworkPolicies | [Network policies](../../charts/eurotransit/templates/networkpolicies.yaml) |
| Keycloak discovery, login and tokens | Separate local host; shared public host/path on AKS | [OIDC setup](keycloak-oidc.md) |
| Argo CD UI | Platform administration endpoint | [Argo ingress](../../platform/traefik/argocd-ingressroute.yaml) |

[Traefik values](../../platform/traefik/values.yaml) configure the controller; [middleware templates](../../charts/eurotransit/templates/traefik-middlewares.yaml) configure route behavior. Namespace placement alone is not proof of network isolation.

Protected endpoint identities, roles, ownership and correlation semantics are defined by the application [API contract](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/api-design.md) and [observability conventions](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/development/instrumentation.md). Verify public reads, unauthenticated rejection and internal-route absence through the [smoke procedure](../operations/kind.md).
