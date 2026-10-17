#!/usr/bin/env python3
"""Read-only, exhaustive Stripe sandbox charge audit for one run's bounded window."""
import argparse
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPRedirectHandler, Request


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the Authorization header, including to another Stripe host.
        raise ValueError('redirect_rejected')


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def window(meta):
    start = datetime.fromisoformat(meta['startedAt'].replace('Z', '+00:00'))
    end = datetime.fromisoformat(meta['finishedAt'].replace('Z', '+00:00'))
    if start.tzinfo is None or end.tzinfo is None or end < start:
        raise ValueError('invalid_run_window')
    return math.floor(start.timestamp()) - 2, math.ceil(end.timestamp()) + 2


def fetch_page(key, params):
    request = Request('https://api.stripe.com/v1/charges?' + urlencode(params), headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
    opener = build_opener(NoRedirect())
    with opener.open(request, timeout=10) as response:
        return json.load(response)


def audit(meta, evidence, key, fetch=fetch_page, max_pages=10):
    result = {'runId': meta.get('runId'), 'extraction': 'INCOMPLETE', 'authorizations': [], 'allPagesRead': False, 'unmatchedChargesHashes': [], 'unattributedFailedAttempts': [], 'limitations': 'Exhaustive sandbox charge enumeration within the recorded run window. Unattributed failed attempts with explicit zero monetary effect are listed separately; their ownership and future effects are not certified.'}
    try:
        if not isinstance(key, str) or not key.startswith(('sk_test_', 'rk_test_')):
            raise ValueError('sandbox_key_required')
        if evidence.get('runId') != meta['runId'] or evidence.get('extraction') != 'COMPLETE':
            raise ValueError('run_evidence_incomplete')
        lower, upper = window(meta)
        result['window'] = {'createdGte': lower, 'createdLte': upper, 'paddingSeconds': 2}
        owned = {str(row['id']) for row in evidence['orders']}
        mapping = {}
        expected = set()
        for payment in evidence['payments']:
            if str(payment['order_id']) not in owned:
                raise ValueError('payment_scope_mismatch')
            reference = payment.get('provider_reference_hash')
            if not reference:
                if payment.get('status') == 'AUTHORIZED':
                    raise ValueError('authorized_payment_reference_missing')
                continue
            if not re.fullmatch('[0-9a-f]{64}', reference):
                raise ValueError('invalid_reference_hash')
            if reference in mapping:
                raise ValueError('duplicate_database_reference')
            mapping[reference] = str(payment['order_id'])
            if payment['status'] == 'AUTHORIZED':
                expected.add(reference)
        seen, successful = set(), set()
        params = {'limit': 100, 'created[gte]': lower, 'created[lte]': upper}
        for _ in range(max_pages):
            page = fetch(key, params.copy())
            if page.get('object') != 'list' or not isinstance(page.get('data'), list) or not isinstance(page.get('has_more'), bool):
                raise ValueError('invalid_provider_page')
            for charge in page['data']:
                reference = charge.get('id')
                amount = charge.get('amount')
                currency = charge.get('currency')
                if not isinstance(reference, str) or not re.fullmatch('ch_[A-Za-z0-9]+', reference):
                    raise ValueError('invalid_charge_reference')
                hashed = sha(reference)
                if hashed in seen:
                    raise ValueError('duplicate_provider_reference')
                seen.add(hashed)
                if charge.get('livemode') is not False:
                    raise ValueError('non_sandbox_charge')
                if type(amount) is not int or amount <= 0 or not isinstance(currency, str) or not re.fullmatch('[a-z]{3}', currency):
                    raise ValueError('invalid_charge_amount_currency')
                if type(charge.get('created')) is not int or not lower <= charge['created'] <= upper:
                    raise ValueError('provider_charge_outside_window')
                status = charge.get('status')
                if status not in ('succeeded', 'failed', 'pending') or type(charge.get('paid')) is not bool:
                    raise ValueError('invalid_charge_status')
                if status == 'succeeded' and not charge['paid']:
                    raise ValueError('inconsistent_successful_charge')
                if status == 'failed' and charge['paid']:
                    raise ValueError('inconsistent_failed_charge')
                if status == 'pending':
                    raise ValueError('unresolved_provider_charge')
                if hashed not in mapping:
                    # A declined Charge object is not a successful authorization.
                    # Require explicit proof of zero effect; unknown, pending,
                    # captured, refunded or paid records still fail closed.
                    if (status == 'failed' and charge['paid'] is False
                            and charge.get('captured') is False
                            and type(charge.get('amount_captured')) is int
                            and charge['amount_captured'] == 0
                            and type(charge.get('amount_refunded')) is int
                            and charge['amount_refunded'] == 0
                            and 'balance_transaction' in charge
                            and charge['balance_transaction'] is None):
                        result['unattributedFailedAttempts'].append({
                            'provider_reference_hash': hashed, 'status': 'FAILED',
                            'paid': False, 'captured': False,
                            'amount_captured': 0, 'amount_refunded': 0})
                        continue
                    result['unmatchedChargesHashes'].append(hashed)
                    continue
                if status == 'succeeded':
                    successful.add(hashed)
                result['authorizations'].append({'order_id': mapping[hashed], 'provider_reference': reference, 'status': 'SUCCEEDED' if status == 'succeeded' else 'FAILED', 'amount': str(Decimal(amount) / 100), 'currency': currency.upper()})
            if not page['has_more']:
                result['allPagesRead'] = True
                break
            if not page['data']:
                raise ValueError('empty_page_with_more')
            params['starting_after'] = page['data'][-1]['id']
        if not result['allPagesRead']:
            raise ValueError('pagination_limit_reached')
        if result['unmatchedChargesHashes']:
            raise ValueError('unattributed_window_charges')
        if not expected.issubset(successful):
            raise ValueError('authorized_effect_missing_from_window')
        result['extraction'] = 'COMPLETE'
    except (ValueError, KeyError, TypeError, OSError) as exc:
        # Fixed reason vocabulary only. HTTP errors can contain sensitive upstream bodies.
        result['errorClass'] = type(exc).__name__
        if isinstance(exc, ValueError) and str(exc) in {'sandbox_key_required', 'run_evidence_incomplete', 'invalid_run_window', 'payment_scope_mismatch', 'authorized_payment_reference_missing', 'invalid_reference_hash', 'duplicate_database_reference', 'invalid_provider_page', 'invalid_charge_reference', 'duplicate_provider_reference', 'non_sandbox_charge', 'invalid_charge_amount_currency', 'provider_charge_outside_window', 'invalid_charge_status', 'inconsistent_successful_charge', 'inconsistent_failed_charge', 'unresolved_provider_charge', 'empty_page_with_more', 'pagination_limit_reached', 'unattributed_window_charges', 'authorized_effect_missing_from_window', 'redirect_rejected'}:
            result['reason'] = str(exc)
        else:
            result['reason'] = 'provider_audit_failed'
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--max-pages', type=int, default=10)
    args = p.parse_args()
    if not 1 <= args.max_pages <= 10:
        p.error('max-pages must be between 1 and 10')
    os.umask(0o077)
    destination = args.output or args.run_dir / 'provider-audit.json'
    try:
        meta = json.loads((args.run_dir / 'run.json').read_text())
        evidence = json.loads((args.run_dir / 'evidence.json').read_text())
        result = audit(meta, evidence, os.environ.get('STRIPE_SECRET_KEY'), max_pages=args.max_pages)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {'runId': None, 'extraction': 'INCOMPLETE', 'authorizations': [], 'allPagesRead': False, 'unmatchedChargesHashes': [], 'errorClass': type(exc).__name__, 'reason': 'invalid_or_missing_run_input'}
    # Refuse existing destination/symlink rather than overwrite an unrelated artifact.
    with destination.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    destination.chmod(0o600)
    print(json.dumps({'extraction': result['extraction'], 'allPagesRead': result['allPagesRead'], 'authorizationsCount': len(result['authorizations']), 'unmatchedChargesCount': len(result['unmatchedChargesHashes']), 'unattributedZeroEffectFailedAttemptsCount': len(result.get('unattributedFailedAttempts', []))}))
    return result['extraction'] != 'COMPLETE'


if __name__ == '__main__':
    sys.exit(main())
