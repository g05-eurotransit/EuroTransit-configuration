# AKS Keycloak bootstrap and cert-manager recovery

An older `eurotransit` realm can lack `eurotransit-load-test`: Keycloak's
[realm import](https://www.keycloak.org/operator/realm-import) creates a realm
but does not update one that already exists. The ordinary
`load-test-client-secret-bootstrap` Job now creates the absent client or
updates it without replacing its ID. It applies the existing Kubernetes
client secret, disables interactive and password grants, enables its service
account, reconciles the `realm roles` mapper and grants `customer`.

The Job retries authentication, realm availability and reconciliation failures,
with its existing 600-second active deadline. API lookup failures do not count
as missing objects. CLI output is suppressed to keep credentials out of logs.

The AKS cert-manager values explicitly retain the standard
`cert-manager.io/disable-validation NotIn ["true"]` namespace filter and add
`control-plane NotIn ["true"]` and
`kubernetes.azure.com/managedby NotIn ["aks"]`. The
[v1.18.2 chart](https://github.com/cert-manager/cert-manager/blob/v1.18.2/deploy/charts/cert-manager/values.yaml)
supports these values under `webhook.validatingWebhookConfiguration.namespaceSelector`.
Only the validating webhook selector changes; Argo diff checks stay enabled.

## Local verification

From the configuration checkout, run:

```bash
scripts/render.sh kind
scripts/render.sh aks
git diff --check
python3 scripts/test-keycloak-load-test-bootstrap.py
```

The integration test needs Docker, Python 3 and PyYAML, and the Job's Keycloak
image (`quay.io/keycloak/keycloak:26.7.0`). It creates temporary containers and a
private Docker network, binds its HTTP port to localhost, and removes its own
containers/network afterwards. It executes the actual YAML Job script with
Keycloak initially unavailable, then with the realm absent; creates the client;
checks a second execution; and repairs an existing incomplete client, mapper
and service-account role mapping. It verifies the client secret and
`client_credentials` token's `customer` claim in memory, preserves object IDs
and an unrelated mapper, and prints neither credentials nor tokens.

To check the cert-manager diff, download the pinned chart and render before
and after with identical base values:

```bash
verification_dir="$(mktemp -d)"
helm pull cert-manager --repo https://charts.jetstack.io --version v1.18.2 \
  --untar --untardir "$verification_dir"
git show 7e4a146:platform/cert-manager/values-aks.yaml > "$verification_dir/values-aks-before.yaml"
helm template cert-manager "$verification_dir/cert-manager" \
  --namespace cert-manager --include-crds \
  -f platform/cert-manager/values.yaml -f "$verification_dir/values-aks-before.yaml" \
  > "$verification_dir/before.yaml"
helm template cert-manager "$verification_dir/cert-manager" \
  --namespace cert-manager --include-crds \
  -f platform/cert-manager/values.yaml -f platform/cert-manager/values-aks.yaml \
  > "$verification_dir/after.yaml"
diff -u "$verification_dir/before.yaml" "$verification_dir/after.yaml"
```

The expected diff adds only the two AKS match expressions to
`ValidatingWebhookConfiguration/cert-manager-webhook`, preserving the standard
filter. `diff` exits with status 1 for this expected change.

## Publication and rollout

Push and merge are manual, with human review before merging. Do not apply the
new Job directly or recreate the realm. After the reviewed commit is merged
into `main`, an operator with the AKS kubectl context and Argo CLI session runs:

```bash
argocd app get eurotransit-keycloak --hard-refresh
argocd app manifests eurotransit-keycloak
```

Confirm that Argo's desired manifests contain the merged bootstrap template
before deleting the old Job. The Pod template is immutable; deleting exactly
this failed Job lets Argo recreate it from Git:

```bash
kubectl -n keycloak delete job load-test-client-secret-bootstrap --ignore-not-found
```

Inspect `argocd app get eurotransit-keycloak`. If a sync is already running,
wait for it; otherwise start it with `argocd app sync eurotransit-keycloak`.
After Keycloak succeeds, synchronize cert-manager and then the root (if their
automatic syncs are already running, wait instead of submitting another):

```bash
argocd app wait eurotransit-keycloak --sync --health --timeout 900
kubectl -n keycloak get job load-test-client-secret-bootstrap

# Run sync only if the Application has no operation already in progress.
argocd app sync cert-manager
argocd app wait cert-manager --sync --health --timeout 900
argocd app sync eurotransit-platform-root
argocd app wait eurotransit-platform-root --sync --health --timeout 900
```

## Acceptance without checkout traffic

This check reads the two existing namespace copies of the client secret,
requires them to match, and requests only a client-credentials token over TLS.
It decodes the claim from the token returned by Keycloak and prints only the
result; it does not call any application API or start the suspended k6 CronJob.
Run without shell tracing or HTTP debug logging:

```bash
python3 - <<'PY'
import base64
import json
import subprocess
import urllib.parse
import urllib.request

def client_secret(namespace):
    result = subprocess.run([
        "kubectl", "-n", namespace, "get", "secret", "eurotransit-load-test-credentials",
        "-o", "jsonpath={.data.client-secret}",
    ], capture_output=True, text=True, check=True)
    return base64.b64decode(result.stdout, validate=True).decode()

secret = client_secret("eurotransit")
if not secret or secret != client_secret("keycloak"):
    raise SystemExit("FAIL: namespace client secrets are empty or differ")
form = urllib.parse.urlencode({
    "grant_type": "client_credentials", "client_id": "eurotransit-load-test", "client_secret": secret,
}).encode()
request = urllib.request.Request(
    "https://g05.cpo2026.it/realms/eurotransit/protocol/openid-connect/token", form,
    {"Content-Type": "application/x-www-form-urlencoded"},
)
with urllib.request.urlopen(request, timeout=20) as response:
    token = json.load(response)["access_token"]
payload = token.split(".")[1]
claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
if claims.get("azp") != "eurotransit-load-test" or "customer" not in claims.get("realm_access", {}).get("roles", []):
    raise SystemExit("FAIL: client identity or customer role missing")
print("PASS: matching secrets, client_credentials token and customer role")
PY

kubectl -n argocd get applications eurotransit-keycloak cert-manager eurotransit-platform-root \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status
kubectl get validatingwebhookconfiguration cert-manager-webhook \
  -o jsonpath='{.webhooks[0].namespaceSelector.matchExpressions}{"\n"}'
argocd app diff cert-manager --hard-refresh
```

Acceptance requires all three Applications to be `Synced / Healthy`, the
bootstrap Job to have completed, the token check to pass, the webhook to
contain all three expressions, and `argocd app diff cert-manager` to show no
differences. Until the merge and these AKS checks are complete, local test
success is not proof of recovery on AKS.
