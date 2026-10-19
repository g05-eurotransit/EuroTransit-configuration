# Recover the Keycloak load-test client

Use this procedure when an existing realm lacks or misconfigures `eurotransit-load-test`, or its ordinary bootstrap Job has failed. Realm import creates a realm once; recreating it is not the repair. The [OIDC reference](../platform/keycloak-oidc.md) owns identity configuration.

## Diagnose

Check PostgreSQL readiness first: discovery can respond while token authentication fails on an unavailable database. [AKS recovery](aks.md#postgresql-disk-recovery) covers storage exhaustion; [AKS acceptance](aks.md#acceptance-and-ordinary-rollback) covers TLS/webhook checks. Confirm both namespace copies of `eurotransit-load-test-credentials` exist with the same client-secret.

The bootstrap Job reconciles the confidential client, existing client ID/secret, service-account customer role and realm-role mapper. Interactive/password grants stay disabled. Its finite deadline does not authorize replacing the realm or logging credentials.

## Reconcile the reviewed Job

```bash
argocd app get eurotransit-keycloak --hard-refresh
argocd app manifests eurotransit-keycloak
```

Confirm desired manifests contain the reviewed bootstrap template. A completed or failed ordinary Job cannot adopt a changed Pod template; delete only that Job after the desired revision is visible:

```bash
kubectl -n keycloak delete job load-test-client-secret-bootstrap --ignore-not-found
```

If sync is running, wait; otherwise sync `eurotransit-keycloak`. Then require completion and Healthy/Synced:

```bash
argocd app wait eurotransit-keycloak --sync --health --timeout 900
kubectl -n keycloak get job load-test-client-secret-bootstrap
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

```

Require matching namespace Secrets, the expected client/customer claim, a completed Job and healthy identity reconciliation. This check does not create orders or start the suspended load CronJob. The executable local bootstrap regression is [test-keycloak-load-test-bootstrap.py](../../scripts/test-keycloak-load-test-bootstrap.py); a local test pass is not target-cluster recovery evidence.
