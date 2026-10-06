#!/usr/bin/env python3
"""Meaningful image-level test: expiry after client exit, neutral restart, denied renewal."""
import json
from pathlib import Path
import subprocess
import tempfile
import time


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.PIPE).strip()


def request(container, path, method='GET', body=None, port=8474):
    code = "import urllib.request,json; " + (
        "r=urllib.request.Request(%r,data=%r,method=%r,headers={'Content-Type':'application/json'}); "
        "print(urllib.request.urlopen(r,timeout=3).read().decode())" %
        (f'http://127.0.0.1:{port}{path}', None if body is None else json.dumps(body).encode(), method))
    return docker('exec', container, 'python3', '-c', code)


def main():
    docker('build', '-t', 'eurotransit-payments-fault-proxy:issue47', 'platform/reliability/payments-proxy')
    with tempfile.TemporaryDirectory(prefix='et-proxy-') as tmp:
        Path(tmp).chmod(0o755)
        Path(tmp, 'proxies.json').write_text(json.dumps([
            {'name': 'payments', 'listen': '0.0.0.0:8080', 'upstream': '127.0.0.1:9000', 'enabled': True}]))
        container = docker('run', '-d', '--network', 'none', '--read-only', '--memory', '64m',
                           '--cpus', '0.1', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                           '--mount', f'type=bind,source={tmp},target=/config,readonly',
                           'eurotransit-payments-fault-proxy:issue47')
        try:
            for _ in range(30):
                try:
                    request(container, '/health')
                    break
                except subprocess.CalledProcessError:
                    time.sleep(.2)
            else:
                raise AssertionError('not healthy')
            code = """
import urllib.request, urllib.error, json, time, http.server, threading

def req(path, method='GET', body=None, port=8474):
    r=urllib.request.Request('http://127.0.0.1:%s%s' % (port,path), data=None if body is None else json.dumps(body).encode(),method=method,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(r,timeout=3) as f: return json.load(f)
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
server=http.server.ThreadingHTTPServer(('127.0.0.1',9000),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
assert req('/',port=8080)['ok']
req('/lease','POST',{'seconds':15})
assert len(req('/proxies/payments',port=8475)['toxics'])==1
start=time.monotonic()
# Faulted response exceeds the Orders3s timeout and remains below a6s test bound.
r=urllib.request.urlopen('http://127.0.0.1:8080/',timeout=6)
assert json.load(r)['ok']
assert time.monotonic()-start>=3.8
for body in ({'seconds':176},{'seconds':True},{'seconds':0},{'seconds':15}):
    try: req('/lease','POST',body)
    except urllib.error.HTTPError as e: assert e.code in (400,409)
    else: raise AssertionError('invalid or renewal accepted')
"""
            docker('exec', container, 'python3', '-c', code)
            # The client process has exited; the in-pod watchdog must remove the toxic.
            time.sleep(16)
            assert json.loads(request(container, '/proxies/payments', port=8475))['toxics'] == []
            request(container, '/lease', 'POST', {'seconds': 175})
            docker('restart', container)
            for _ in range(30):
                try:
                    request(container, '/health')
                    break
                except subprocess.CalledProcessError:
                    time.sleep(.2)
            assert json.loads(request(container, '/proxies/payments', port=8475))['toxics'] == []
            request(container, '/lease', 'POST', {'seconds': 10})
            request(container, '/lease', 'DELETE')
            assert json.loads(request(container, '/proxies/payments', port=8475))['toxics'] == []
            print('PASS: independent expiry, invalid bounds, no renewal, neutral restart, explicit reset; 64Mi limit')
        except Exception:
            print(docker('logs', container))
            raise
        finally:
            docker('rm', '-f', container)


if __name__ == '__main__':
    main()
