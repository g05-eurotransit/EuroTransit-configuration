#!/usr/bin/env python3
"""Operator-owned EuroTransit runner. No credentials in command arguments or artifacts."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import uuid
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen


def command(argv, data=None, env=None):
    result = subprocess.run(argv, input=data, text=True, capture_output=True, env=env)
    if result.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(argv[:3]))
    return result.stdout


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')
    path.chmod(0o600)


def utc():
    return datetime.now(timezone.utc)


def quantity(value, cpu=False):
    value = str(value)
    if cpu:
        return float(value[:-1]) if value.endswith('m') else float(value) * 1000
    for suffix, factor in [('Ki', 1/1024), ('Mi', 1), ('Gi', 1024), ('Ti', 1048576)]:
        if value.endswith(suffix):
            return float(value[:-len(suffix)]) * factor
    return float(value) / 1048576


def requests(pod, resource):
    cpu = resource == 'cpu'
    def amount(c):
        return quantity(c.get('resources', {}).get('requests', {}).get(resource, '0'), cpu)
    app = sum(amount(c) for c in pod.get('containers', []))
    sidecars, peak = 0, 0
    for c in pod.get('initContainers', []):
        if c.get('restartPolicy') == 'Always':
            sidecars += amount(c)
            peak = max(peak, sidecars)
        else:
            peak = max(peak, sidecars + amount(c))
    return max(app + sidecars, peak) + quantity(pod.get('overhead', {}).get(resource, '0'), cpu)


def capacity(nodes, pods, metrics, mode, extra_mib=0):
    errors, candidates = [], []
    sampled = {m['metadata']['name']: m for m in metrics['items']}
    saturated = False
    for node in nodes['items']:
        name = node['metadata']['name']
        conditions = {c['type']: c['status'] for c in node['status']['conditions']}
        if conditions.get('Ready') != 'True' or conditions.get('MemoryPressure') == 'True':
            errors.append(name + ': not Ready or MemoryPressure')
        m = sampled.get(name)
        if not m:
            errors.append(name + ': missing metrics'); continue
        age = (utc() - datetime.fromisoformat(m['timestamp'].replace('Z', '+00:00'))).total_seconds()
        if not 0 <= age <= 60:
            errors.append(name + ': stale metrics'); continue
        alloc = node['status']['allocatable']
        used = quantity(m['usage']['memory'])
        available = quantity(alloc['memory'])
        saturated |= used >= available
        scheduled = [p for p in pods['items'] if p['spec'].get('nodeName') == name and p.get('status', {}).get('phase') not in ['Succeeded', 'Failed']]
        mem_req = sum(requests(p['spec'], 'memory') for p in scheduled)
        cpu_req = sum(requests(p['spec'], 'cpu') for p in scheduled)
        tolerated = all(t.get('effect') not in ['NoSchedule', 'NoExecute'] for t in node['spec'].get('taints', []))
        if not node['spec'].get('unschedulable') and tolerated and used + 256 + extra_mib + 128 <= available and mem_req + 128 <= available and cpu_req + 50 <= quantity(alloc['cpu'], True):
            candidates.append(name)
    for pod in pods['items']:
        if pod.get('status', {}).get('phase') in ['Succeeded', 'Failed']:
            continue
        for state in pod.get('status', {}).get('containerStatuses', []):
            prior = state.get('lastState', {}).get('terminated', {})
            if prior.get('reason') == 'OOMKilled' and prior.get('finishedAt'):
                age = (utc() - datetime.fromisoformat(prior['finishedAt'].replace('Z', '+00:00'))).total_seconds()
                if age <= 600:
                    errors.append(pod['metadata']['name'] + ': recent OOMKilled')
            if state.get('state', {}).get('terminated', {}).get('reason') == 'OOMKilled' or state.get('state', {}).get('waiting', {}).get('reason') == 'CrashLoopBackOff':
                errors.append(pod['metadata']['name'] + ': unhealthy container')
    if mode == 'job' and not candidates:
        errors.append('No node has room for runner limit + 128Mi safety margin')
    return {'mode': mode, 'errors': errors, 'eligibleNodes': candidates, 'saturated': saturated, 'faultsPermitted': not errors and not saturated and bool(candidates)}


def fixture_keys(value):
    if value.get('version') != 1 or not value.get('fixtures'):
        raise ValueError('Expected version 1 and nonempty fixtures')
    slots = set()
    for f in value['fixtures']:
        slot = (f['routeId'], f['travelDate'], f['seatId'])
        datetime.strptime(f['travelDate'], '%Y-%m-%d')
        if slot in slots:
            raise ValueError('Duplicate fixture slot')
        slots.add(slot)
    return sorted(slots)


def parse_results(log, run_id):
    rows = []
    for line in log.splitlines():
        # k6 wraps console.log in level=info msg="..."; also support raw stdout.
        if 'ET_RESULT ' not in line:
            continue
        marker = line.index('ET_RESULT ')
        payload = line[marker + len('ET_RESULT '):]
        if marker and line[marker - 1] == '"':
            decoder = json.JSONDecoder()
            wrapped, _ = decoder.raw_decode(line[marker - 1:])
            payload = wrapped[len('ET_RESULT '):]
        event, _ = json.JSONDecoder().raw_decode(payload)
        if event.get('runId') != run_id:
            raise ValueError('Unexpected runId in results')
        rows.append(event)
    return rows


def bounded_process(argv, env, log, deadline, container_name=None):
    process = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        return process.wait(timeout=deadline)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as interruption:
        if container_name:
            # Stop only this run's named container. Failure leaves the lock retained.
            command(['docker', 'kill', container_name])
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        return 130 if isinstance(interruption, KeyboardInterrupt) else 124


class Operator:
    def __init__(self, args):
        self.args = args
        self.prefix = ['kubectl', '--context', args.context, '-n', args.namespace, '--request-timeout=15s']

    def k(self, *argv, data=None):
        return command(self.prefix + list(argv), data)

    def get(self, *argv):
        return json.loads(self.k('get', *argv, '-o', 'json'))

    def preflight(self, mode):
        report = capacity(self.get('nodes'), self.get('pods', '-A'), json.loads(self.k('get', '--raw', '/apis/metrics.k8s.io/v1beta1/nodes')), mode, self.args.extra_memory_mib)
        report.update({'status': 'passed' if not report['errors'] else 'blocked', 'context': self.args.context, 'namespace': self.args.namespace, 'runId': self.args.run_id, 'timestamp': utc().isoformat(), 'extraMemoryMiB': self.args.extra_memory_mib})
        return report

    def cm(self, name, data):
        self.k('create', '-f', '-', data=json.dumps({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name, 'labels': {'eurotransit.io/load-test': 'true'}}, 'data': data}))

    def db(self, database, sql):
        pods = self.get('pods', '-l', 'cnpg.io/cluster=eurotransit-postgres')['items']
        primaries = [p for p in pods if p['metadata'].get('labels', {}).get('cnpg.io/instanceRole', p['metadata'].get('labels', {}).get('role')) == 'primary']
        if len(primaries) == 1:
            primary = primaries[0]
        else:
            current = self.get('cluster.postgresql.cnpg.io', 'eurotransit-postgres')['status']['currentPrimary']
            primary = next(p for p in pods if p['metadata']['name'] == current)
        raw = self.k('exec', '-i', primary['metadata']['name'], '-c', 'postgres', '--', 'psql', '-X', '-q', '-t', '-A', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-d', database, data='BEGIN READ ONLY; SET LOCAL statement_timeout=10000; ' + sql + '; COMMIT;')
        return json.loads(raw.strip())

    def available_fixtures(self, slots):
        predicates = []
        def literal(v):
            return "'" + v.replace("'", "''") + "'"
        for route, date, seat in slots:
            predicates.append('(route_id=' + literal(route) + ' AND travel_date=' + literal(date) + '::date AND seat_id=' + literal(seat) + " AND status='AVAILABLE')")
        count = self.db('inventory_db', 'SELECT count(*) FROM seats WHERE ' + ' OR '.join(predicates))
        if count != len(slots):
            raise ValueError('Fixtures missing or consumed; no database cleanup is allowed')

    def snapshot(self, output, name):
        pods = self.get('pods')['items']
        write(output / (name + '-pods.json'), [{'name': p['metadata']['name'], 'uid': p['metadata']['uid'], 'node': p['spec'].get('nodeName'), 'images': [c['image'] for c in p['spec']['containers']], 'status': p.get('status', {})} for p in pods])

    def extract(self, output, run_id):
        events = parse_results((output / 'runner.log').read_text(), run_id)
        write(output / 'events.json', events)
        orders = [e for e in events if e['type'] == 'order_result']
        write(output / 'orders.json', orders)
        (output / 'orders.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in orders))
        summaries = [e for e in events if e['type'] == 'run_summary']
        finished = [e for e in events if e['type'] == 'runner_finished']
        summary_path = output / 'summary.json'
        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
            if summary.get('runId') != run_id:
                raise ValueError('Unexpected summary runId')
        else:
            summary = summaries[-1] if summaries else {'runId': run_id, 'extraction': 'INCOMPLETE'}
        summary['passed'] = bool(finished and finished[-1].get('passed') and summary.get('passed', True))
        write(summary_path, summary)
        return orders

    def run(self):
        a = self.args
        output = a.output.resolve()
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        fixtures = json.loads(a.fixtures.read_text())
        slots = fixture_keys(fixtures)
        if a.scenario == 'baseline' and a.max_attempts > len(slots):
            raise ValueError('MAX_ATTEMPTS exceeds unique fixture capacity')
        if a.image and not re.search(r'(:[a-f0-9]{7,40}|@sha256:[a-f0-9]{64})$', a.image):
            raise ValueError('Harness image must be pinned to commit SHA or digest')
        if a.mode == 'workstation':
            command(['docker', 'info']) if a.image else command(['k6', 'version'])
        report = self.preflight(a.mode)
        write(output / 'preflight.json', report)
        if report['errors']:
            raise RuntimeError('; '.join(report['errors']))
        if a.mode == 'workstation' and report['saturated'] and (a.scenario != 'baseline' or a.max_attempts > 20 or a.max_vus != 1):
            raise RuntimeError('Saturated cluster permits only <=20 sequential baseline attempts; no faults')
        if a.mode == 'workstation' and a.max_vus == 1 and a.scenario == 'baseline':
            print('Workstation baseline; saturation=' + str(report['saturated']) + '; faultsPermitted=' + str(report['faultsPermitted']))
        deployments = self.get('deployments')['items']
        for service in ['catalog', 'orders', 'inventory', 'payments']:
            deployment = next(d for d in deployments if d['metadata']['name'] == service)
            if deployment.get('status', {}).get('availableReplicas', 0) < 1:
                raise ValueError(service + ': no available replica')
        self.available_fixtures(slots)
        self.snapshot(output, 'before')
        env = os.environ.copy()
        if a.mode == 'workstation' and not env.get('CLIENT_SECRET'):
            raise ValueError('Provide CLIENT_SECRET in environment (never CLI)')
        run_id = a.run_id or 'et-' + uuid.uuid4().hex[:16]
        job_name = 'et-load-' + run_id
        if not re.fullmatch('[a-z0-9][a-z0-9-]{0,40}', run_id):
            raise ValueError('RUN_ID must be a short Kubernetes-safe identifier')
        self.cm('eurotransit-load-test-lock', {'runId': run_id, 'mode': a.mode, 'jobName': job_name, 'startedAt': utc().isoformat()})
        terminal = False
        try:
            for slot in slots:
                name = 'et-fixture-' + hashlib.sha256(json.dumps(slot).encode()).hexdigest()[:24]
                self.cm(name, {'runId': run_id, 'fixture': json.dumps(slot)})
            write(output / 'fixtures.json', fixtures)
            meta = {'runId': run_id, 'mode': a.mode, 'scenario': a.scenario, 'startedAt': utc().isoformat(), 'harness': a.image or str(a.harness), 'maxAttempts': a.max_attempts}
            write(output / 'run.json', meta)
            config = {'PUBLIC_URL': a.public_url, 'TOKEN_URL': a.issuer.rstrip('/') + '/protocol/openid-connect/token', 'CLIENT_ID': 'eurotransit-load-test', 'RUN_ID': run_id, 'SCENARIO': a.scenario, 'MAX_ATTEMPTS': str(a.max_attempts), 'MAX_VUS': str(a.max_vus), 'POLL_TIMEOUT_SECONDS': '30', 'OUTPUT_DIR': str(output), 'FIXTURES_FILE': str(a.fixtures.resolve())}
            if a.mode == 'workstation':
                env.update(config)
                with (output / 'runner.log').open('w') as log:
                    argv = ['docker', 'run', '--rm', '--name', job_name, '--user', str(os.getuid()) + ':' + str(os.getgid()), '--network', 'host', '--memory', '256m', '--cpus', '0.25', '--mount', 'type=bind,src=' + str(a.fixtures.resolve()) + ',dst=/fixtures/fixtures.json,readonly', '--mount', 'type=bind,src=' + str(output) + ',dst=/results'] if a.image else ['python3', str(a.harness)]
                    if a.image:
                        container_env = dict(config, OUTPUT_DIR='/results', FIXTURES_FILE='/fixtures/fixtures.json')
                        env.update(container_env)
                        for key in list(container_env) + ['CLIENT_SECRET']:
                            argv += ['--env', key]
                        argv += [a.image]
                    code = bounded_process(argv, env, log, a.deadline, job_name if a.image else None)
                terminal = True
            else:
                if not re.search(r'(:[a-f0-9]{7,40}|@sha256:[a-f0-9]{64})$', a.image):
                    raise ValueError('Job image must be pinned to commit SHA or digest')
                template = self.get('cronjob', 'eurotransit-load-tests')['spec']['jobTemplate']['spec']
                template['activeDeadlineSeconds'] = a.deadline
                pod = template['template']['spec']
                container = pod['containers'][0]
                container['image'] = a.image
                config.update({'OUTPUT_DIR': '/results', 'FIXTURES_FILE': '/fixtures/fixtures.json'})
                container['env'] = [{'name': k, 'value': v} for k, v in config.items()] + [{'name': 'CLIENT_SECRET', 'valueFrom': {'secretKeyRef': {'name': 'eurotransit-load-test-credentials', 'key': 'client-secret'}}}]
                claim = 'et-run-' + run_id
                self.cm(claim, {'fixtures.json': json.dumps(fixtures)})
                pod['volumes'][0]['configMap']['name'] = claim
                self.k('create', '-f', '-', data=json.dumps({'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': job_name}, 'spec': template}))
                import time
                stop = time.monotonic() + a.deadline + 60
                while time.monotonic() < stop:
                    status = self.get('job', job_name).get('status', {})
                    if status.get('succeeded') or status.get('failed'):
                        terminal = True
                        code = 0 if status.get('succeeded') else 1
                        break
                    time.sleep(2)
                if not terminal:
                    raise RuntimeError('Job not terminal; lock retained, recover explicitly')
                (output / 'runner.log').write_text(self.k('logs', 'job/' + job_name))
                write(output / 'job.json', self.get('job', job_name))
            self.snapshot(output, 'after')
            self.extract(output, run_id)
            meta.update({'finishedAt': utc().isoformat(), 'exitCode': code})
            write(output / 'run.json', meta)
            return code
        finally:
            if terminal:
                self.k('delete', 'configmap', 'eurotransit-load-test-lock')

    def collect(self):
        output = self.args.output
        meta = json.loads((output / 'run.json').read_text())
        self.telemetry(output, meta)
        rows = self.extract(output, meta['runId'])
        ids = sorted({str(uuid.UUID(r['orderId'])) for r in rows if r.get('orderId')})
        evidence = {'runId': meta['runId'], 'extraction': 'INCOMPLETE', 'orders': [], 'reservations': [], 'payments': [], 'inventory': [], 'outboxEvents': [], 'providerEffects': {'extraction': 'INCOMPLETE', 'authorizations': []}}
        if not ids:
            write(output / 'evidence.json', evidence)
            raise ValueError('No attributed order IDs')
        # UUID validation prevents SQL injection. SELECT-only read-only transaction.
        literals = ','.join("'" + x + "'" for x in ids)
        query = self.db
        fixture_scope = []
        def literal(value):
            if not isinstance(value, str):
                raise ValueError('Invalid ledger fixture')
            return "'" + value.replace("'", "''") + "'"
        for row in rows:
            f = row['fixture']
            fixture_scope.append('(route_id=' + literal(f['routeId']) + ' AND travel_date=' + literal(f['travelDate']) + '::date AND seat_id=' + literal(f['seatId']) + ')')
        def select(table, fields, where):
            projection = ','.join("'" + f + "',to_jsonb(t)->'" + f + "'" for f in fields)
            return 'SELECT COALESCE(jsonb_agg(jsonb_build_object(' + projection + ")), '[]'::jsonb) FROM " + table + ' t WHERE ' + where
        try:
            evidence['orders'] = query('orders_db', select('orders', ['id', 'status', 'route_id', 'travel_date', 'seats', 'total_amount', 'currency', 'failure_code', 'reservation_id'], 'id::text IN (' + literals + ')'))
            evidence['reservations'] = query('inventory_db', select('reservations', ['reservation_id', 'order_id', 'route_id', 'travel_date', 'status', 'expires_at'], 'order_id::text IN (' + literals + ')'))
            evidence['inventory'] = query('inventory_db', select('seats', ['route_id', 'travel_date', 'seat_id', 'status', 'reservation_id'], ' OR '.join(fixture_scope)))
            evidence['payments'] = query('payments_db', select('payment_authorizations', ['id', 'order_id', 'amount', 'currency', 'status', 'provider_reference', 'error_code', 'idempotency_key'], 'order_id::text IN (' + literals + ')'))
            # Provider references are identifiers; hash before artifact export.
            for row in evidence['payments']:
                ref = row.pop('provider_reference', None)
                row['provider_reference_hash'] = hashlib.sha256(ref.encode()).hexdigest() if ref else None
            canonical = []
            for service in ['orders']:
                sql = select('outbox_events', ['id', 'aggregate_id', 'type', 'payload', 'created_at'], "type = 'order-placed' AND (aggregate_id IN (" + literals + ") OR payload->>'orderId' IN (" + literals + '))')
                for row in query(service + '_db', sql):
                    row['source'] = service
                    if any('token' in k.lower() or 'secret' in k.lower() for k in row['payload']):
                        raise ValueError('Unexpected credential field in canonical event; not exported')
                    canonical.append(dict(row))
                    # Replay is not authorized by this collector. Preserve event identity,
                    # remove payment tokens and recipient/principal data from evidence.
                    row['payload'] = {k: v for k, v in row['payload'].items() if k in ['eventId', 'orderId', 'reservationId', 'routeId', 'seats', 'travelDate', 'amount', 'totalAmount', 'status', 'reason', 'failureCode', 'offerId']}
                    evidence['outboxEvents'].append(row)
            write(output / 'canonical-events.json', {'runId': meta['runId'], 'events': canonical})
            if self.args.provider_evidence:
                audit = json.loads(self.args.provider_evidence.read_text())
                if audit.get('runId') != meta['runId'] or audit.get('extraction') != 'COMPLETE':
                    raise ValueError('Provider audit runId/extraction mismatch')
                safe = []
                for row in audit['authorizations']:
                    if row['order_id'] not in ids:
                        raise ValueError('Provider audit contains unrelated order')
                    ref = row['provider_reference']
                    if not isinstance(ref, str) or not ref or row['status'] not in ['SUCCEEDED', 'FAILED', 'REFUNDED']:
                        raise ValueError('Invalid provider audit row')
                    safe.append({'order_id': row['order_id'], 'provider_reference_hash': hashlib.sha256(ref.encode()).hexdigest(), 'status': row['status'], 'amount': row['amount'], 'currency': row['currency']})
                evidence['providerEffects'] = {'extraction': 'COMPLETE', 'authorizations': safe}
            evidence['extraction'] = 'COMPLETE'
        finally:
            write(output / 'evidence.json', evidence)

    def telemetry(self, output, meta):
        result = {'runId': meta['runId'], 'extraction': 'INCOMPLETE', 'attribution': 'namespace_and_time_window_not_exclusive_run', 'status': 'NOT_VERIFIED', 'missingSeries': [], 'queries': {}}
        if not getattr(self.args, 'prometheus_url', None):
            result['reason'] = 'prometheus_url_not_supplied'
            write(output / 'telemetry.json', result)
            return
        url = urlsplit(self.args.prometheus_url)
        if url.scheme not in ['http', 'https'] or url.username or url.password:
            raise ValueError('Prometheus URL must not contain credentials')
        namespace = json.dumps(self.args.namespace)
        queries = {
            'confirmed': 'orders_checkout_completed_total{namespace=' + namespace + '}',
            'failed': 'orders_checkout_failed_total{namespace=' + namespace + '}',
            'stage_duration_buckets': 'orders_checkout_duration_seconds_bucket{namespace=' + namespace + '}',
            'e2e_duration_buckets': 'orders_checkout_e2e_duration_seconds_bucket{namespace=' + namespace + '}',
            'dead_letters': 'orders_events_dlt_total{namespace=' + namespace + '}',
            'acceptance_count': 'http_server_requests_seconds_count{namespace=' + namespace + ',application="orders",method="POST",uri="/api/orders"}',
            'acceptance_sum': 'http_server_requests_seconds_sum{namespace=' + namespace + ',application="orders",method="POST",uri="/api/orders"}',
            'breaker_state': 'resilience4j_circuitbreaker_state{namespace=' + namespace + '}',
            'kafka_lag': 'kafka_consumergroup_lag{namespace=' + namespace + '}',
        }
        try:
            for name, query in queries.items():
                params = urlencode({'query': query, 'start': meta['startedAt'], 'end': meta.get('finishedAt', utc().isoformat()), 'step': '30s'})
                with urlopen(self.args.prometheus_url.rstrip('/') + '/api/v1/query_range?' + params, timeout=10) as response:
                    data = json.load(response)
                if data.get('status') != 'success':
                    raise ValueError('Prometheus query failed')
                result['queries'][name] = data['data']
                if not data['data'].get('result'):
                    result['missingSeries'].append(name)
            if not result['missingSeries']:
                result['extraction'] = 'COMPLETE'
                result['status'] = 'COLLECTED'
            else:
                result['reason'] = 'metric_series_missing'
        except (OSError, ValueError) as exc:
            result['reason'] = 'sampling_failed:' + type(exc).__name__
            print('Telemetry sampling failed; evidence remains NOT_VERIFIED', file=sys.stderr)
        finally:
            write(output / 'telemetry.json', result)

    def recover(self):
        lock = self.get('configmap', 'eurotransit-load-test-lock')['data']
        if lock['mode'] == 'workstation':
            raise ValueError('Workstation lock requires operator confirmation process ended; use kubectl delete after verification')
        result = json.loads(self.k('get', 'job', lock['jobName'], '--ignore-not-found', '-o', 'json') or '{}')
        status = result.get('status', {})
        if result and not (status.get('succeeded') or status.get('failed')):
            raise ValueError('Job still running; lock retained')
        self.k('delete', 'configmap', 'eurotransit-load-test-lock')


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['preflight', 'run', 'collect', 'recover'])
    p.add_argument('--context', required=True)
    p.add_argument('--namespace', default='eurotransit')
    p.add_argument('--mode', choices=['workstation', 'job'], default='workstation')
    p.add_argument('--output', type=Path, default=Path('load-results'))
    p.add_argument('--fixtures', type=Path)
    p.add_argument('--harness', type=Path)
    p.add_argument('--image', default='')
    p.add_argument('--prometheus-url', help='Optional operator port-forward URL for namespace/time-window metrics')
    p.add_argument('--provider-evidence', type=Path, help='Read-only provider audit supplied separately; never infer provider effects from DB rows')
    p.add_argument('--public-url')
    p.add_argument('--issuer')
    p.add_argument('--run-id')
    p.add_argument('--scenario', default='baseline')
    p.add_argument('--max-attempts', type=int, default=20)
    p.add_argument('--max-vus', type=int, default=1)
    p.add_argument('--deadline', type=int, default=600)
    p.add_argument('--extra-memory-mib', type=int, default=0, help='Additional peak fault/rollout memory; never lowers safety margin')
    a = p.parse_args()
    if not 1 <= a.max_vus <= 4 or not 1 <= a.max_attempts or not 60 <= a.deadline <= 600 or a.extra_memory_mib < 0:
        p.error('Invalid bounded runner settings')
    if a.action == 'run' and (not a.fixtures or not a.public_url or not a.issuer or (a.mode == 'workstation' and not (a.harness or a.image))):
        p.error('run requires fixtures/public-url/issuer and workstation harness or image')
    op = Operator(a)
    try:
        if a.action == 'preflight':
            report = op.preflight(a.mode)
            print(json.dumps(report, indent=2)); return bool(report['errors'])
        if a.action == 'run': return op.run()
        if a.action == 'collect': op.collect()
        if a.action == 'recover': op.recover()
    except (RuntimeError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(str(e), file=sys.stderr); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
