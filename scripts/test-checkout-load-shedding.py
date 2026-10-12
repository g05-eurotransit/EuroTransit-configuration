#!/usr/bin/env python3
"""Render ingress contracts; --docker also checks actual Traefik refusal/recovery locally."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'traefik:v3.4.3'  # Same version as the AKS gateway; no cluster access.


def render(environment='production', *settings, succeeds=True):
    args = ['helm', 'template', 'eurotransit', str(ROOT / 'charts/eurotransit'),
            '-f', str(ROOT / f'charts/eurotransit/values-{environment}.yaml')]
    for setting in settings:
        args += ['--set', setting]
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    assert (result.returncode == 0) == succeeds, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d] if succeeds else []


def contracts():
    for env in ('kind', 'production'):
        disabled = render(env)
        assert not any(d['metadata']['name'] == 'eurotransit-checkout-rate-limit' for d in disabled)
        for progressive in ('false', 'true'):
            docs = render(env, 'ingress.checkoutRateLimit.enabled=true',
                          f'progressiveDelivery.enabled={progressive}',
                          'ingress.localhost.enabled=true', 'ingress.forwardAuth.enabled=true')
            route = next(d for d in docs if d['kind'] == 'IngressRoute')['spec']['routes']
            limited = [r for r in route if any(m['name'] == 'eurotransit-checkout-rate-limit'
                                               for m in r.get('middlewares', []))]
            assert len(limited) == 2
            for r in limited:
                assert 'Method(`POST`)' in r['match'] and 'PathPrefix' not in r['match']
                assert 'Path(`/api/orders`)' in r['match'] and 'Path(`/api/orders/`)' in r['match']
                assert r['priority'] == 1000
                assert [m['name'] for m in r['middlewares']] == [
                    'eurotransit-secure-headers', 'eurotransit-checkout-rate-limit', 'eurotransit-forward-auth']
                assert r['services'][0]['name'] == ('orders-weighted' if progressive == 'true' else 'orders')
            middleware = next(d for d in docs if d['metadata']['name'] == 'eurotransit-checkout-rate-limit')
            assert middleware['spec']['rateLimit']['sourceCriterion'] == {'requestHost': True}
    for setting in ('average=0', 'average=-1', 'average=1.5', 'burst=0', 'burst=-1',
                    'period=0s', 'period=-1s', 'period=garbage'):
        render('production', 'ingress.checkoutRateLimit.enabled=true',
               'ingress.checkoutRateLimit.' + setting, succeeds=False)
    assert not any(d['kind'] == 'IngressRoute' or d['metadata']['name'] == 'eurotransit-checkout-rate-limit'
                   for d in render('production', 'ingress.enabled=false', 'ingress.checkoutRateLimit.enabled=true'))
    print('PASS: route scope, localhost, auth, stable/canary routing, disabled defaults and invalid values')


def local_proxy(progressive):
    class Backend(BaseHTTPRequestHandler):
        posts = 0

        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.reply(200)

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            Backend.posts += 1
            self.reply(202)

        def reply(self, status):
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'backend': True}).encode())

    backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    docs = render('production', 'global.domain=checkout.test', 'ingress.checkoutRateLimit.enabled=true',
                  'ingress.checkoutRateLimit.average=1', 'ingress.checkoutRateLimit.period=2s',
                  'ingress.checkoutRateLimit.burst=1', f'progressiveDelivery.enabled={str(progressive).lower()}')
    ingress = next(d for d in docs if d['kind'] == 'IngressRoute')
    middlewares = {d['metadata']['name']: d['spec'] for d in docs if d['kind'] == 'Middleware'}
    target = {'loadBalancer': {'servers': [{'url': f'http://127.0.0.1:{backend.server_port}'}]}}
    services = {name: target for name in ('frontend', 'catalog', 'orders', 'notifications')}
    services['orders-weighted'] = {'weighted': {'services': [{'name': 'orders', 'weight': 100}]}}
    # Feed the rendered rules/middleware to actual Traefik; local backend replaces Kubernetes Services.
    routers = {f'route-{i}': {'rule': r['match'], 'priority': r.get('priority', 0),
               'entryPoints': ['test'], 'middlewares': [m['name'] for m in r.get('middlewares', [])],
               'service': r['services'][0]['name']} for i, r in enumerate(ingress['spec']['routes'])}
    name = 'et-shedding-test-' + uuid.uuid4().hex[:12]
    try:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'dynamic.yaml'
            path.write_text(yaml.safe_dump({'http': {'routers': routers, 'middlewares': middlewares, 'services': services}}))
            subprocess.run(['docker', 'run', '--rm', '-d', '--name', name, '--network', 'host',
                            '--memory', '128m', '--cpus', '0.5', '-v', f'{path}:/etc/traefik/dynamic.yaml:ro',
                            IMAGE, f'--entrypoints.test.address=127.0.0.1:{port}',
                            '--providers.file.filename=/etc/traefik/dynamic.yaml'],
                           check=True, capture_output=True, timeout=120)

            def request(method, path):
                req = Request(f'http://127.0.0.1:{port}{path}', method=method,
                              headers={'Host': 'checkout.test'}, data=b'{}' if method == 'POST' else None)
                try:
                    with urlopen(req, timeout=3) as response:
                        return response.status
                except HTTPError as error:
                    return error.code

            deadline = time.monotonic() + 15
            while True:
                try:
                    if request('GET', '/api/catalog/routes') == 200:
                        break
                except (URLError, TimeoutError):
                    pass
                assert time.monotonic() < deadline, 'Traefik did not become ready'
                time.sleep(0.1)
            assert request('POST', '/api/orders') == 202
            before = Backend.posts
            assert request('POST', '/api/orders') == 429
            assert request('POST', '/api/orders/') == 429
            assert Backend.posts == before, 'Refused checkout reached backend'
            for path in ('/api/catalog/routes', '/api/orders/example', '/api/orders/seat-availability'):
                assert request('GET', path) == 200, path
            assert request('POST', '/api/orders/example/refund') == 202
            time.sleep(2.2)
            assert request('POST', '/api/orders') == 202, 'Checkout did not recover'
            print(f'PASS: actual Traefik 429 before backend, unaffected reads/refund, recovery; progressive={progressive}')
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=15)
        backend.shutdown()
        backend.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', action='store_true')
    args = parser.parse_args()
    contracts()
    if args.docker:
        local_proxy(False)
        local_proxy(True)
