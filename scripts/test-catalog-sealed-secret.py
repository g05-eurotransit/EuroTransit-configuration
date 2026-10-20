#!/usr/bin/env python3
"""Ensure Catalog-only sealing preserves existing passwords and cannot apply cluster changes."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

spec = importlib.util.spec_from_file_location('seal_catalog', Path(__file__).with_name('generate-catalog-sealed-secret.py'))
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


class CatalogSealingTests(unittest.TestCase):
    def test_preserves_existing_password_and_rejects_wrong_user(self):
        existing = {'data': {k: base64.b64encode(v.encode()).decode() for k, v in {'username': 'catalog', 'password': 'existing-private-test-value'}.items()}}
        self.assertEqual(s.secret_document(existing)['stringData']['password'], 'existing-private-test-value')
        existing['data']['username'] = base64.b64encode(b'orders').decode()
        with self.assertRaises(ValueError):
            s.secret_document(existing)

    def test_only_read_and_seal_commands_and_one_output(self):
        calls = []
        def command(argv, payload=None):
            calls.append(argv)
            if argv[0] == 'kubectl':
                self.assertEqual(argv, ['kubectl', '--context', 'test-aks', '-n', 'eurotransit', 'get', 'secret', 'catalog-db-credentials', '--ignore-not-found', '-o', 'json'])
                return ''
            if '--fetch-cert' in argv:
                return 'public-test-certificate'
            data = json.loads(payload)
            self.assertEqual(data['type'], 'kubernetes.io/basic-auth')
            self.assertEqual(data['stringData']['username'], 'catalog')
            self.assertGreaterEqual(len(data['stringData']['password']), 40)
            self.assertIn('strict', argv)
            return yaml.safe_dump({'apiVersion': 'bitnami.com/v1alpha1', 'kind': 'SealedSecret', 'metadata': data['metadata'], 'spec': {'encryptedData': {'username': 'cipher-user', 'password': 'cipher-password'}}})
        with tempfile.TemporaryDirectory() as tmp, patch.object(s, 'command', side_effect=command):
            target = Path(tmp) / 'catalog.yaml'
            s.generate('test-aks', target=target)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ['catalog.yaml'])
            self.assertNotIn('stringData', target.read_text())
            count = len(calls)
            with self.assertRaises(ValueError):
                s.generate('test-aks', target=target)
            self.assertEqual(len(calls), count)


if __name__ == '__main__':
    unittest.main()
