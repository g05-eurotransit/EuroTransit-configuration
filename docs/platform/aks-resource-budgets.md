# AKS resource budgets

These initial budgets apply only to the AKS profile. They change persistent
Helm values and operator CRs; generated Deployments, Pods and AKS-managed
components must not be patched. Keep existing CPU budgets and JVM settings.
The shared Kafka Connect worker remains at Xms=128m and Xmx=512m while its
memory request increases to 512Mi; consolidation and heap reduction are
separate changes.

| Component | Memory request / limit (MiB) | Persistent owner |
| --- | --- | --- |
| Argo application-controller | 384 / 1536 | `platform/argocd/values-aks.yaml` |
| Argo repo-server | 128 / 384 | same Helm overlay |
| Argo server | 48 / 192 | same Helm overlay |
| Argo Redis | 16 / 64 | same Helm overlay |
| cert-manager controller; webhook | 32 / 128 each | `platform/cert-manager/values-aks.yaml` |
| cert-manager cainjector | 64 / 192 | same Helm overlay |
| CloudNativePG operator | 64 / 256 | `platform/cloudnativepg/values-aks.yaml` |
| PostgreSQL | 192 / 512 | `platform/environments/aks/postgres-patch.yaml` |
| Kafka broker | 448 / 768 | `platform/environments/aks/kafka-nodepool-patch.yaml` |
| Kafka Topic Operator | 192 / 384 | `platform/environments/aks/kafka-patch.yaml` |
| Shared Kafka Connect worker | 512 / 768 | `platform/connectors/environments/aks/connect-patch.yaml` |
| catalog | 224 / 512 | `charts/eurotransit/values-production.yaml` |
| orders | 320 / 512 | same Helm overlay |
| inventory; payments; notifications | 256 / 512 each | same Helm overlay |
| frontend | 16 / 128 | same Helm overlay |
| Keycloak | 512 / 768 | existing `platform/keycloak/keycloak.yaml` |
| Keycloak Operator | 224 / 450 | `platform/keycloak-operator/environments/aks` |
| Prometheus | 320 / 768 | `platform/kube-prometheus-stack/values-aks.yaml` |
| Alertmanager | 32 / 128 | same Helm overlay |
| Prometheus / Alertmanager config reloader | 24 / 64 each | same Helm overlay, `prometheusOperator.prometheusConfigReloader` |
| Grafana | 160 / 384 | same Helm overlay |
| kube-state-metrics | 32 / 128 | same Helm overlay |
| Prometheus Operator | 64 / 256 | same Helm overlay |
| node-exporter | 16 / 64 per node | same Helm overlay |
| Sealed Secrets | 32 / 128 | `platform/sealed-secrets/values-aks.yaml` |
| Strimzi Cluster Operator | 256 / 512 | existing `platform/strimzi/values-aks.yaml` |
| Traefik | 48 / 256 | `platform/traefik/values-aks.yaml` |
| Argo Rollouts controller | 64 / 192 | existing Helm values in platform Application |

The application-controller limit was raised from 768Mi to 1536Mi after
release qualification found OOMs at both 768Mi and 1024Mi during reconciliation. Its 384Mi request
and CPU budget stay unchanged, so the scheduling-request totals below do not
change. Requalify startup and the load window after any such correction.

The local Keycloak Operator overlay vendors the exact upstream 26.7.0 resources,
with SHA-256 checksums. It changes only the Deployment memory resources. CPU
stays at upstream's 300m/700m. CRDs, RBAC, ServiceAccount, image and operator
configuration are preserved. The AKS Application selects that local overlay;
the Kind Application continues to select upstream directly.

Bootstrap owners must receive their AKS values too. The Argo bootstrap uses
`-f platform/argocd/values.yaml -f platform/argocd/values-aks.yaml`; Sealed Secrets
uses `-f platform/sealed-secrets/values.yaml -f platform/sealed-secrets/values-aks.yaml`
on both install and upgrade. Use shared values alone for Kind. See
[AKS setup](aks-production-setup.md) and [Argo bootstrap](argocd-bootstrap.md).

The chart hooks and init containers also have explicit budgets: repo-server's
copyutil init container and Redis secret-init Job each request 16Mi and limit
64Mi, as do cert-manager startupapicheck and each Prometheus admission
create/patch Job. The optional monitoring CRD upgrade Job has 32Mi/128Mi when
enabled. Existing inventory bootstrap requests 32Mi/128Mi; the four Keycloak
reconciliation/bootstrap Jobs retain 64Mi/256Mi each. KeycloakRealmImport
retains 512Mi/1024Mi. The suspended k6 CronJob, when progressive delivery is
enabled, retains 128Mi/256Mi. Do not assume completed or suspended Jobs reserve
running capacity; reserve it when planning a new start or a reconciliation.

For normal init containers, a Pod's scheduling request is the larger of the
sum of regular container requests and the largest init container request.
Restartable init sidecars contribute to steady state and subsequent init
stages. Account for Pod overhead and operator-generated Pods, including CNPG
bootstrap/recovery, Keycloak import and Prometheus/Alertmanager reloaders.
CloudNativePG 1.26.0 assigns `cluster.Spec.Resources` to both its
[bootstrap init container](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.26.0/pkg/specs/containers.go#L34)
and [bootstrap/recovery Job container](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.26.0/pkg/specs/jobs.go#L358).
Rendered CR resources and the pinned operator behavior define those budgets;
the next live inventory must verify the generated Pods actually match.

Before release, calculate requests against each node's allocatable capacity,
which already excludes kube/system reservations. Subtract AKS-managed Pod
requests and current project Pods, and inspect placement,
affinity, volumes and taints. Aggregate free memory does not imply that a
512Mi Pod can fit on any individual node. Reserve overlap for one controlled
rollout at a time, temporary Jobs and the current image-cleaner workload.
The plan's approximately 981Mi aggregate headroom is an estimate tied to the
observed baseline; it does not guarantee three simultaneous Eraser scans or
continued scheduling with one node unavailable.

Release one change at a time and verify login, checkout, all three outbox
flows, dashboards and GitOps reconciliation. Qualify startup and at least
30 minutes of representative load without OOM, eviction or memory Pending.
Use current metrics to revise budgets if necessary; no JVM or API tuning is
part of this change. Revert the relevant AKS values/CR owner to roll back a
resource-only change. Kafka Connect consolidation requires its offset-safe
migration/rollback procedure before changing worker topology.
