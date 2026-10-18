# AKS capacity and resource budgets

Qualify startup, ordinary load and rollout overlap against actual per-node capacity. Scheduling requests, working-set usage and memory limits answer different questions; aggregate headroom cannot prove that an individual Pod fits. AKS is constrained and single-instance, as described in [deployment](deployment.md).

## Authoritative resource inputs

| Owner | Resource source |
| --- | --- |
| Application services and frontend | [Production values](../../charts/eurotransit/values-production.yaml) |
| Argo CD, cert-manager and Sealed Secrets | [Argo](../../platform/argocd/values-aks.yaml), [cert-manager](../../platform/cert-manager/values-aks.yaml), [Sealed Secrets](../../platform/sealed-secrets/values-aks.yaml) |
| PostgreSQL and operator | [Cluster patch](../../platform/environments/aks/postgres-patch.yaml), [operator values](../../platform/cloudnativepg/values-aks.yaml) |
| Kafka and Connect | [Node pool](../../platform/environments/aks/kafka-nodepool-patch.yaml), [Kafka patch](../../platform/environments/aks/kafka-patch.yaml), [Connect patch](../../platform/connectors/environments/aks/connect-patch.yaml) |
| Keycloak and operator | [Instance](../../platform/keycloak/keycloak.yaml), [vendored operator overlay](../../platform/keycloak-operator/README.md) |
| Monitoring, Strimzi and ingress | [Monitoring](../../platform/kube-prometheus-stack/values-aks.yaml), [Strimzi](../../platform/strimzi/values-aks.yaml), [Traefik](../../platform/traefik/values-aks.yaml) |

Render those owners with the pinned chart versions before calculating totals. Bootstrap releases need both shared and AKS values. Do not patch generated Pods/Deployments instead of their persistent owner. The [capacity verification](../verification/aks/capacity.md) records its baseline revision and observed inventory; its old aggregate estimates are not current free capacity.

## Qualification

1. Capture node allocatable capacity, managed/project Pod requests, usage, init containers, temporary Jobs, image-cleaner scans and the planned stable/canary overlap.
2. Evaluate placement, affinity, taints and volume topology on every node. Allocatable already excludes kube/system reservations; subtract managed Pod requests only once.
3. Apply one reviewed component change at a time with [controlled GitOps maintenance](../operations/gitops.md#controlled-maintenance). Preserve CPU/JVM settings unless separately reviewed.
4. Verify Argo and Keycloak login, checkout, all three outbox flows, dashboards and alerts. Qualify cold startup and at least 30 minutes of representative load without OOM, eviction or memory Pending.
5. Roll back resource-only changes through their values/CR owner. Connector topology uses its [offset-safe rollback](../operations/connect-migration.md#rollback). Check [Kafka storage](../operations/aks.md#kafka-storage-before-maintenance) before a broker restart.

The application-controller limit was increased after OOMs at lower limits; a larger limit does not create scheduling headroom. Do not infer failed-node capacity from healthy applications or a zero-size scan sample.

## Operator-generated work

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
