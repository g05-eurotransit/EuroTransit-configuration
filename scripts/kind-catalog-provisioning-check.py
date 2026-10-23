#!/usr/bin/env python3
"""Test the rendered startup gate and CNPG Database reconciliation on Kind only."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('catalog_check', Path(__file__).with_name('kind-catalog-check.py'))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def wait(check, message, seconds=90):
    deadline = time.monotonic() + seconds
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise AssertionError(message)
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    manifests = list(yaml.safe_load_all(subprocess.check_output(['helm', 'template', 'eurotransit', str(ROOT / 'charts/eurotransit'),
        '-f', str(ROOT / 'charts/eurotransit/values-kind-ha.yaml'), '--set', 'catalog.storage=postgres'], text=True)))
    deployment = next(x for x in manifests if x and x['kind'] == 'Deployment' and x['metadata']['name'] == 'catalog')
    gate = deployment['spec']['template']['spec']['initContainers'][0]
    run = 'catalog-gate-' + uuid.uuid4().hex[:8]
    resources = []
    proof = {'context': c.h.CONTEXT, 'startedAt': c.h.now(), 'cases': {}}

    def create(document):
        kind, name = document['kind'], document['metadata']['name']
        c.h.k('create', '-f', '-', data=json.dumps(document))
        resources.append((kind.lower(), name))
        return name

    def database(name, owner):
        return {'apiVersion': 'postgresql.cnpg.io/v1', 'kind': 'Database', 'metadata': {'name': name},
                'spec': {'name': name.replace('-', '_'), 'owner': owner, 'cluster': {'name': 'eurotransit-postgres'},
                         'ensure': 'present', 'databaseReclaimPolicy': 'delete'}}

    def pod(name, db, budget=180):
        init = copy.deepcopy(gate)
        for e in init['env']:
            if e['name'] == 'PGDATABASE':
                e['value'] = db
            if e['name'] == 'CATALOG_DATABASE_WAIT_SECONDS':
                e['value'] = str(budget)
        main = {k: copy.deepcopy(init[k]) for k in ('image', 'env', 'resources', 'securityContext')}
        main.update(name='verified', command=['/bin/sh', '-ec'], args=[
            "psql -X -qAt --no-password --set=ON_ERROR_STOP=1 -c \"SELECT current_user,pg_get_userbyid(datdba),has_database_privilege('orders',current_database(),'CONNECT') FROM pg_database WHERE datname=current_database();\""])
        return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name}, 'spec': {
            'restartPolicy': 'Never', 'activeDeadlineSeconds': 220, 'automountServiceAccountToken': False,
            'initContainers': [init], 'containers': [main]}}

    def applied(name):
        obj = c.h.obj('database', name)
        return obj.get('status', {}).get('applied') and obj['status'].get('observedGeneration') == obj['metadata']['generation']

    def phase(name, expected):
        obj = c.h.obj('pod', name)
        if expected == 'Succeeded':
            assert obj['status']['phase'] != 'Failed', 'Gate success probe failed'
        return obj['status']['phase'] == expected

    try:
        pending = run + '-pending'
        dbname = pending.replace('-', '_')
        create(pod(pending, dbname))
        def blocked():
            state = c.h.obj('pod', pending)['status']
            return any(v.get('state', {}).get('running') for v in state.get('initContainerStatuses', []))
        wait(blocked, 'Startup gate did not start')
        wait(lambda: 'Waiting for the dedicated' in c.h.k('logs', pending, '-c', 'catalog-database-ready'), 'Gate did not wait for the missing database')
        state = c.h.obj('pod', pending)['status']
        assert any(v['type'] == 'Initialized' and v['status'] == 'False' for v in state['conditions'])
        assert len(c.h.request(c.h.BASE + '/api/catalog/routes')) == 5
        proof['cases']['missingDatabaseBlocksStartup'] = True
        create(database(pending, 'catalog'))
        wait(lambda: applied(pending), 'Database was not reconciled')
        wait(lambda: phase(pending, 'Succeeded'), 'Gate did not unblock after database creation')
        assert c.h.k('logs', pending, '-c', 'verified').strip() == 'catalog|catalog|f'
        proof['cases']['controllerCreatesDatabaseAndUnblocksGate'] = True
        proof['cases']['gateRevokesPublicConnect'] = True

        timeout = run + '-timeout'
        create(pod(timeout, timeout.replace('-', '_'), budget=5))
        wait(lambda: phase(timeout, 'Failed'), 'Missing database did not fail within the bounded budget', 45)
        assert 'not ready within the startup budget' in c.h.k('logs', timeout, '-c', 'catalog-database-ready')
        proof['cases']['boundedFailure'] = True

        wrong = run + '-wrong-owner'
        create(database(wrong, 'orders'))
        wait(lambda: applied(wrong), 'Wrong-owner fixture was not reconciled')
        create(pod(wrong, wrong.replace('-', '_'), budget=5))
        wait(lambda: phase(wrong, 'Failed'), 'Non-owner was incorrectly accepted', 45)
        owner = c.sql('postgres', "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='" + wrong.replace('-', '_') + "';").strip()
        assert owner == 'orders'
        proof['cases']['wrongOwnerRejectedWithoutOwnershipChange'] = True

        before = c.sql('catalog_db', "SELECT (SELECT count(*) FROM offers),(SELECT count(*) FROM routes),(SELECT count(*) FROM flyway_schema_history WHERE success);").strip()
        production = yaml.safe_load((ROOT / 'platform/environments/aks/catalog-database.yaml').read_text())
        existing = c.h.k('get', 'database', 'catalog', '--ignore-not-found', '-o', 'json')
        if existing.strip():
            current = json.loads(existing)
            assert current['spec']['name'] == 'catalog_db' and current['spec']['owner'] == 'catalog'
        # Only this Database resource is applied to Kind; no AKS overlay is applied.
        c.h.k('apply', '-f', '-', data=json.dumps(production))
        wait(lambda: applied('catalog'), 'Existing Catalog database was not adopted')
        after = c.sql('catalog_db', "SELECT (SELECT count(*) FROM offers),(SELECT count(*) FROM routes),(SELECT count(*) FROM flyway_schema_history WHERE success);").strip()
        assert before == after == '6|5|2'
        proof['cases']['existingCatalogAdoptedWithoutReset'] = True
        proof['catalogCounts'] = {'offers': 6, 'routes': 5, 'migrations': 2}
        proof['passed'] = True
    finally:
        for kind, name in reversed(resources):
            c.h.k('delete', kind, name, '--ignore-not-found', '--wait=false')
        # Only generated fixture database names are checked; Catalog itself is retained.
        def cleaned():
            return c.sql('postgres', "SELECT count(*) FROM pg_database WHERE datname LIKE '" + run.replace('-', '_') + "_%';").strip() == '0'
        wait(cleaned, 'Temporary databases were not reclaimed', 60)
        proof['temporaryResourcesDeleted'] = True
        proof['finishedAt'] = c.h.now()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof))


if __name__ == '__main__':
    main()
