# EuroTransit Production Readiness

## Verdict

The repository is now **manifest-ready for constrained AKS deployment** and
can render both AKS and Kind profiles. It is not yet go-live verified because
cluster-specific secrets, image availability, DNS/TLS validation, and runtime
capacity measurements require the real AKS cluster.

## Completed In Configuration

- [x] AKS-specific Helm values and Kustomize runtime overlay.
- [x] Argo CD points to AKS production values rather than Kind values.
- [x] Argo CD has a root app-of-apps with child health and ordered sync waves.
- [x] Argo CD repository references use the private organization repository.
- [x] Public hostname is `g05.cpo2026.it`; placeholder production domains are removed.
- [x] Keycloak and APIs share one public hostname with a consistent OIDC issuer.
- [x] Keycloak uses the official Keycloak Operator `26.7.0`, not an abandoned
  Bitnami image dependency.
- [x] Application services have explicit requests, limits and one replica.
- [x] CloudNativePG and Strimzi use one-instance constrained topologies; Keycloak reuses CloudNativePG.
- [x] Traefik runs one replica and requests the assigned Azure DNS label.
- [x] Prometheus has reduced retention and memory limits.
- [x] Chaos Mesh is excluded from steady-state GitOps deployment.
- [x] Kind has repeatable setup, test, status, logs and teardown commands.
- [x] PDBs are disabled where a single replica would make eviction impossible.

## Required Before First AKS Sync

- [ ] Confirm `g05.cpo2026.it` resolves to `g05-eurotransit.swedencentral.cloudapp.azure.com`.
- [ ] Confirm immutable images exist in `eurotransitregistry.azurecr.io`.
- [ ] Confirm AKS can pull from ACR.
- [ ] Replace example SealedSecrets with values encrypted for the AKS controller.
- [ ] Confirm the Let's Encrypt account email is monitored.
- [ ] Provision Argo CD with a read-only credential for the private
  `g05-eurotransit/EuroTransit-configuration` repository.
- [ ] Merge and push the validated configuration revision before applying the
  AKS root Application.
- [ ] Create `keycloak-admin-credentials` and `keycloak-db-credentials` as
  SealedSecrets in namespace `keycloak`, plus `keycloak-db-credentials` in
  namespace `eurotransit`, all with `username` and `password` keys.

## Required Runtime Proof

- [ ] All Argo CD applications are Healthy and Synced.
- [ ] No pods remain Pending, CrashLoopBackOff or OOMKilled.
- [ ] `kubectl top` shows acceptable memory headroom on every node.
- [ ] The TLS certificate for `g05.cpo2026.it` is Ready.
- [ ] Keycloak discovery reports the exact configured issuer.
- [ ] Catalog is public and Orders rejects unauthenticated requests.
- [ ] Inventory and Payments remain internal-only.
- [ ] CloudNativePG, Kafka and Debezium reach Ready state.
- [ ] Prometheus discovers application ServiceMonitors and alert rules.
- [ ] A GitOps rollback has been exercised and recorded.

## Remaining Product And Operations Work

- The React frontend cannot be deployed because it does not exist as a workload
  in `EuroTransit-application` yet.
- Real Grafana dashboards, tracing collection, progressive delivery evidence,
  least-privilege RBAC and completed chaos reports remain follow-up work.
- The single-instance database, Kafka and Keycloak topology cannot tolerate a
  node or process failure. This is an accepted consequence of the fixed node
  size, not a hidden production claim.
