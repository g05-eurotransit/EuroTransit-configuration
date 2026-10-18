# Platform procedures

Choose the environment in [deployment](deployment.md), then follow its bootstrap procedure. These pages own Kubernetes configuration and operations; service behavior and contracts remain in the application repository.

| Task | Reference |
| --- | --- |
| Start local Kubernetes | [Kind setup](kind-local-setup.md) |
| Run the isolated HA profile and fault gates | [Kind HA runbook](../reliability/kind-ha-runbook.md) |
| Bootstrap private-repository GitOps | [Argo CD](argocd-bootstrap.md), [Kind secrets](kind-gitops-secrets-runbook.md) |
| Provision and operate AKS | [Production setup](aks-production-setup.md), [bootstrap sequence](cluster-bootstrap-runbook.md) |
| Size constrained AKS | [Resource budgets](aks-resource-budgets.md), [memory reduction](aks-memory-reduction-runbook.md), [verification](aks-memory-verification.md) |
| Configure identity and public access | [OIDC](keycloak-oidc.md), [networking](networking-and-ingress.md), [secrets](security-and-secrets.md) |
| Recover identity/TLS controllers | [Recovery procedure](aks-keycloak-cert-manager-recovery.md) |
| Operate CDC and durable state | [Connector lifecycle](debezium-connector-lifecycle.md), [Inventory reset](inventory-bootstrap-and-reset.md), [dead letters](kafka-dead-letter-operations.md) |
| Inspect metrics and alert delivery | [Observability](observability.md) |
