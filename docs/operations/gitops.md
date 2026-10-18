# Bootstrap and maintain GitOps

Install Argo CD, provide a read-only private-repository credential and apply one root Application. The root then reconciles child applications in the [configured order](../platform/gitops.md). Independent child applies bypass that ordering.

## Prerequisites

For AKS, complete [controller and ciphertext bootstrap](aks.md#controller-and-application-secrets) first. For optional GitOps on Kind, prepare the local images/runtime with [Kind setup](kind.md), then install Sealed Secrets if testing encrypted runtime secrets. Direct Kind setup alone is not GitOps proof.

Argo's dedicated GitHub token needs read-only Contents access to configuration. It is separate from CI's configuration-write credential. Do not print tokens, enable shell tracing or commit decrypted Secrets.

## Install Argo CD

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade --install argocd argo/argo-cd --version 10.2.2   --namespace argocd --create-namespace   -f platform/argocd/values.yaml -f platform/argocd/values-aks.yaml
kubectl -n argocd rollout status deployment/argocd-server --timeout=5m
```

The command selects AKS values. For Kind use the shared values without `values-aks.yaml`. Select the intended kubectl/Helm context before either path.

## Repository credential

On AKS manually apply the controller-bound bootstrap SealedSecret after its original controller keys are available:

```bash
kubectl apply -f platform/argocd/bootstrap/aks/eurotransit-configuration-repo.sealedsecret.yaml
kubectl -n argocd wait --for=condition=Synced   sealedsecret/eurotransit-configuration-repo --timeout=60s
```

This credential is outside Argo-managed kustomizations. Same-cluster ciphertext can be reused from another workstation; a new controller needs original keys restored or freshly sealed credentials. Expired/revoked tokens need replacement regardless of available keys.

For disposable Kind, create the bootstrap Secret directly without a plaintext file:

```bash
read -rp 'GitHub username: ' ARGO_REPO_USERNAME
read -rsp 'Read-only repository token: ' ARGO_REPO_TOKEN; echo
kubectl -n argocd create secret generic eurotransit-configuration-repo   --from-literal=type=git   --from-literal=url=https://github.com/g05-eurotransit/EuroTransit-configuration.git   --from-literal=username="$ARGO_REPO_USERNAME"   --from-literal=password="$ARGO_REPO_TOKEN" --dry-run=client -o yaml | kubectl label --local -f - argocd.argoproj.io/secret-type=repository -o yaml | kubectl apply -f -
unset ARGO_REPO_USERNAME ARGO_REPO_TOKEN
```

Verify `argocd repo list` reports `Successful` before root creation.

## Reconcile the root

```bash
kubectl apply -k apps/argocd-apps/environments/aks
argocd app wait eurotransit-platform-root --sync --health --timeout 1800
kubectl -n argocd get applications
```

For Kind select `apps/argocd-apps/environments/kind`. Do not apply the child overlay directly. Inspect failed child health with `argocd app get`; require both Connect custom-resource readiness and actual RUNNING tasks.

To verify self-heal in a disposable acceptance cluster, record `argocd app diff`, introduce reversible drift in a non-stateful workload and verify restoration. Do not use Secrets, databases or volumes for drift tests. Kind cannot qualify Azure identity, ACR pull access, public DNS/TLS or AKS storage behavior.

## Optional sealed runtime Secrets on Kind

This is a separate extension to direct Kind setup, not a default bootstrap requirement. Seal only disposable values for the actual Kind controller and validate them before applying. Keep environment-specific ciphertext in a Kind-only overlay; never add it to the shared CloudNativePG base used by AKS. [Security and secrets](../platform/security-and-secrets.md) owns names, scopes and rotation boundaries.

Apply the reviewed overlay through the selected runtime Application and verify each SealedSecret becomes Synced and produces the expected Secret type/keys. A YAML file outside a kustomization is not reconciled. A different controller certificate cannot decrypt existing ciphertext.

## Repository credential rotation

Create the replacement read-only token before revoking the old one. For AKS fetch the target public certificate after key backup, seal the replacement and apply it manually:

```bash
read -rp 'GitHub username: ' ARGO_REPO_USERNAME
read -rsp 'Read-only repository token: ' ARGO_REPO_TOKEN; echo
printf 'type=git\nurl=https://github.com/g05-eurotransit/EuroTransit-configuration.git\nusername=%s\npassword=%s\n' "$ARGO_REPO_USERNAME" "$ARGO_REPO_TOKEN" | kubectl -n argocd create secret generic eurotransit-configuration-repo     --from-env-file=/dev/stdin --dry-run=client -o yaml | kubectl label --local -f - argocd.argoproj.io/secret-type=repository -o yaml | kubeseal --cert /tmp/eurotransit-sealed-secrets.pem --scope strict --format yaml > platform/argocd/bootstrap/aks/eurotransit-configuration-repo.sealedsecret.yaml
unset ARGO_REPO_USERNAME ARGO_REPO_TOKEN
kubeseal --controller-name sealed-secrets-controller --controller-namespace sealed-secrets   --validate < platform/argocd/bootstrap/aks/eurotransit-configuration-repo.sealedsecret.yaml
kubectl apply -f platform/argocd/bootstrap/aks/eurotransit-configuration-repo.sealedsecret.yaml
kubectl -n argocd wait --for=condition=Synced   sealedsecret/eurotransit-configuration-repo --timeout=60s
kubectl -n argocd annotate application eurotransit-platform-root   argocd.argoproj.io/refresh=hard --overwrite
argocd repo list
```

Require successful access/root refresh before revoking the previous token. Review and commit only replacement ciphertext. For Kind replace the disposable repository Secret with the same direct creation procedure.

## Controlled maintenance

Before a desired-state change that needs ordered data migration, save the root/affected child sources and sync policies. Suspend automated sync on the root and affected children, terminate or wait for in-flight operations, suspend external sync automation and pin every affected Git/value source to the known pre-change revision. Keep chart versions fixed. Do not sync the root while maintenance is in progress: it can restore child automation.

Apply reviewed stages individually, preserving a single resource owner and measuring actual overlap capacity. Do not auto-sync a final connector topology before [offset migration](connect-migration.md) completes. Pinning only Argo is insufficient when REST migration also requires Strimzi reconciliation paused.

At completion compare live owners with the reviewed final render, advance child sources, qualify sync/health and restore child policies before the root policy. Confirm `main` still matches the reviewed release. Roll back ordinary Argo-owned changes through a reviewed Git revert; state migrations require their own rollback procedure.
