#!/usr/bin/env python3
"""Provision Catalog's isolated database on an existing or new Kind CNPG cluster."""
import argparse
import base64
import json
import secrets
import subprocess
import time


def provision(context):
    if not context.startswith('kind-'):
        raise SystemExit('This procedure only accepts an explicit kind-* context.')

    def k(*args, data=None):
        result = subprocess.run(['kubectl', '--context', context, '--request-timeout=20s', '-n', 'eurotransit', *args],
                                input=data, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError('Kind provisioning command failed; sensitive diagnostics suppressed.')
        return result.stdout

    existing = k('get', 'secret', 'catalog-db-credentials', '--ignore-not-found', '-o', 'json')
    if existing.strip():
        secret = json.loads(existing)
        if base64.b64decode(secret['data']['username']).decode() != 'catalog':
            raise RuntimeError('Existing secret has an unexpected Catalog role; no credentials were changed.')
    else:
        secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'catalog-db-credentials'},
                  'type': 'Opaque', 'stringData': {'username': 'catalog', 'password': secrets.token_urlsafe(32)}}
        k('create', '-f', '-', data=json.dumps(secret))

    cluster = json.loads(k('get', 'cluster.postgresql.cnpg.io', 'eurotransit-postgres', '-o', 'json'))
    roles = cluster['spec'].get('managed', {}).get('roles', [])
    expected = {'name': 'catalog', 'ensure': 'present', 'login': True,
                'passwordSecret': {'name': 'catalog-db-credentials'}}
    found = next((role for role in roles if role['name'] == 'catalog'), None)
    if found is not None and any(found.get(key) != value for key, value in expected.items()):
        raise RuntimeError('Existing Catalog role differs; refusing to overwrite its configuration.')
    if found is None:
        # Resource-version precondition avoids overwriting concurrent role-management changes.
        patch = {'metadata': {'resourceVersion': cluster['metadata']['resourceVersion']},
                 'spec': {'managed': {'roles': [*roles, expected]}}}
        k('patch', 'cluster.postgresql.cnpg.io', 'eurotransit-postgres', '--type=merge', '-p', json.dumps(patch))

    def sql(query):
        current = json.loads(k('get', 'cluster.postgresql.cnpg.io', 'eurotransit-postgres', '-o', 'json'))
        return k('exec', '-i', current['status']['currentPrimary'], '-c', 'postgres', '--', 'psql', '-X', '-qAt',
                 '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-d', 'postgres', data=query)

    deadline = time.monotonic() + 90
    while sql("SELECT count(*) FROM pg_roles WHERE rolname='catalog' AND rolcanlogin;\n").strip() != '1':
        if time.monotonic() >= deadline:
            raise RuntimeError('Timed out waiting for CNPG to provision the Catalog role.')
        time.sleep(2)
    sql("SELECT 'CREATE DATABASE catalog_db OWNER catalog' WHERE NOT EXISTS "
        "(SELECT FROM pg_database WHERE datname='catalog_db')\\gexec\n")
    if sql("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='catalog_db';\n").strip() != 'catalog':
        raise RuntimeError('Existing catalog_db has an unexpected owner; no ownership was changed.')
    # Only Catalog may connect. Other service roles must not inherit PUBLIC access.
    sql('REVOKE CONNECT ON DATABASE catalog_db FROM PUBLIC;\n')
    print('Catalog database and dedicated credentials are ready; existing credentials were preserved.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    provision(parser.parse_args().context)
