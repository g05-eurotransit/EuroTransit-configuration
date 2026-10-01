#!/usr/bin/env python3
"""Regression checks for effective Pod requests used by the offline budget audit."""
import importlib.util
from pathlib import Path
import sys
import unittest
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('audit', Path(__file__).with_name('check-aks-memory.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def container(memory, restart=None):
    c = {'name': 'test', 'resources': {'requests': {'cpu': '25m', 'memory': memory}, 'limits': {'cpu': '250m', 'memory': '1Gi'}}}
    if restart:
        c['restartPolicy'] = restart
    return c


class SchedulingRequests(unittest.TestCase):
    def test_init_maximum_and_overhead(self):
        self.assertEqual(audit.effective({'containers': [container('100Mi'), container('50Mi')], 'initContainers': [container('200Mi'), container('120Mi')], 'overhead': {'memory': '10Mi'}}), 210)

    def test_restartable_init_contributes_to_later_initialization(self):
        self.assertEqual(audit.effective({'containers': [container('100Mi')], 'initContainers': [container('20Mi', 'Always'), container('200Mi'), container('30Mi', 'Always'), container('180Mi')]}), 230)

    def test_restartable_init_contributes_to_regular_containers(self):
        self.assertEqual(audit.effective({'containers': [container('300Mi')], 'initContainers': [container('20Mi', 'Always'), container('100Mi')]}), 320)

    def test_kubernetes_crd_enum_equals_is_a_string(self):
        self.assertEqual(audit.documents('enum: [=]')[0]['enum'], ['='])

    def test_quantities(self):
        self.assertEqual(audit.quantity('1Gi'), 1024)
        self.assertEqual(audit.quantity('1024Ki'), 1)
        self.assertEqual(audit.quantity('500m', cpu=True), 0.5)

    def test_invalid_budget_is_rejected(self):
        pod = {'containers': [container('2Gi')]}
        render = {'test': [{'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': 'test'}, 'spec': {'template': {'spec': pod}}}]}
        with self.assertRaisesRegex(AssertionError, 'request exceeds limit'):
            audit.audit(render, True, 3)

    def test_duplicate_ownership_is_rejected(self):
        doc = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'test', 'namespace': 'monitoring'}}
        with self.assertRaisesRegex(AssertionError, 'duplicate ownership'):
            audit.audit({'first': [doc], 'second': [doc]}, False, 3)


if __name__ == '__main__':
    unittest.main()
