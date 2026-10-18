# Keycloak resources

Instance, realm, routes and identity/bootstrap Jobs live here. [OIDC configuration](../../docs/platform/keycloak-oidc.md) defines runtime inputs; [identity recovery](../../docs/operations/identity-recovery.md) covers failed or changed ordinary bootstrap Jobs. [AKS setup](../../docs/operations/aks.md) and [Kind setup](../../docs/operations/kind.md) own provisioning.

`KeycloakRealmImport` only creates the realm. The PostSync frontend-claims Job updates existing identity mappers; ordinary client-bootstrap Jobs reconcile confidential clients. Keep exact Job names and execution behavior in their manifests.
