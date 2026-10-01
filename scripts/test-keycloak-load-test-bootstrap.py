#!/usr/bin/env python3
"""Exercise the actual Job script against an isolated Keycloak (Docker + PyYAML)."""

import base64
import json
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import yaml


ROOT = Path(__file__).resolve().parents[1]
JOB = yaml.safe_load((ROOT / "platform/keycloak/load-test-client-secret-bootstrap-job.yaml").read_text())
CONTAINER = JOB["spec"]["template"]["spec"]["containers"][0]
REALM = yaml.safe_load((ROOT / "platform/keycloak/eurotransit-realm.yaml").read_text())["spec"]["realm"]
EXPECTED = next(c for c in REALM["clients"] if c["clientId"] == "eurotransit-load-test")


def docker(*args):
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Docker {args[0]} timed out") from None
    if result.returncode:
        # Do not render command arguments, environment values or container output.
        raise RuntimeError(f"Docker {args[0]} failed")
    return result.stdout.strip()


def request(url, data=None, token=None, method=None, form=False):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        data = (urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data, headers, method=method), timeout=5) as response:
        payload = response.read()
        return json.loads(payload) if payload else None


def main():
    name = f"eurotransit-kc-bootstrap-test-{uuid.uuid4().hex[:10]}"
    server, runner = f"{name}-server", f"{name}-runner"
    admin_password, client_secret = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    process = None
    try:
        docker("network", "create", name)
        # Run the unmodified Job script before the server or realm exists.
        process = subprocess.Popen([
            "docker", "run", "--rm", "-i", "--name", runner, "--network", name,
            "-e", "KEYCLOAK_ADMIN_USERNAME=admin", "-e", f"KEYCLOAK_ADMIN_PASSWORD={admin_password}",
            "-e", f"LOAD_TEST_CLIENT_SECRET={client_secret}", "--entrypoint", "/bin/sh",
            CONTAINER["image"], "-ceu", CONTAINER["args"][0],
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(6)
        assert process.poll() is None, "Bootstrap must retry while Keycloak is unavailable"
        docker("run", "-d", "--name", server, "--network", name,
               "--network-alias", "keycloak-service", "-p", "127.0.0.1::8080",
               "-e", "KC_BOOTSTRAP_ADMIN_USERNAME=admin", "-e", f"KC_BOOTSTRAP_ADMIN_PASSWORD={admin_password}",
               CONTAINER["image"], "start-dev")
        port = docker("inspect", "--format", '{{(index (index .NetworkSettings.Ports "8080/tcp") 0).HostPort}}', server)
        base = f"http://127.0.0.1:{port}"
        admin_token = None
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                admin_token = request(f"{base}/realms/master/protocol/openid-connect/token", {
                    "grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": admin_password,
                }, form=True)["access_token"]
                break
            except (urllib.error.URLError, OSError):
                time.sleep(1)
        assert admin_token, "Isolated Keycloak did not become ready"
        time.sleep(6)
        assert process.poll() is None, "Bootstrap must retry while the realm is absent"

        def api(path, data=None, method=None):
            nonlocal admin_token
            # Master-realm admin tokens are short-lived; test runs can outlast one.
            admin_token = request(f"{base}/realms/master/protocol/openid-connect/token", {
                "grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": admin_password,
            }, form=True)["access_token"]
            return request(f"{base}/admin/realms/{path}", data, token=admin_token, method=method)

        api("", {"realm": "eurotransit", "enabled": True, "sslRequired": "none", "roles": REALM["roles"]})

        def finish_bootstrap(active, expect_retry=False):
            try:
                output, errors = active.communicate(timeout=JOB["spec"]["activeDeadlineSeconds"])
            except subprocess.TimeoutExpired:
                raise RuntimeError("Bootstrap exceeded the Job deadline") from None
            assert all(value not in output + errors for value in (admin_password, client_secret, admin_token)), "Credential in logs"
            assert active.returncode == 0, "Bootstrap failed (credential-bearing diagnostics suppressed)"
            assert "Reconciled eurotransit-load-test" in output
            if expect_retry:
                assert "retrying" in errors

        def rerun():
            active = subprocess.Popen([
                "docker", "run", "--rm", "--name", runner, "--network", name,
                "-e", "KEYCLOAK_ADMIN_USERNAME=admin", "-e", f"KEYCLOAK_ADMIN_PASSWORD={admin_password}",
                "-e", f"LOAD_TEST_CLIENT_SECRET={client_secret}", "--entrypoint", "/bin/sh",
                CONTAINER["image"], "-ceu", CONTAINER["args"][0],
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                finish_bootstrap(active)
            finally:
                if active.poll() is None:
                    active.kill()
                    active.wait()

        def verify():
            clients = api("eurotransit/clients?clientId=eurotransit-load-test")
            assert len(clients) == 1, "Exactly one load-test client must exist"
            client = clients[0]
            for field, value in EXPECTED.items():
                if field != "protocolMappers":
                    assert client.get(field) == value, f"Incorrect client field: {field}"
            assert client["clientAuthenticatorType"] == "client-secret"
            client_id = client["id"]
            assert api(f"eurotransit/clients/{client_id}/client-secret")["value"] == client_secret, "Incorrect client secret"
            mappers = api(f"eurotransit/clients/{client_id}/protocol-mappers/models")
            roles_mappers = [m for m in mappers if m["name"] == "realm roles"]
            assert len(roles_mappers) == 1, "Exactly one realm roles mapper must exist"
            mapper = roles_mappers[0]
            for field, value in EXPECTED["protocolMappers"][0].items():
                if field == "config":
                    # Keycloak can add default mapper settings to the representation.
                    for key, expected in value.items():
                        assert mapper["config"].get(key) == expected, f"Incorrect mapper config: {key}"
                else:
                    assert mapper.get(field) == value, f"Incorrect mapper field: {field}"
            account = api(f"eurotransit/clients/{client_id}/service-account-user")
            roles = api(f'eurotransit/users/{account["id"]}/role-mappings/realm')
            assert "customer" in {r["name"] for r in roles}, "Service account must have customer role"
            response = request(f"{base}/realms/eurotransit/protocol/openid-connect/token", {
                "grant_type": "client_credentials", "client_id": "eurotransit-load-test", "client_secret": client_secret,
            }, form=True)
            payload = response["access_token"].split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            assert "customer" in claims.get("realm_access", {}).get("roles", []), "Token must contain customer role"
            assert claims["azp"] == "eurotransit-load-test"
            return client_id, mapper["id"], account["id"]

        finish_bootstrap(process, expect_retry=True)
        original_ids = verify()
        print("PASS: server/realm unavailable, absent client created, customer token issued", flush=True)

        rerun()
        assert verify() == original_ids, "Second run must preserve client, mapper and service account IDs"
        print("PASS: second run preserves IDs without duplicate clients or mappers", flush=True)

        client_id, mapper_id, account_id = original_ids
        customer = next(r for r in api(f"eurotransit/users/{account_id}/role-mappings/realm") if r["name"] == "customer")
        api(f"eurotransit/users/{account_id}/role-mappings/realm", [customer], "DELETE")
        api(f"eurotransit/clients/{client_id}", {
            "publicClient": True, "serviceAccountsEnabled": False, "standardFlowEnabled": True,
            "directAccessGrantsEnabled": True, "implicitFlowEnabled": True, "enabled": False,
            "fullScopeAllowed": False, "clientAuthenticatorType": "client-jwt", "name": "incomplete",
        }, "PUT")
        api(f"eurotransit/clients/{client_id}/protocol-mappers/models/{mapper_id}", {
            "id": mapper_id, "name": "realm roles", "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-realm-role-mapper",
            "config": {"claim.name": "incorrect_roles", "access.token.claim": "false"},
        }, "PUT")
        api(f"eurotransit/clients/{client_id}/protocol-mappers/models", {
            "name": "realm roles extra", "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-realm-role-mapper", "config": {"claim.name": "unrelated_roles"},
        })
        rerun()
        # Keycloak deletes the service-account user when that capability is
        # disabled; repairing it creates a new user but preserves client/mapper IDs.
        assert verify()[:2] == original_ids[:2], "Repair must preserve client and mapper IDs"
        assert any(m["name"] == "realm roles extra" and m["config"]["claim.name"] == "unrelated_roles"
                   for m in api(f"eurotransit/clients/{client_id}/protocol-mappers/models")), "Unrelated mapper changed"
        print("PASS: existing incomplete client/mapper/role repaired; unrelated mapper preserved", flush=True)
    finally:
        for container in (runner, server):
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        subprocess.run(["docker", "network", "rm", name], capture_output=True, timeout=30)


if __name__ == "__main__":
    main()
