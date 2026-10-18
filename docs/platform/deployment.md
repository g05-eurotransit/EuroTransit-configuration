# Kind and AKS deployment

The checked-in Kind and AKS overlays configure one replica of each application service, one PostgreSQL instance, and one Kafka broker/controller. Kind uses a single control-plane node. These are constrained deployment topologies with single points of failure; the manifests do not establish live cluster health or continuous checkout availability.

## Deployment views

### Kind

![Kind deployment: workstation ingress, application pods, Keycloak, single-instance PostgreSQL and Kafka, and optional GitOps control](../diagrams/deployment/kind.svg)

[Open the full-size SVG](../diagrams/deployment/kind.svg) · [Download the interactive HTML](../diagrams/deployment/kind.html)

### AKS

![AKS deployment: public LoadBalancer, application pods, identity, PostgreSQL, Kafka, outbox connectors, monitoring, and Argo CD](../diagrams/deployment/aks.svg)

[Open the full-size SVG](../diagrams/deployment/aks.svg) · [Download the interactive HTML](../diagrams/deployment/aks.html)

Both views show the ingress path, grouped application workloads, identity, persistence, outbox relay, and deployment control. AKS also shows its configured monitoring stack. Namespaces identify placement; they do not by themselves prove network isolation. Operator internals and individual service interactions are omitted; see the [microservice architecture](../../../EuroTransit-application/docs/design/architecture.md) for the application view.

The diagrams describe the committed configuration. They do not incorporate unmerged HA proposals or claim that those manifests have been reconciled on a live cluster.

## Environment differences

| Concern | Kind | AKS |
| --- | --- | --- |
| Application values | [Base](../../charts/eurotransit/values.yaml) + [Kind overrides](../../charts/eurotransit/values-kind.yaml) | Base + [production overrides](../../charts/eurotransit/values-production.yaml) |
| Ingress | Traefik ClusterIP with host ports mapped to the workstation | Traefik LoadBalancer with an Azure DNS label |
| Public identity | Separate `eurotransit.local` and `keycloak.eurotransit.local` hosts | Application and Keycloak paths share `g05.cpo2026.it` |
| TLS | Local certificates issued by a self-signed issuer | Production certificates use the configured Let's Encrypt issuer |
| Application replicas | One per service and frontend | One per service and frontend |
| PostgreSQL | One instance, 2 Gi storage | One instance, 5 Gi storage |
| Kafka | One dual-role broker/controller, replication factor 1 | One dual-role broker/controller, replication factor 1 |
| Monitoring | Kind GitOps excludes the monitoring applications; the direct setup script has an optional stack | Argo CD installs Prometheus, Grafana, and Alertmanager plus monitoring configuration |
| Trace export | Disabled in effective chart values | Disabled in effective chart values |
| Secret provisioning | Direct setup creates local Secrets; the separate GitOps procedure uses Sealed Secrets | Controller-bound SealedSecrets through GitOps |
| Reconciliation | Optional Argo CD Kind overlay; direct setup also exists | Argo CD applications select AKS overlays and production values |

The [Kind runtime overlay](../../platform/environments/kind/kustomization.yaml) and [AKS runtime overlay](../../platform/environments/aks/kustomization.yaml) override the larger base PostgreSQL and Kafka topologies. Kafka inherits ephemeral storage from the [base cluster definition](../../platform/strimzi/kafka-cluster.yaml), including on AKS.

## Operational constraints

Single service replicas interrupt their own traffic during replacement. A single PostgreSQL instance has no standby for primary promotion; a single Kafka broker with ephemeral storage provides neither broker redundancy nor a durable replicated log. Node capacity and persistent storage behavior require separate operational verification.

PDBs differ between the overlays. The [PDB template](../../charts/eurotransit/templates/poddisruptionbudgets.yaml) reads `global.podDisruptionBudget.enabled`: production disables it at that path, but Kind's override sets a top-level `podDisruptionBudget.enabled` and leaves the base global setting enabled. Kind therefore renders five PDBs with `minAvailable: 1` for single-replica services, which can block voluntary eviction. The mismatch is documented here for a later configuration fix.

[Ingress routes](../../charts/eurotransit/templates/ingressroutes.yaml) expose the frontend, Catalog, Orders, and the enabled Notifications API. Inventory and Payments have no public IngressRoute. Forward-auth is disabled in the [base values](../../charts/eurotransit/values.yaml); JWT checks remain in the services. This differs from the gateway-authentication requirement in the [application DoD](../../../EuroTransit-application/docs/capstone-dod.md) and must remain an explicit gap.

Argo CD reconciles platform controllers, runtime resources, application workloads, and connectors in ordered waves. Rollouts is installed by the platform applications, while progressive-delivery resources remain disabled by default in the marketplace values. Their existence in the chart does not prove a canary or blue/green execution.

Application ServiceMonitors are disabled in Kind. Installing the optional monitoring stack alone does not enable them. AKS configures ServiceMonitors, but an allowed scrape endpoint and matching selectors still require verification. Neither environment enables trace export through these values.

## Sources and procedures

- [Argo CD applications](../../platform/argocd/base/platform-applications.yaml) and [Kind patches](../../platform/argocd/environments/kind/kustomization.yaml) select the environment resources. [Connector overlays](../../platform/connectors/environments/aks/kustomization.yaml) configure the outbox relay separately from the marketplace chart.
- [Kind setup](kind-local-setup.md), [cluster bootstrap](cluster-bootstrap-runbook.md), and [Argo CD bootstrap](argocd-bootstrap.md) describe setup paths.
- [AKS setup](aks-production-setup.md), [Kind GitOps secrets](kind-gitops-secrets-runbook.md), and [security and secrets](security-and-secrets.md) describe environment prerequisites.
- [Observability](observability.md) maps monitoring artifacts. [Readiness](../delivery/production-readiness-gap-analysis.md) tracks operational acceptance; the observations above are configuration findings, not new runtime test results.
