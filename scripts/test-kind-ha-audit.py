"""The financial audit must not hide a broken invariant behind an HTTP timeout."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


harness = load('ha_experiment', ROOT / 'scripts/kind-ha-experiment.py')
fixtures = load('verify_fixtures', ROOT / 'load-tests/tests/test_verify.py')


class AuditTest(unittest.TestCase):
    def test_slot_sync_worker_is_not_a_consumer(self):
        slots = [{'slot_name':name,'active':False,'restart_lsn':'0/100','confirmed_flush_lsn':'0/200'}
                 for name in sorted(harness.EXPECTED_SLOTS)]
        self.assertTrue(harness.standby_slots_ready(slots))
        slots[0].update(active=True, active_backend_type='pg_failover_slots worker')
        self.assertTrue(harness.standby_slots_ready(slots))
        slots[0]['active_backend_type'] = 'walsender'
        self.assertFalse(harness.standby_slots_ready(slots))
        slots[0].update(active=False, restart_lsn=None)
        self.assertFalse(harness.standby_slots_ready(slots))
        self.assertFalse(harness.standby_slots_ready(slots[1:]))

    def test_stop_and_freeze_are_distinct_faults(self):
        running = {'Running': True, 'Paused': False}
        frozen = {'Running': True, 'Paused': True}
        stopped = {'Running': False, 'Paused': False}
        self.assertFalse(harness.unavailable(running, 'worker-stop'))
        self.assertFalse(harness.unavailable(running, 'worker-freeze'))
        self.assertTrue(harness.unavailable(frozen, 'worker-freeze'))
        self.assertFalse(harness.unavailable(frozen, 'worker-stop'))
        self.assertTrue(harness.unavailable(stopped, 'worker-stop'))

    def test_committed_http_timeout_keeps_client_failure(self):
        rows, evidence = fixtures.VerifyTests().case()
        rows[0]['httpStatus'] = 0
        violations = fixtures.module.verify(rows, evidence)
        self.assertEqual(violations, ['invalid_acceptance_evidence'])
        self.assertTrue(harness.money_invariants_verified(
            evidence['providerEffects'], {'passed': False, 'violations': violations}))
        self.assertEqual(rows[0]['httpStatus'], 0)

    def test_timeout_does_not_mask_financial_failure(self):
        for defect in ('duplicate_charge', 'wrong_owner', 'missing_provider'):
            with self.subTest(defect=defect):
                rows, evidence = fixtures.VerifyTests().case()
                rows[0]['httpStatus'] = 0
                if defect == 'duplicate_charge':
                    evidence['providerEffects']['authorizations'] *= 2
                elif defect == 'wrong_owner':
                    evidence['inventory'][0]['reservation_id'] = 'another-order'
                else:
                    evidence['providerEffects']['extraction'] = 'INCOMPLETE'
                self.assertFalse(harness.money_invariants_verified(evidence['providerEffects'],
                    {'passed': False, 'violations': fixtures.module.verify(rows, evidence)}))

    def test_absent_or_inconsistent_verifier_result_never_passes(self):
        for result in ({}, {'passed': False, 'violations': []}):
            self.assertFalse(harness.money_invariants_verified({'extraction': 'COMPLETE'}, result))


if __name__ == '__main__':
    unittest.main()
