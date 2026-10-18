# Networking and ingress

Traefik exposes the frontend, Catalog, Orders and the enabled Notifications read/SSE API. Inventory and Payments have no public IngressRoute. Forward-auth is disabled in effective base values; service JWT checks remain active. The gateway-enforcement gap is tracked in [readiness](../delivery/readiness.md).

## Exposure and routing

| Endpoint | Exposure | Configuration |
| --- | --- | --- |
| Frontend and public APIs | Traefik routes to service ClusterIPs | [Application IngressRoutes](../../charts/eurotransit/templates/ingressroutes.yaml) |
| Inventory / Payments | Internal services; baseline NetworkPolicies | [Network policies](../../charts/eurotransit/templates/networkpolicies.yaml) |
| Keycloak discovery, login and tokens | Separate local host; shared public host/path on AKS | [OIDC setup](keycloak-oidc.md) |
| Argo CD UI | Platform administration endpoint | [Argo ingress](../../platform/traefik/argocd-ingressroute.yaml) |

[Traefik values](../../platform/traefik/values.yaml) configure the controller; [middleware templates](../../charts/eurotransit/templates/traefik-middlewares.yaml) configure route behavior. The [deployment comparison](deployment.md) owns environment hosts, TLS issuers and ingress service types. Namespace placement alone is not proof of network isolation.

Protected endpoint identities, roles, ownership and correlation semantics are defined by the application [API contract](https://github.com/g05-eurotransit/EuroTransit-application/blob/dev/docs/design/api-design.md) and [observability conventions](https://github.com/g05-eurotransit/EuroTransit-application/blob/dev/docs/design/observability-conventions.md). Verify public reads, unauthenticated rejection and internal-route absence through the [smoke procedure](../delivery/kind-smoke-e2e.md).
