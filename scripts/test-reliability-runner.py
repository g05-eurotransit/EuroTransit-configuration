#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, Mock
import tempfile
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('runner', Path(__file__).with_name('reliability-runner.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def inventory(used='1000Mi'):
    return ({'items': [{'metadata': {'name': 'n'}, 'spec': {}, 'status': {'allocatable': {'cpu': '1900m', 'memory': '2800Mi'}, 'conditions': [{'type': 'Ready', 'status': 'True'}]}}]}, {'items': []}, {'items': [{'metadata': {'name': 'n'}, 'timestamp': r.utc().isoformat(), 'usage': {'memory': used}}]})


class RunnerTests(unittest.TestCase):
    def test_saturation_only_baseline_workstation(self):
        nodes, pods, metrics = inventory('2900Mi')
        self.assertTrue(r.capacity(nodes, pods, metrics, 'workstation')['saturated'])
        self.assertFalse(r.capacity(nodes, pods, metrics, 'workstation')['errors'])
        self.assertFalse(r.capacity(nodes, pods, metrics, 'workstation')['faultsPermitted'])
        self.assertTrue(r.capacity(nodes, pods, metrics, 'job')['errors'])

    def test_limit_margin_and_extra_are_counted(self):
        data = inventory('2400Mi')
        self.assertFalse(r.capacity(*data, 'job')['errors'])
        self.assertTrue(r.capacity(*data, 'job', extra_mib=64)['errors'])

    def test_missing_stale_metrics_fail_closed(self):
        nodes, pods, metrics = inventory()
        metrics['items'][0]['timestamp'] = '2000-01-01T00:00:00Z'
        self.assertTrue(r.capacity(nodes, pods, metrics, 'workstation')['errors'])
        metrics['items'] = []
        self.assertTrue(r.capacity(nodes, pods, metrics, 'job')['errors'])

    def test_scheduler_cpu_memory_and_taints(self):
        nodes, pods, metrics = inventory()
        pods['items'] = [{'metadata': {'name': 'busy'}, 'spec': {'nodeName': 'n', 'containers': [{'resources': {'requests': {'cpu': '1890m'}}}]}, 'status': {}}]
        self.assertTrue(r.capacity(nodes, pods, metrics, 'job')['errors'])
        pods['items'] = []
        nodes['items'][0]['spec']['taints'] = [{'effect': 'NoSchedule'}]
        self.assertTrue(r.capacity(nodes, pods, metrics, 'job')['errors'])

    def test_recent_oom_blocks_even_workstation(self):
        nodes, pods, metrics = inventory()
        pods['items'] = [{'metadata': {'name': 'oom'}, 'spec': {}, 'status': {'containerStatuses': [{'lastState': {'terminated': {'reason': 'OOMKilled', 'finishedAt': r.utc().isoformat()}}}]}}]
        self.assertTrue(r.capacity(nodes, pods, metrics, 'workstation')['errors'])

    def test_effective_restartable_init_and_overhead(self):
        pod = {'containers': [{'resources': {'requests': {'memory': '100Mi'}}}], 'initContainers': [{'resources': {'requests': {'memory': '20Mi'}}, 'restartPolicy': 'Always'}, {'resources': {'requests': {'memory': '200Mi'}}}], 'overhead': {'memory': '10Mi'}}
        self.assertEqual(r.requests(pod, 'memory'), 230)

    def test_fixture_duplicate_rejected(self):
        fixture = {'routeId': 'route', 'travelDate': '2026-11-01', 'seatId': '1A'}
        with self.assertRaises(ValueError):
            r.fixture_keys({'version': 1, 'fixtures': [fixture, fixture]})

    def test_k6_wrapped_and_direct_events_attributed(self):
        event = {'type': 'order_result', 'runId': 'run', 'orderId': 'id'}
        payload = 'ET_RESULT ' + json.dumps(event)
        log = payload + '\ntime=now level=info msg=' + json.dumps(payload) + ' source=console\n'
        self.assertEqual(r.parse_results(log, 'run'), [event, event])
        with self.assertRaises(ValueError):
            r.parse_results(payload, 'other')

    def test_timeout_stops_own_container_and_process_group(self):
        process = Mock(pid=99)
        process.wait.side_effect = [subprocess.TimeoutExpired('docker', 1), 0]
        with patch.object(r.subprocess, 'Popen', return_value=process), patch.object(r, 'command') as cmd, patch.object(r.os, 'killpg') as kill:
            self.assertEqual(r.bounded_process(['docker'], {}, None, 1, 'own-run'), 124)
            cmd.assert_called_once_with(['docker', 'kill', 'own-run'])
            kill.assert_called_once_with(99, r.signal.SIGTERM)

    def test_native_interrupt_stops_group_without_docker(self):
        process = Mock(pid=100)
        process.wait.side_effect = [KeyboardInterrupt(), 0]
        with patch.object(r.subprocess, 'Popen', return_value=process), patch.object(r, 'command') as cmd, patch.object(r.os, 'killpg') as kill:
            self.assertEqual(r.bounded_process(['python3'], {}, None, 1), 130)
            cmd.assert_not_called()
            kill.assert_called_once_with(100, r.signal.SIGTERM)

    def test_failed_container_stop_is_ambiguous(self):
        process = Mock(pid=99)
        process.wait.side_effect = subprocess.TimeoutExpired('docker', 1)
        with patch.object(r.subprocess, 'Popen', return_value=process), patch.object(r, 'command', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):
                r.bounded_process(['docker'], {}, None, 1, 'own-run')

    def test_authoritative_summary_failure_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            r.write(output / 'summary.json', {'runId': 'run', 'passed': False, 'reason': 'incomplete_order_ledger'})
            (output / 'runner.log').write_text('ET_RESULT ' + json.dumps({'type': 'run_summary', 'runId': 'run'}) + '\nET_RESULT ' + json.dumps({'type': 'runner_finished', 'runId': 'run', 'passed': True}))
            op = r.Operator(SimpleNamespace(context='test', namespace='test'))
            op.extract(output, 'run')
            self.assertFalse(json.loads((output / 'summary.json').read_text())['passed'])

    def test_inventory_collect_includes_other_owners_and_readonly_sql(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            oid = '11111111-1111-1111-1111-111111111111'
            row = {'type': 'order_result', 'runId': 'run', 'orderId': oid, 'fixture': {'routeId': "route'quote", 'seatId': '1A', 'travelDate': '2026-11-01'}}
            r.write(output / 'run.json', {'runId': 'run'})
            (output / 'runner.log').write_text('ET_RESULT ' + json.dumps(row))
            op = r.Operator(SimpleNamespace(context='test', namespace='test', output=output, provider_evidence=None))
            calls = []
            op.db = lambda db, sql: calls.append((db, sql)) or []
            op.collect()
            seat_sql = next(sql for db, sql in calls if 'FROM seats' in sql)
            self.assertIn("route_id='route''quote'", seat_sql)
            self.assertNotIn('SELECT reservation_id', seat_sql)
            self.assertEqual(json.loads((output / 'evidence.json').read_text())['providerEffects']['extraction'], 'INCOMPLETE')
            op.get = lambda *args: {'items': [{'metadata': {'name': 'pg', 'labels': {'role': 'primary'}}}]}
            op.k = Mock(return_value='[]')
            r.Operator.db(op, 'orders_db', 'SELECT 1')
            self.assertIn('BEGIN READ ONLY; SET LOCAL statement_timeout=10000; SELECT 1; COMMIT;', op.k.call_args.kwargs['data'])

    def test_chart_opt_in_pinned_and_bounded(self):
        root = Path(__file__).resolve().parents[1]
        def render(*extra):
            return subprocess.run(['helm', 'template', 'eurotransit', str(root / 'charts/eurotransit'), '-f', str(root / 'charts/eurotransit/values-production.yaml'), *extra], capture_output=True, text=True)
        self.assertNotIn('name: eurotransit-load-tests', render().stdout)
        self.assertNotEqual(render('--set', 'reliabilityTests.enabled=true', '--set', 'reliabilityTests.image=eurotransit/load-tests:latest').returncode, 0)
        import yaml
        enabled = render('--set', 'reliabilityTests.enabled=true', '--set', 'reliabilityTests.image=eurotransit/load-tests:abcdef1234567')
        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        cron = next(d for d in yaml.safe_load_all(enabled.stdout) if d and d.get('metadata', {}).get('name') == 'eurotransit-load-tests')
        self.assertTrue(cron['spec']['suspend'])
        job = cron['spec']['jobTemplate']['spec']
        self.assertEqual(job['backoffLimit'], 0)
        self.assertFalse(job['template']['spec']['automountServiceAccountToken'])
        env = {e['name']: e for e in job['template']['spec']['containers'][0]['env']}
        self.assertEqual(env['TOKEN_URL']['value'], 'https://g05.cpo2026.it/realms/eurotransit/protocol/openid-connect/token')
        self.assertIn('valueFrom', env['CLIENT_SECRET'])


if __name__ == '__main__':
    unittest.main()
