#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest
from urllib.error import HTTPError
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location('audit', Path(__file__).with_name('reliability') / 'provider-audit.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class AuditTests(unittest.TestCase):
    def fixture(self):
        meta = {'runId': 'run', 'startedAt': '2026-10-06T21:50:49.460Z', 'finishedAt': '2026-10-06T21:51:26.030Z'}
        evidence = {'runId': 'run', 'extraction': 'COMPLETE', 'orders': [{'id': 'order'}], 'payments': [{'order_id': 'order', 'status': 'AUTHORIZED', 'provider_reference_hash': a.sha('ch_one')}]}
        charge = {'id': 'ch_one', 'livemode': False, 'amount': 2490, 'currency': 'eur', 'status': 'succeeded', 'paid': True, 'created': 1791323460, 'billing_details': {'name': 'DO NOT EXPORT'}, 'card': {'number': 'DO NOT EXPORT'}}
        lower, upper = a.window(meta)
        charge['created'] = lower + 2
        return meta, evidence, charge

    def run_audit(self, charges, **kwargs):
        meta, evidence, _ = self.fixture()
        return a.audit(meta, evidence, 'sk_test_dummy', fetch=lambda key, params: {'object': 'list', 'data': charges, 'has_more': False}, **kwargs)

    def test_complete_whitelist(self):
        _, _, charge = self.fixture()
        result = self.run_audit([charge])
        self.assertEqual(result['extraction'], 'COMPLETE')
        self.assertEqual(result['authorizations'][0]['amount'], '24.9')
        self.assertNotIn('DO NOT EXPORT', str(result))

    def test_extra_unattributed_charge_cannot_pass(self):
        _, _, charge = self.fixture()
        extra = dict(charge, id='ch_unknown')
        result = self.run_audit([charge, extra])
        self.assertEqual(result['extraction'], 'INCOMPLETE')
        self.assertEqual(result['unmatchedChargesHashes'], [a.sha('ch_unknown')])
        self.assertNotIn('ch_unknown', str(result))

    def test_duplicate_reference_rejected(self):
        _, _, charge = self.fixture()
        self.assertEqual(self.run_audit([charge, charge])['reason'], 'duplicate_provider_reference')

    def test_missing_success_rejected(self):
        self.assertEqual(self.run_audit([])['reason'], 'authorized_effect_missing_from_window')
        _, _, charge = self.fixture()
        self.assertEqual(self.run_audit([dict(charge, status='failed', paid=False)])['extraction'], 'INCOMPLETE')

    def test_live_invalid_status_amount_fail_closed(self):
        _, _, charge = self.fixture()
        for changes in [{'livemode': True}, {'amount': -1}, {'currency': 'XXX'}, {'status': 'pending'}, {'paid': False}]:
            self.assertEqual(self.run_audit([dict(charge, **changes)])['extraction'], 'INCOMPLETE')

    def test_pagination_exhaustive_and_bounded(self):
        meta, evidence, charge = self.fixture()
        fetch = Mock(side_effect=[{'object': 'list', 'data': [charge], 'has_more': True}, {'object': 'list', 'data': [], 'has_more': False}])
        result = a.audit(meta, evidence, 'rk_test_dummy', fetch=fetch)
        self.assertEqual(result['extraction'], 'COMPLETE')
        self.assertEqual(fetch.call_args_list[1].args[1]['starting_after'], 'ch_one')
        self.assertEqual(fetch.call_args_list[0].args[1]['limit'], 100)
        never_done = lambda key, params: {'object': 'list', 'data': [charge], 'has_more': True}
        self.assertEqual(a.audit(meta, evidence, 'sk_test_dummy', fetch=never_done, max_pages=1)['reason'], 'pagination_limit_reached')

    def test_invalid_key_and_http_errors_redacted(self):
        meta, evidence, _ = self.fixture()
        fetch = Mock()
        self.assertEqual(a.audit(meta, evidence, 'sk_live_secret', fetch=fetch)['extraction'], 'INCOMPLETE')
        fetch.assert_not_called()
        fetch.side_effect = HTTPError('url', 401, 'SECRET BODY', {}, None)
        result = a.audit(meta, evidence, 'sk_test_secret', fetch=fetch)
        self.assertNotIn('SECRET', str(result))
        self.assertEqual(result['errorClass'], 'HTTPError')

    def test_redirect_rejected(self):
        with self.assertRaisesRegex(ValueError, 'redirect_rejected'):
            a.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid')


if __name__ == '__main__':
    unittest.main()
