# Argo CD Bootstrap

Argo CD reconciles EuroTransit from the private
`g05-eurotransit/EuroTransit-configuration` repository. The bootstrap keeps the
minimum unavoidable imperative boundary explicit: install Argo CD, provide its
read-only repository credential, and apply one root Application. Everything
below the root is then reconciled declaratively.

## Application hierarchy

```text
eurotransit-platform-root
└── platform/argocd/environments/<environment>
    └── platform/argocd/base
        ├── eurotransit-platform AppProject
        ├── eurotransit-secrets                 wave 5
        ├── platform operators                  wave 10
        ├── keycloak-operator                   wave 15
        ├── eurotransit-platform-runtime        wave 20
        ├── eurotransit-keycloak                wave 25
        ├── eurotransit-marketplace             wave 30
        └── eurotransit-connectors              wave 40
```

The root Application has a shared base under `apps/argocd-apps/base`. The AKS
and Kind entry points are `apps/argocd-apps/environments/aks` and
`apps/argocd-apps/environments/kind`; the Kind overlay selects Kind values and
paths and omits the optional monitoring stack.
Both use the built-in `default` project because the root creates the
`eurotransit-platform` AppProject as part of its first sync.

The Sealed Secrets controller itself is cluster-admin bootstrap infrastructure,
not an Argo Application. `eurotransit-secrets` owns only cluster-specific
application SealedSecrets; the private repository credential is versioned as
ciphertext under `platform/argocd/bootstrap/aks` and applied manually before
root creation, outside the Argo-managed resources. The child `Application`
health customization in `platform/argocd/values.yaml`
makes the root wait for each child to become healthy before advancing to a
later wave. The `KafkaConnect` and `KafkaConnector` customizations propagate
connector failures through the child and root Application health.

## 1. Install Argo CD

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade --install argocd argo/argo-cd --version 10.2.2 \
  --namespace argocd --create-namespace \
  -f platform/argocd/values.yaml \
  -f platform/argocd/values-aks.yaml
kubectl -n argocd rollout status deployment/argocd-server --timeout=5m
```

## 2. Provide the private repository credential

Use a dedicated fine-grained GitHub token scoped only to
`EuroTransit-configuration` with read-only repository contents. Do not reuse
the write token used by the application image workflow.

For an ephemeral Kind acceptance cluster, create the bootstrap Secret directly
without writing the token to disk:

```bash
read -rp "GitHub username: " ARGO_REPO_USERNAME
read -rsp "Argo repository token: " ARGO_REPO_TOKEN
echo

kubectl -n argocd create secret generic eurotransit-configuration-repo \
  --from-literal=type=git \
  --from-literal=url=https://github.com/g05-eurotransit/EuroTransit-configuration.git \
  --from-literal=username="$ARGO_REPO_USERNAME" \
  --from-literal=password="$ARGO_REPO_TOKEN" \
  --dry-run=client -o yaml \
| kubectl apply -f -

kubectl -n argocd label secret eurotransit-configuration-repo \
  argocd.argoproj.io/secret-type=repository \
  --overwrite

unset ARGO_REPO_USERNAME ARGO_REPO_TOKEN
```

For AKS, manually apply the committed
`platform/argocd/bootstrap/aks/eurotransit-configuration-repo.sealedsecret.yaml`
after the Sealed Secrets controller and required original keys are available.
A new PC can clone the repository with its own GitHub access and reuse this
ciphertext on the same cluster. For a new controller without the original keys,
or an expired/revoked token, seal a replacement with the target certificate
and apply it manually; commit only the replacement ciphertext. The template
in `platform/argocd/templates` documents the expected structure. Kind and AKS
encrypted payloads are not interchangeable. No plaintext
token belongs in Git, shell history, CI logs, or a values file.
The exact AKS ordering, including the controller and bootstrap runtime Secrets,
is documented in [AKS production bootstrap](aks-production-setup.md).

Verify access before creating the root:

```bash
argocd repo list
```

The repository must report `Successful`.

## 3. Apply the root Application

For AKS:

```bash
kubectl apply -k apps/argocd-apps/environments/aks
argocd app wait eurotransit-platform-root \
  --sync --health --timeout 1800
```

For Kind, first build and load all local application and connector images and
create the disposable runtime Secrets required by the workloads. Then apply
the environment-specific root:

```bash
kubectl apply -k apps/argocd-apps/environments/kind
argocd app wait eurotransit-platform-root \
  --sync --health --timeout 1800
```

Do not apply `platform/argocd/base` or an environment overlay directly during
the normal bootstrap. Doing so would create every child Application at once
and bypass the root's wave ordering.

Inspect the hierarchy and any failed child:

```bash
argocd app get eurotransit-platform-root
kubectl -n argocd get applications
kubectl -n argocd get applications \
  -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status'
```

## 4. Validate reconciliation before AKS

Static validation remains mandatory:

```bash
just render-kind
just render-aks
kubectl kustomize platform/argocd/environments/aks >/dev/null
kubectl kustomize platform/argocd/environments/kind >/dev/null
```

An Argo-on-Kind acceptance run additionally validates repository access,
multi-source Helm rendering, child health, sync waves, pruning and self-heal.
The standard `kind-up` path intentionally installs resources directly and does
not constitute this GitOps proof.

After all Applications are healthy, introduce reversible drift in a workload
owned by Argo and confirm that self-heal restores the Git value. Use
`argocd app diff` before and after the test. Never perform a drift test on a
Secret, database, persistent volume or production cluster.

Kind cannot validate Azure identity, ACR authorization, Azure LoadBalancer,
public DNS/TLS, Azure networking or AKS storage behavior. Those checks remain
part of the AKS acceptance run.

## Credential rotation

Create the replacement GitHub token before revoking the current one. Update the
repository Secret, request a hard refresh, and verify `argocd repo list` plus a
root refresh before revocation:

```bash
kubectl -n argocd annotate application eurotransit-platform-root \
  argocd.argoproj.io/refresh=hard --overwrite
argocd app get eurotransit-platform-root --refresh
```
