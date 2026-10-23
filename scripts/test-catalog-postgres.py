#!/usr/bin/env python3
"""Check database wiring in both Catalog deployment modes."""
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class CatalogPostgresWiringTests(unittest.TestCase):
    def render(self, storage, progressive):
        return list(yaml.safe_load_all(subprocess.check_output([
            'helm', 'template', 'eurotransit', str(ROOT / 'charts/eurotransit'),
            '-f', str(ROOT / 'charts/eurotransit/values-kind-ha.yaml'),
            '--set', 'catalog.storage=' + storage,
            '--set', 'progressiveDelivery.enabled=' + str(progressive).lower(),
        ], text=True)))

    def test_storage_wiring_and_rollout_reference(self):
        for progressive in (False, True):
            for storage in ('in-memory', 'postgres'):
                with self.subTest(progressive=progressive, storage=storage):
                    docs = self.render(storage, progressive)
                    deployment = next(d for d in docs if d and d['kind'] == 'Deployment' and d['metadata']['name'] == 'catalog')
                    env = {e['name']: e for e in deployment['spec']['template']['spec']['containers'][0]['env']}
                    self.assertEqual(deployment['spec']['template']['spec']['topologySpreadConstraints'][0]['nodeTaintsPolicy'], 'Honor')
                    self.assertEqual(env['CATALOG_STORAGE']['value'], storage)
                    if storage == 'postgres':
                        gate = deployment['spec']['template']['spec']['initContainers'][0]
                        self.assertEqual(gate['name'], 'catalog-database-ready')
                        gate_env = {e['name']: e for e in gate['env']}
                        self.assertEqual(gate_env['PGUSER']['valueFrom']['secretKeyRef']['name'], 'catalog-db-credentials')
                        self.assertEqual(gate_env['PGPASSWORD']['valueFrom']['secretKeyRef']['key'], 'password')
                        self.assertEqual(gate_env['CATALOG_DATABASE_WAIT_SECONDS']['value'], '180')
                        self.assertTrue(gate['securityContext']['runAsNonRoot'])
                        self.assertIn('REVOKE CONNECT', gate['args'][0])
                        subprocess.run(['sh', '-n'], input=gate['args'][0], text=True, check=True)
                        self.assertEqual(env['DB_NAME']['value'], 'catalog_db')
                        self.assertEqual(env['DB_USER']['valueFrom']['secretKeyRef'], {'name': 'catalog-db-credentials', 'key': 'username'})
                        self.assertEqual(env['DB_PASSWORD']['valueFrom']['secretKeyRef'], {'name': 'catalog-db-credentials', 'key': 'password'})
                        self.assertIn('SPRING_R2DBC_POOL_MAX_ACQUIRE_TIME', env)
                    else:
                        self.assertNotIn('initContainers', deployment['spec']['template']['spec'])
                        self.assertNotIn('DB_PASSWORD', env)
                    if progressive:
                        term = deployment['spec']['template']['spec']['affinity']['podAntiAffinity']['requiredDuringSchedulingIgnoredDuringExecution'][0]
                        self.assertEqual(term['matchLabelKeys'], ['rollouts-pod-template-hash'])
                        rollout = next(d for d in docs if d and d['kind'] == 'Rollout' and d['metadata']['name'] == 'catalog')
                        self.assertEqual(rollout['spec']['workloadRef']['name'], 'catalog')

    def test_aks_database_and_role_preserve_existing_services(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(['kubectl', 'kustomize', str(ROOT / 'platform/environments/aks')], text=True)))
        cluster = next(d for d in docs if d and d['kind'] == 'Cluster')
        roles = {r['name']: r for r in cluster['spec']['managed']['roles']}
        self.assertEqual(set(roles), {'orders', 'inventory', 'payments', 'keycloak', 'catalog'})
        self.assertEqual(roles['catalog']['passwordSecret']['name'], 'catalog-db-credentials')
        self.assertFalse(roles['catalog']['superuser'])
        self.assertFalse(roles['catalog']['createdb'])
        self.assertFalse(roles['catalog']['createrole'])
        database = next(d for d in docs if d and d['kind'] == 'Database')
        self.assertEqual(database['spec'], {'name': 'catalog_db', 'owner': 'catalog', 'cluster': {'name': 'eurotransit-postgres'}, 'ensure': 'present', 'databaseReclaimPolicy': 'retain'})
        self.assertEqual(cluster['spec']['instances'], 1)

    def test_production_enables_storage_and_preserves_rolling_availability(self):
        docs = list(yaml.safe_load_all(subprocess.check_output(['helm', 'template', 'eurotransit', str(ROOT / 'charts/eurotransit'), '-f', str(ROOT / 'charts/eurotransit/values-production.yaml')], text=True)))
        deployment = next(d for d in docs if d and d['kind'] == 'Deployment' and d['metadata']['name'] == 'catalog')
        self.assertEqual(deployment['spec']['strategy']['rollingUpdate']['maxUnavailable'], 0)
        env = {e['name']: e for e in deployment['spec']['template']['spec']['containers'][0]['env']}
        self.assertEqual(env['CATALOG_STORAGE']['value'], 'postgres')
        for mode in ('kind', 'kind-ha'):
            docs = list(yaml.safe_load_all(subprocess.check_output(['helm', 'template', 'eurotransit', str(ROOT / 'charts/eurotransit'), '-f', str(ROOT / 'charts/eurotransit' / ('values-' + mode + '.yaml'))], text=True)))
            deployment = next(d for d in docs if d and d['kind'] == 'Deployment' and d['metadata']['name'] == 'catalog')
            self.assertNotIn('initContainers', deployment['spec']['template']['spec'])


if __name__ == '__main__':
    unittest.main()
