#!/usr/bin/env python3
import datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class FaultContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.preflight = self.root / 'preflight.json'
        self.data = {'status': 'passed', 'faultsPermitted': True, 'context': 'test',
                     'namespace': 'eurotransit', 'runId': 'run-test', 'extraMemoryMiB': 576,
                     'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        self.preflight.write_text(json.dumps(self.data))

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, extra=(), scenario='inventory-kill', env=None):
        return subprocess.run(['python3', str(ROOT / 'scripts/reliability/fault.py'), scenario,
                               '--context', 'test', '--run-id', 'run-test', '--output-dir', str(self.root),
                               '--preflight', str(self.preflight), *extra], env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_dry_run_does_not_call_kubectl(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['dryRun'])

    def test_saturation_and_stale_gate(self):
        for patch in ({'faultsPermitted': False}, {'context': 'wrong'},
                      {'timestamp': '2000-01-01T00:00:00+00:00'}):
            self.preflight.write_text(json.dumps(self.data | patch))
            self.assertNotEqual(self.invoke(['--execute']).returncode, 0)

    def test_proxy_rollout_memory_gate(self):
        self.preflight.write_text(json.dumps(self.data | {'extraMemoryMiB': 64}))
        self.assertNotEqual(self.invoke(scenario='payments-latency').returncode, 0)

    def test_uid_precondition_and_single_kill(self):
        exe = self.root / 'kubectl'
        exe.write_text('''#!/usr/bin/env python3
import json,sys
from pathlib import Path
if 'get' in sys.argv:
 print(json.dumps({'items':[{'metadata':{'name':'inventory-old','uid':'uid-original'},'status':{'conditions':[{'type':'Ready','status':'True'}]}}]}))
else:
 Path(__file__).with_name('delete.json').write_text(sys.stdin.read())
''')
        exe.chmod(0o755)
        env = os.environ | {'PATH': str(self.root) + ':' + os.environ['PATH']}
        result = self.invoke(['--execute'], env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        deleted = json.loads((self.root / 'delete.json').read_text())
        self.assertEqual(deleted['preconditions'], {'uid': 'uid-original'})
        proof = json.loads((self.root / 'inventory-kill-fault.json').read_text())
        self.assertFalse(proof['overlapEvidence'])
        self.assertNotEqual(self.invoke(['--execute'], env=env).returncode, 0)

    def test_replay_is_scoped_to_original_run_orders(self):
        (self.root / 'run.json').write_text(json.dumps({'runId': 'run-test'}))
        (self.root / 'orders.jsonl').write_text(json.dumps({'runId': 'run-test', 'orderId': 'order-one'}) + '\n')
        exported = {'runId': 'run-test', 'events': [{'id': 'event-one', 'aggregate_id': 'order-one',
                    'type': 'order-placed', 'payload': {'orderId': 'order-one'},
                    'created_at': '2026-10-06T12:00:00Z', 'source': 'outbox'}]}
        source = self.root / 'canonical-events.json'
        source.write_text(json.dumps(exported))
        command = ['python3', str(ROOT / 'scripts/reliability/replay-events.py'), '--context', 'test',
                   '--producer-pod', 'broker', '--output-dir', str(self.root), '--preflight', str(self.preflight)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['executed'])
        exported['events'][0]['aggregate_id'] = 'other-order'
        exported['events'][0]['payload']['orderId'] = 'other-order'
        source.write_text(json.dumps(exported))
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
