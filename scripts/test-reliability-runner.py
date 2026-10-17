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
    def test_expect_overload_reaches_native_and_docker_wrapper(self):
        for image in ('', 'registry/harness:abcdef1'):
            with self.subTest(image=image), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                fixtures = root / 'fixtures.json'
                r.write(fixtures, {'version': 1, 'fixtures': [
                    {'routeId': 'route', 'travelDate': '2099-01-01', 'seatId': '1A'}]})
                args = SimpleNamespace(context='test', namespace='test', output=root / 'results',
                    fixtures=fixtures, scenario='spike', max_attempts=1, image=image,
                    mode='workstation', max_vus=1, run_id='overload-run', harness=root / 'run.py',
                    public_url='https://example.invalid', issuer='https://example.invalid/realm', deadline=60)
                op = r.Operator(args)
                op.preflight = Mock(return_value={'errors': [], 'saturated': False})
                op.get = Mock(return_value={'items': [
                    {'metadata': {'name': name}, 'status': {'availableReplicas': 1}}
                    for name in ('catalog', 'orders', 'inventory', 'payments')]})
                op.available_fixtures = Mock()
                op.snapshot = Mock()
                op.cm = Mock()
                op.k = Mock()
                def execute(argv, env, log, *_args):
                    self.assertEqual(env['EXPECT_OVERLOAD'], 'true')
                    if image:
                        self.assertIn(['--env', 'EXPECT_OVERLOAD'], [argv[i:i+2] for i in range(len(argv)-1)])
                    log.write('\n'.join('ET_RESULT ' + json.dumps(event) for event in [
                        {'type': 'order_result', 'runId': args.run_id, 'orderId': 'one'},
                        {'type': 'run_summary', 'runId': args.run_id},
                        {'type': 'runner_finished', 'runId': args.run_id, 'passed': True}]))
                    return 0
                with patch.dict(r.os.environ, {'CLIENT_SECRET': 'unit-secret', 'EXPECT_OVERLOAD': 'true'}), \
                     patch.object(r, 'command'), patch.object(r, 'bounded_process', side_effect=execute):
                    self.assertEqual(op.run(), 0)

    def test_invalid_overload_expectation_fails_before_cluster_actions(self):
        op = r.Operator(SimpleNamespace(context='test', namespace='test'))
        with patch.dict(r.os.environ, {'EXPECT_OVERLOAD': 'yes'}), patch.object(r, 'command') as cmd:
            with self.assertRaisesRegex(ValueError, 'EXPECT_OVERLOAD must be true or false'):
                op.run()
            cmd.assert_not_called()

    def test_command_timeout_is_bounded_and_redacted(self):
        with patch.object(r.subprocess, 'run', side_effect=subprocess.TimeoutExpired(
                ['tool', 'secret-argument'], 30, output='secret-output', stderr='secret-error')) as run:
            with self.assertRaisesRegex(RuntimeError, '^Command timed out after 30 seconds$'):
                r.command(['tool', 'secret-argument'], data='secret-input', env={'SECRET': 'secret-env'})
            self.assertEqual(run.call_args.kwargs['timeout'], 30)

    def test_job_launcher_preserves_template_secret_and_extra_env(self):
        secret = {'name': 'CLIENT_SECRET', 'valueFrom': {'secretKeyRef': {
            'name': 'custom-load-credentials', 'key': 'custom-key', 'optional': False}}}
        for credentials, valid in [(secret, True), ({'name': 'CLIENT_SECRET', 'value': 'unsafe'}, False), (None, False)]:
            with self.subTest(credentials=credentials), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                fixtures = root / 'fixtures.json'
                r.write(fixtures, {'version': 1, 'fixtures': [
                    {'routeId': 'route', 'travelDate': '2026-11-01', 'seatId': '1A'}]})
                args = SimpleNamespace(context='test', namespace='test', output=root / 'results',
                    fixtures=fixtures, scenario='baseline', max_attempts=1, image='registry/harness:abcdef1',
                    mode='job', max_vus=1, run_id='custom-secret-run', harness=None,
                    public_url='https://example.invalid', issuer='https://example.invalid/realm', deadline=60)
                extra = {'name': 'EXPECT_OVERLOAD', 'value': 'true'}
                template = {'template': {'spec': {'containers': [{'env': [extra,
                    {'name': 'RUN_ID', 'value': 'old-run'}] + ([credentials] if credentials else [])}],
                    'volumes': [{'configMap': {'name': 'unclaimed'}}]}}}
                op = r.Operator(args)
                def get(*argv):
                    if argv[0] == 'deployments':
                        return {'items': [{'metadata': {'name': name}, 'status': {'availableReplicas': 1}}
                                          for name in ['catalog', 'orders', 'inventory', 'payments']]}
                    if argv[0] == 'cronjob':
                        return {'spec': {'jobTemplate': {'spec': template}}}
                    if argv[0] == 'job':
                        return {'status': {'succeeded': 1}}
                    raise AssertionError(argv)
                op.get = Mock(side_effect=get)
                op.preflight = Mock(return_value={'errors': [], 'saturated': False,
                                                 'eligibleNodes': ['admitted-node']})
                op.available_fixtures = Mock()
                op.snapshot = Mock()
                op.cm = Mock()
                events = '\n'.join('ET_RESULT ' + json.dumps(event) for event in [
                    {'type': 'order_result', 'runId': args.run_id, 'orderId': 'order-one'},
                    {'type': 'run_summary', 'runId': args.run_id, 'passed': True},
                    {'type': 'runner_finished', 'runId': args.run_id, 'passed': True}])
                op.k = Mock(side_effect=lambda *argv, **kwargs: events if argv[0] == 'logs' else '')
                if valid:
                    with patch.dict(r.os.environ, {'EXPECT_OVERLOAD': 'true'}):
                        self.assertEqual(op.run(), 0)
                    creation = next(call for call in op.k.call_args_list if call.args[0] == 'create')
                    job = json.loads(creation.kwargs['data'])
                    env = job['spec']['template']['spec']['containers'][0]['env']
                    self.assertEqual([entry for entry in env if entry['name'] == 'CLIENT_SECRET'], [secret])
                    self.assertIn(extra, env)
                    self.assertEqual([entry for entry in env if entry['name'] == 'RUN_ID'],
                                     [{'name': 'RUN_ID', 'value': args.run_id}])
                    terms = job['spec']['template']['spec']['affinity']['nodeAffinity'][
                        'requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms']
                    self.assertEqual(terms[0]['matchFields'], [
                        {'key': 'metadata.name', 'operator': 'In', 'values': ['admitted-node']}])
                    # A successful Kubernetes exit cannot certify missing results.
                    args.output = root / 'missing-results'
                    op.k = Mock(return_value='')
                    self.assertEqual(op.run(), 1)
                    self.assertFalse(json.loads((args.output / 'summary.json').read_text())['passed'])
                else:
                    with self.assertRaisesRegex(ValueError, 'CLIENT_SECRET'):
                        op.run()
                    op.k.assert_not_called()

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
