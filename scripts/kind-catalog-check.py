#!/usr/bin/env python3
"""Bounded Catalog checkout/refund proof on kind-eurotransit; credentials stay in memory."""
import argparse
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kind_ha', ROOT / 'scripts/kind-ha-experiment.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def sql(database, query):
    assert database in ('orders_db', 'inventory_db', 'payments_db', 'catalog_db', 'postgres')
    primary = h.obj('cluster.postgresql.cnpg.io', 'eurotransit-postgres')['status']['currentPrimary']
    return h.k('exec', '-i', primary, '-c', 'postgres', '--', 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1',
               '-U', 'postgres', '-d', database, data=query + '\n')


class Check:
    def __init__(self):
        provider_key = h.secret('payments-provider-credentials', 'provider-api-key')
        assert provider_key.startswith(('sk_test_', 'rk_test_')), 'Sandbox credentials required before any purchase'
        self.auth = h.token()

    def http(self, path, body=None, key=None):
        headers = {'Authorization': 'Bearer ' + self.auth, 'Content-Type': 'application/json'}
        if key:
            headers['Idempotency-Key'] = key
        payload = json.dumps(body).encode() if body is not None else None
        try:
            with urlopen(Request(h.BASE + path, data=payload, headers=headers), context=h.TLS, timeout=15) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            try:
                data = json.load(exc)
            except ValueError:
                data = {}
            return exc.code, data

    def wait_order(self, oid, expected):
        uuid.UUID(oid)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            status, result = self.http('/api/orders/' + oid)
            assert status == 200, ('order_read', status)
            if result['status'] == expected:
                return result
            assert result['status'] not in ('FAILED', 'REFUND_FAILED', 'CANCELLED'), ('unexpected_terminal', result['status'], result.get('failureCode'))
            time.sleep(.5)
        raise AssertionError('Order did not reach ' + expected)

    def provider(self, oid, amount, refunded=False):
        uuid.UUID(oid)
        rows = json.loads(sql('payments_db', "SELECT coalesce(json_agg(t),'[]') FROM (SELECT status,amount,currency,provider_reference FROM payment_authorizations WHERE order_id='" + oid + "') t;"))
        assert len(rows) == 1 and rows[0]['status'] == 'AUTHORIZED', 'payment_authorization'
        reference = rows[0]['provider_reference']
        assert isinstance(reference, str) and reference.startswith('ch_') and reference.replace('_', '').isalnum()
        key = h.secret('payments-provider-credentials', 'provider-api-key')
        assert key.startswith(('sk_test_', 'rk_test_')), 'Sandbox credentials required'
        with urlopen(Request('https://api.stripe.com/v1/charges/' + reference,
                             headers={'Authorization': 'Bearer ' + key}), timeout=15) as response:
            charge = json.load(response)
        assert charge['livemode'] is False and charge['paid'] and charge['status'] == 'succeeded'
        assert charge['amount'] == int(Decimal(str(amount)) * 100) and charge['currency'] == 'eur'
        assert charge['amount_refunded'] == (charge['amount'] if refunded else 0)
        return {'chargeHash': hashlib.sha256(reference.encode()).hexdigest(), 'sandbox': True,
                'amountCents': charge['amount'], 'refundedCents': charge['amount_refunded']}

    def checkout(self, offer, seats_count):
        status, detail = self.http('/api/catalog/offers/' + offer)
        assert status == 200
        travel = (date.today() + timedelta(days=1)).isoformat()
        status, availability = self.http('/api/orders/seat-availability?routeId=' + detail['routeId'] + '&travelDate=' + travel)
        assert status == 200
        seats = [s['seatId'] for s in availability['seats'] if s['available']][:seats_count]
        assert len(seats) == seats_count
        body = {'routeId': detail['routeId'], 'offerId': offer, 'travelDate': travel, 'seats': seats,
                'totalAmount': float(Decimal(str(detail['price'])) * seats_count), 'paymentMethodToken': 'tok_visa'}
        status, accepted = self.http('/api/orders', body, 'catalog-proof-' + uuid.uuid4().hex)
        assert status == 202, ('checkout', status, accepted.get('code'))
        oid = accepted['orderId']
        final = self.wait_order(oid, 'CONFIRMED')
        assert final['refundable'] == detail['refundPolicy']['refundable']
        assert final['refundCutoffMinutesBeforeDeparture'] == detail['refundPolicy']['cutoffMinutesBeforeDeparture']
        assert Decimal(str(final['totalAmount'])) == Decimal(str(body['totalAmount']))
        inventory = json.loads(sql('inventory_db', "SELECT json_agg(t) FROM (SELECT status FROM reservations WHERE order_id='" + oid + "') t;"))
        assert len(inventory) == 1 and inventory[0]['status'] == 'CONFIRMED'
        deadline = time.monotonic() + 30
        while True:
            status, notifications = self.http('/api/notifications')
            if status == 200 and any(n.get('orderId') == oid for n in notifications):
                break
            assert time.monotonic() < deadline, 'confirmation_notification'
            time.sleep(.5)
        proof = {'orderId': oid, 'offerId': offer, 'seats': seats, 'travelDate': travel,
                 'amount': body['totalAmount'], 'status': final['status'], 'notification': True,
                 'provider': self.provider(oid, body['totalAmount'])}
        print(json.dumps({'checkout': offer, 'seats': seats_count, 'status': final['status']}), flush=True)
        return proof

    def refund(self, order):
        status, result = self.http('/api/orders/' + order['orderId'] + '/refund', {}, 'catalog-refund-' + uuid.uuid4().hex)
        if order['offerId'] == 'of-001':
            assert status == 409 and result['code'] == 'OFFER_NOT_REFUNDABLE', ('refund_refusal', status, result.get('code'))
            return {'status': status, 'code': result['code']}
        assert status == 202, ('refund', status, result.get('code'))
        final = self.wait_order(order['orderId'], 'REFUNDED')
        status, availability = self.http('/api/orders/seat-availability?routeId=rt-to-mi-001&travelDate=' + order['travelDate'])
        assert status == 200 and all(any(s['seatId'] == seat and s['available'] for s in availability['seats']) for seat in order['seats'])
        return {'status': final['status'], 'provider': self.provider(order['orderId'], order['amount'], refunded=True)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--refund', action='store_true')
    parser.add_argument('--require-postgres', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    check = Check()
    proof = {'context': h.CONTEXT, 'startedAt': h.now(), 'orders': []}
    selector = h.obj('service', 'catalog')['spec']['selector']
    pods = h.obj('pods', '-l', ','.join(k + '=' + v for k, v in selector.items()))['items']
    proof['catalogPods'] = [p['metadata']['name'] for p in pods]
    proof['catalogImages'] = sorted({next(v for v in p['spec']['containers'] if v['name'] == 'catalog')['image'] for p in pods})
    if args.require_postgres:
        assert pods and all(any(e['name'] == 'CATALOG_STORAGE' and e.get('value') == 'postgres'
            for e in next(v for v in p['spec']['containers'] if v['name'] == 'catalog')['env']) for p in pods), 'Public Service is not using PostgreSQL'
        proof['catalogBackend'] = 'postgres'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        for offer, count in [('of-001', 1), ('of-002', 2)]:
            proof['orders'].append(check.checkout(offer, count))
            args.output.write_text(json.dumps(proof, indent=2) + '\n')
        # Verify the server still rejects a client-supplied lower price before creating an order.
        status, response = check.http('/api/orders', {'routeId': 'rt-to-mi-001', 'offerId': 'of-001',
            'travelDate': (date.today() + timedelta(days=1)).isoformat(), 'seats': ['6D'],
            'totalAmount': .01, 'paymentMethodToken': 'tok_visa'}, 'catalog-price-' + uuid.uuid4().hex)
        assert status == 400 and response['code'] == 'OFFER_PRICE_MISMATCH'
        proof['priceTamperingRejected'] = True
        if args.refund:
            for order in proof['orders']:
                order['refund'] = check.refund(order)
        proof['passed'] = True
    finally:
        proof['finishedAt'] = h.now()
        args.output.write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps({'passed': proof['passed'], 'orders': len(proof['orders']), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
