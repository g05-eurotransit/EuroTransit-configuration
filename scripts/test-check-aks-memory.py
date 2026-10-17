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
    def test_filter_supports_current_baseline_without_allowing_default_changes(self):
        default = {'action': 'keep', 'regex': 'required-default'}
        drop = {'action': 'drop', 'sourceLabels': ['__name__'],
                'regex': 'apiserver_(request_duration_seconds|request_body_size_bytes|request_sizes|response_sizes|response_size_bytes)_(bucket|sum|count)'}
        audit.check_filter_preservation([default, drop], [default])
        audit.check_filter_preservation([default, drop], [default, drop])
        with self.assertRaisesRegex(AssertionError, 'chart default API server filter changed'):
            audit.check_filter_preservation([drop], [default, drop])
        with self.assertRaisesRegex(AssertionError, 'unexpected API server drop filter'):
            audit.check_filter_preservation([default, {'action': 'drop', 'regex': '.*'}], [default])

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

    def test_absent_eraser_sample_leaves_future_request_unknown(self):
        unrelated = {'metadata': {'name': 'eraser-controller-manager-test'},
                     'spec': {'containers': [container('64Mi')]},
                     'status': {'phase': 'Running'}}
        result = audit.eraser_requests([unrelated])
        self.assertIsNone(result['eraser_request_per_node_mib'])
        self.assertEqual(result['observed_active_eraser_requests_mib'], 0)

    def test_completed_eraser_sample_sizes_future_scan_without_active_cost(self):
        scan = {'metadata': {'name': 'eraser-aks-test'},
                'spec': {'containers': [container('550Mi')]},
                'status': {'phase': 'Succeeded'}}
        result = audit.eraser_requests([scan])
        self.assertEqual(result['eraser_request_per_node_mib'], 550)
        self.assertEqual(result['observed_active_eraser_requests_mib'], 0)
        scan['status']['phase'] = 'Running'
        self.assertEqual(audit.eraser_requests([scan])['observed_active_eraser_requests_mib'], 550)

    def test_invalid_budget_is_rejected(self):
        pod = {'containers': [container('2Gi')]}
        render = {'test': [{'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': 'test'}, 'spec': {'template': {'spec': pod}}}]}
        with self.assertRaisesRegex(AssertionError, 'request exceeds limit'):
            audit.audit(render, True, 3)

    def test_duplicate_ownership_is_rejected(self):
        doc = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'test', 'namespace': 'monitoring'}}
        with self.assertRaisesRegex(AssertionError, 'duplicate ownership'):
            audit.audit({'first': [doc], 'second': [doc]}, False, 3)


    def test_kind_secret_changes_are_rejected(self):
        def render(value):
            return {'owner': [{'apiVersion': 'v1', 'kind': 'Secret',
                              'metadata': {'name': 'test'}, 'data': {'key': value}}]}
        audit.check_kind_unchanged(render('a'), render('a'))
        with self.assertRaisesRegex(AssertionError, 'Kind render changed'):
            audit.check_kind_unchanged(render('b'), render('a'))

    def test_deleted_or_changed_dashboard_is_rejected(self):
        def dashboard(value):
            return {'kind': 'ConfigMap', 'metadata': {'name': 'test', 'namespace': 'monitoring',
                    'labels': {'grafana_dashboard': '1'}}, 'data': {'test.json': value}}
        audit.check_dashboard_preservation([dashboard('a')], [dashboard('a')])
        with self.assertRaisesRegex(AssertionError, 'set changed'):
            audit.check_dashboard_preservation([], [dashboard('a')])
        with self.assertRaisesRegex(AssertionError, 'content changed'):
            audit.check_dashboard_preservation([dashboard('b')], [dashboard('a')])

    def test_default_application_namespace_counts_for_ownership(self):
        def cm(namespace=None):
            doc = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'test'}}
            if namespace:
                doc['metadata']['namespace'] = namespace
            return doc
        app = {'kind': 'Application', 'metadata': {'name': 'first'},
               'spec': {'destination': {'namespace': 'monitoring'}}}
        with self.assertRaisesRegex(AssertionError, 'duplicate ownership'):
            audit.audit({'argocd-applications': [app], 'first': [cm()],
                         'second': [cm('monitoring')]}, False, 3)


if __name__ == '__main__':
    unittest.main()
