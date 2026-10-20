#!/usr/bin/env python3
"""Disable only catalog_db connections, prove refusal and historical refund, always restore."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import subprocess
import signal
from urllib.request import Request, urlopen
import uuid

spec = importlib.util.spec_from_file_location('catalog_check', Path(__file__).with_name('kind-catalog-check.py'))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def counts():
    return {name: int(c.sql(db, 'SELECT count(*) FROM ' + table + ';').strip()) for name, db, table in (
        ('orders', 'orders_db', 'orders'), ('reservations', 'inventory_db', 'reservations'),
        ('payments', 'payments_db', 'payment_authorizations'))}


def charge_hashes(since):
    key = c.h.secret('payments-provider-credentials', 'provider-api-key')
    assert key.startswith(('sk_test_', 'rk_test_'))
    with urlopen(Request('https://api.stripe.com/v1/charges?limit=100&created[gte]=' + str(since),
                         headers={'Authorization': 'Bearer ' + key}), timeout=15) as response:
        result = json.load(response)
    assert not result['has_more'], 'Bounded provider audit exceeded one page'
    assert all(row['livemode'] is False for row in result['data'])
    return sorted(hashlib.sha256(row['id'].encode()).hexdigest() for row in result['data'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--historical-orders', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise SystemExit('Interrupted; restoring Catalog database access.')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    os.umask(0o077)
    check = c.Check()
    historical = json.loads(args.historical_orders.read_text())['orders']
    assert c.sql('postgres', "SELECT datallowconn FROM pg_database WHERE datname='catalog_db';").strip() == 't'
    assert c.sql('postgres', "SELECT count(*) FROM pg_stat_activity WHERE datname='catalog_db';").strip() != '0', 'No live Catalog database sessions'
    proof = {'context': c.h.CONTEXT, 'startedAt': c.h.now()}
    selector = c.h.obj('service', 'catalog')['spec']['selector']
    pods = c.h.obj('pods', '-l', ','.join(k + '=' + v for k, v in selector.items()))['items']
    assert pods and all(any(e['name'] == 'CATALOG_STORAGE' and e.get('value') == 'postgres'
        for e in next(v for v in pod['spec']['containers'] if v['name'] == 'catalog')['env']) for pod in pods), 'Active Catalog is not PostgreSQL'
    before = counts()
    since = int(time.time()) - 2
    prior_charges = charge_hashes(since)
    key = 'catalog-outage-' + uuid.uuid4().hex
    try:
        c.sql('postgres', 'ALTER DATABASE catalog_db ALLOW_CONNECTIONS false;')
        c.sql('postgres', "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='catalog_db';")
        proof['health'] = []
        for pod in pods:
            name = pod['metadata']['name']
            live = json.loads(c.h.k('exec', name, '--', 'wget', '-qO-', 'http://127.0.0.1:8080/actuator/health/liveness'))
            assert live['status'] == 'UP'
            ready = subprocess.run(['kubectl', '--context', c.h.CONTEXT, '-n', 'eurotransit', 'exec', name,
                '--', 'wget', '-S', '-O-', 'http://127.0.0.1:8080/actuator/health/readiness'], capture_output=True, text=True, timeout=15)
            assert ready.returncode != 0 and '503' in ready.stderr, 'Readiness must fail with 503'
            proof['health'].append({'pod': name, 'liveness': 'UP', 'readinessHttp': 503})
        started = time.monotonic()
        status, result = check.http('/api/orders', {'routeId': 'rt-to-mi-001', 'offerId': 'of-001',
            'travelDate': historical[0]['travelDate'], 'seats': ['6D'],
            'totalAmount': 24.9, 'paymentMethodToken': 'tok_visa'}, key)
        proof['checkoutRefusal'] = {'httpStatus': status, 'code': result.get('code'),
                                   'seconds': round(time.monotonic() - started, 3)}
        assert status == 503 and result.get('code') == 'OFFER_UNRESOLVABLE', proof['checkoutRefusal']
        after = counts()
        assert before == after, (before, after)
        assert c.sql('orders_db', "SELECT count(*) FROM idempotency_keys WHERE key='" + key + "';").strip() == '0'
        assert charge_hashes(since) == prior_charges, 'Unexpected provider charge during refused checkout'
        proof['noBusinessEffects'] = {'before': before, 'after': after, 'providerChargesUnchanged': True}
        for order in historical:
            status, result = check.http('/api/orders/' + order['orderId'])
            assert status == 200 and result['status'] == 'CONFIRMED'
        proof['historicalOrdersReadable'] = True
        proof['historicalStandardRefund'] = check.refund(next(o for o in historical if o['offerId'] == 'of-001'))
        proof['historicalBusinessRefund'] = check.refund(next(o for o in historical if o['offerId'] == 'of-002'))
        proof['passed'] = True
    finally:
        c.sql('postgres', 'ALTER DATABASE catalog_db ALLOW_CONNECTIONS true;')
        proof['accessRestored'] = True
        proof['finishedAt'] = c.h.now()
        args.output.write_text(json.dumps(proof, indent=2) + '\n')
    deadline = time.monotonic() + 60
    while True:
        status, result = check.http('/api/catalog/offers/of-003')
        if status == 200:
            break
        assert time.monotonic() < deadline, 'Catalog did not recover'
        time.sleep(1)
    proof['catalogRecovered'] = True
    args.output.write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps({'passed': True, 'checkoutRefusal': proof['checkoutRefusal'], 'historicalBusinessRefund': proof['historicalBusinessRefund']['status'], 'accessRestored': True}))


if __name__ == '__main__':
    main()
