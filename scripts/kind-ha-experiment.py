#!/usr/bin/env python3
"""Bounded Kind-only baseline / worker interruption; secrets stay in memory.

Reuses the existing checkout harness, SELECT-only collector and provider verifier.
Raw artifacts are private and remain below ignored load-results/.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import ssl
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = 'kind-eurotransit'
BASE = 'https://eurotransit.local'
ISSUER = 'https://keycloak.eurotransit.local/realms/eurotransit'
EXPECTED_SLOTS = {'orders_outbox', 'inventory_outbox', 'payments_outbox'}
TLS = ssl._create_unverified_context()  # Fixed local self-signed endpoints only.


def now():
    return datetime.now(timezone.utc).isoformat()


def command(argv, data=None, timeout=25):
    p = subprocess.run(argv, input=data, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError('Command failed (exit ' + str(p.returncode) + '): ' + ' '.join(argv[:4]))
    return p.stdout


def k(*args, data=None, timeout=25):
    return command(['kubectl', '--context', CONTEXT, '--request-timeout=15s', '-n', 'eurotransit', *args], data, timeout)


def obj(*args):
    return json.loads(k('get', *args, '-o', 'json'))


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')
    path.chmod(0o600)


def secret(name, key):
    return base64.b64decode(obj('secret', name)['data'][key]).decode()


def memory_mib():
    values = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
    return {'availableMiB': round(values['MemAvailable'] / 1024, 2),
            'swapUsedMiB': round((values['SwapTotal'] - values['SwapFree']) / 1024, 2)}


def unavailable(state, mode):
    return state['Paused'] if mode == 'worker-freeze' else not state['Running']


def standby_slots_ready(slots):
    # The extension temporarily owns slots while advancing them on a standby.
    # That is not an active Debezium consumer. Require initialized LSNs anyway.
    return ({s['slot_name'] for s in slots} == EXPECTED_SLOTS
            and all(s.get('restart_lsn') and s.get('confirmed_flush_lsn')
                    and (not s['active'] or s.get('active_backend_type') == 'pg_failover_slots worker')
                    for s in slots))


def kafka_diagnostic(tool, args):
    """Give diagnostic JVMs their own memory budget, never the broker's cgroup."""
    assert tool in ('kafka-topics.sh', 'kafka-consumer-groups.sh')
    broker = obj('pod', 'eurotransit-kafka-dual-role-1')
    name = 'et-ha-kafka-check-' + uuid.uuid4().hex[:8]
    pod = {'apiVersion':'v1','kind':'Pod','metadata':{'name':name}, 'spec':{
        'restartPolicy':'Never','activeDeadlineSeconds':75,'automountServiceAccountToken':False,
        'nodeSelector':{'kubernetes.io/hostname':broker['spec']['nodeName']},
        'securityContext':{'runAsNonRoot':True,'seccompProfile':{'type':'RuntimeDefault'}},
        'containers':[{'name':'diagnostic','image':broker['spec']['containers'][0]['image'],
                       'imagePullPolicy':'IfNotPresent','command':['/opt/kafka/bin/'+tool], 'args':args,
                       'env':[{'name':'KAFKA_HEAP_OPTS','value':'-Xms16m -Xmx96m'}],
                       'resources':{'requests':{'cpu':'50m','memory':'128Mi'},'limits':{'cpu':'1','memory':'256Mi'}},
                       'securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}}}]}}
    k('create','-f','-',data=json.dumps(pod))
    try:
        deadline = time.monotonic() + 80
        while time.monotonic() < deadline:
            status = obj('pod', name)['status']
            if status['phase'] == 'Succeeded':
                return k('logs', name)
            assert status['phase'] != 'Failed', 'Isolated Kafka diagnostic failed'
            time.sleep(1)
        raise TimeoutError('Isolated Kafka diagnostic deadline')
    finally:
        k('delete','pod',name,'--wait=false')


def request(url, data=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    with urlopen(Request(url, data=data, headers=headers), context=TLS, timeout=12) as response:
        return json.load(response)


def token():
    body = urlencode({'grant_type': 'client_credentials', 'client_id': 'eurotransit-load-test',
                      'client_secret': secret('eurotransit-load-test-credentials', 'client-secret')}).encode()
    req = Request(ISSUER + '/protocol/openid-connect/token', data=body,
                  headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urlopen(req, context=TLS, timeout=15) as response:
        return json.load(response)['access_token']


def sql(pod, query):
    # All experiment SQL is a read-only transaction.
    return k('exec', '-i', pod, '-c', 'postgres', '--', 'psql', '-X', '-q', '-t', '-A',
             '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-d', 'postgres',
             data='BEGIN READ ONLY; SET LOCAL statement_timeout=10000; ' + query + '; COMMIT;')


def preflight(fault):
    inotify = {name:int(Path('/proc/sys/fs/inotify', name).read_text())
               for name in ('max_user_instances', 'max_user_watches')}
    assert inotify['max_user_instances'] >= 512 and inotify['max_user_watches'] >= 524288, 'Kind host inotify limits too low; see runbook'
    nodes = obj('nodes')['items']
    assert len(nodes) == 4 and all(n['metadata']['name'].startswith('eurotransit-') for n in nodes)
    for node in nodes:
        conditions = {c['type']: c['status'] for c in node['status']['conditions']}
        assert conditions['Ready'] == 'True' and conditions['MemoryPressure'] == 'False'
    assert memory_mib()['availableMiB'] >= 1024, 'Host needs at least 1 GiB available before injection'
    pods = obj('pods')['items']
    for name in ('catalog', 'orders', 'inventory', 'payments'):
        ready = [p for p in pods if p['metadata'].get('labels', {}).get('app') == name
                 and not p['metadata'].get('deletionTimestamp')
                 and p['status'].get('phase') == 'Running'
                 and p['status'].get('containerStatuses')
                 and all(c.get('ready') for c in p['status']['containerStatuses'])]
        assert len(ready) == 2 and len({p['spec']['nodeName'] for p in ready}) == 2, name
    for pod in pods:
        for state in pod['status'].get('containerStatuses', []):
            assert state.get('lastState', {}).get('terminated', {}).get('reason') != 'OOMKilled', 'Prior OOM requires review'
    kafka = obj('kafka', 'eurotransit-kafka')
    assert any(c['type'] == 'Ready' and c['status'] == 'True' for c in kafka['status']['conditions'])
    connects = [p for p in pods if p['metadata'].get('labels', {}).get('strimzi.io/name') == 'orders-outbox-connect-connect']
    assert len(connects) == 2 and len({p['spec']['nodeName'] for p in connects}) == 2
    assert all(p['status'].get('phase') == 'Running' and p['status'].get('containerStatuses')
               and all(c.get('ready') for c in p['status']['containerStatuses']) for p in connects), 'Connect workers not ready'
    for connector in obj('kafkaconnector')['items']:
        status = connector['status']['connectorStatus']
        assert status['connector']['state'] == 'RUNNING' and status['tasks']
        assert all(t['state'] == 'RUNNING' for t in status['tasks'])
        live = json.loads(k('exec', connects[0]['metadata']['name'], '--', 'curl', '--max-time', '5', '-fsS',
                            'http://localhost:8083/connectors/' + connector['metadata']['name'] + '/status'))
        assert live['connector']['state'] == 'RUNNING' and live['tasks']
        assert all(t['state'] == 'RUNNING' for t in live['tasks']), 'Live Connect task not running'
    if fault:
        degraded = kafka_diagnostic('kafka-topics.sh',
                     ['--bootstrap-server', 'eurotransit-kafka-kafka-bootstrap:9092', '--describe', '--under-replicated-partitions'])
        assert not degraded.strip(), 'Kafka has under-replicated partitions'
    cluster = obj('cluster.postgresql.cnpg.io', 'eurotransit-postgres')
    assert cluster['status']['readyInstances'] == 3
    assert cluster['spec']['postgresql']['synchronous'] == {'method': 'any', 'number': 1, 'dataDurability': 'required'}
    primary = cluster['status']['currentPrimary']
    database = [p for p in pods if p['metadata'].get('labels', {}).get('cnpg.io/cluster') == 'eurotransit-postgres'
                and p['metadata'].get('labels', {}).get('cnpg.io/podRole') == 'instance']
    assert len(database) == 3 and len({p['spec']['nodeName'] for p in database}) == 3
    # Ready alone does not prove a standby follows the current timeline.
    streaming = json.loads(sql(primary, "SELECT COALESCE(json_agg(t),'[]'::json) FROM (SELECT application_name,state,sync_state,pg_wal_lsn_diff(pg_current_wal_lsn(),replay_lsn) AS replay_lag_bytes FROM pg_stat_replication WHERE application_name LIKE 'eurotransit-postgres-%') t"))
    standby_names = {p['metadata']['name'] for p in database if p['metadata']['name'] != primary}
    assert {s['application_name'] for s in streaming if s['state']=='streaming'} == standby_names, 'Standby not streaming from current primary'
    assert all(s['replay_lag_bytes'] is not None and s['replay_lag_bytes'] <= 1048576 for s in streaming), 'Standby replay lag exceeds 1 MiB'
    target = next(p for p in database if p['metadata']['name'] == primary)['spec']['nodeName']
    assert target != 'eurotransit-control-plane'
    container = json.loads(command(['docker', 'inspect', target]))[0]
    assert container['Config']['Labels']['io.x-k8s.kind.cluster'] == 'eurotransit'
    assert container['Config']['Labels']['io.x-k8s.kind.role'] == 'worker'
    assert container['State']['Running'] and not container['State']['Paused']
    # Guard against an unrelated kubeconfig entry that happens to have the same context name.
    assert next(n for n in nodes if n['metadata']['name'] == target)['status']['addresses']
    docker_ip = container['NetworkSettings']['Networks']['kind']['IPAddress']
    assert any(a['address'] == docker_ip for a in next(n for n in nodes if n['metadata']['name'] == target)['status']['addresses'])
    configured_barrier = cluster['spec']['postgresql']['parameters']['pg_failover_slots.standby_slot_names']
    expected_barrier = {'_cnpg_' + p['metadata']['name'].replace('-','_') for p in database}
    if fault:
        assert set(configured_barrier.split(',')) == expected_barrier, 'CDC barrier does not match current instances; run prepare-cdc'
    slots = {}
    for pod in database:
        name = pod['metadata']['name']
        if name != primary:
            tcp_timeout = sql(name, "SELECT substring(current_setting('primary_conninfo') from 'tcp_user_timeout=''?([0-9]+)')").strip()
            assert tcp_timeout == '5000', 'Standby TCP timeout must be 5000 ms in the HA profile'
        slots[name] = json.loads(sql(name, "SELECT COALESCE(json_agg(t),'[]'::json) FROM (SELECT s.slot_name,s.active,s.restart_lsn::text,s.confirmed_flush_lsn::text,a.backend_type AS active_backend_type FROM pg_replication_slots s LEFT JOIN pg_stat_activity a ON a.pid=s.active_pid WHERE s.slot_type='logical') t"))
        if fault and name == primary:
            assert {s['slot_name'] for s in slots[name] if s['active']} == EXPECTED_SLOTS, 'Primary logical slots not active'
        if fault and name != primary:
            assert standby_slots_ready(slots[name]), 'Standby logical slots not initialized'
    return {'at': now(), 'context': CONTEXT, 'memory': memory_mib(), 'primary': primary,
            'hostInotifyLimits':inotify,
            'target': target, 'containerId': container['Id'], 'slots': slots, 'physicalReplication':streaming, 'cdcBarrier':configured_barrier,
            'affectedPods': [p['metadata']['name'] for p in pods if p['spec'].get('nodeName') == target]}


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def collect(output, provider_key):
    runner = module(ROOT / 'scripts/reliability-runner.py', 'kind_collector')
    args = SimpleNamespace(context=CONTEXT, namespace='eurotransit', output=output,
                           prometheus_url='http://127.0.0.1:19190', provider_evidence=None)
    runner.Operator(args).collect()
    env = os.environ.copy()
    env['STRIPE_SECRET_KEY'] = provider_key
    audit = subprocess.run([sys.executable, str(ROOT / 'scripts/reliability/provider-audit.py'),
                            '--run-dir', str(output)], env=env, cwd=ROOT, timeout=130)
    if audit.returncode == 0:
        args.provider_evidence = output / 'provider-audit.json'
        runner.Operator(args).collect()
    check = subprocess.run([sys.executable, str(ROOT / 'load-tests/verify.py'), '--ledger', str(output / 'orders.jsonl'),
                            '--evidence', str(output / 'evidence.json'), '--output', str(output / 'verification.json')], cwd=ROOT)
    return check.returncode == 0


def final_audit(output, meta, provider_key):
    auth = token()
    rows = [json.loads(line) for line in (output / 'orders.jsonl').read_text().splitlines()]
    deadline = time.monotonic() + 120
    accepted = [r for r in rows if r.get('orderId')]
    while True:
        results = [request(BASE + '/api/orders/' + r['orderId'], token=auth) for r in accepted]
        if all(r.get('status') in ('CONFIRMED', 'FAILED', 'CANCELLED') for r in results) or time.monotonic() >= deadline:
            break
        time.sleep(2)
    dest = output / 'final-audit'
    dest.mkdir(mode=0o700)
    derived_id = meta['runId'] + '-final'
    derived = []
    for row, result in zip(accepted, results):
        value = dict(row, runId=derived_id, sourceRunId=row['runId'], initialClientOutcome=row['outcome'],
                     finalObservedAt=now(), status=result['status'], failureCode=result.get('failureCode'))
        value['outcome'] = 'confirmed' if result['status'] == 'CONFIRMED' else 'terminal_failure' if result['status'] in ('FAILED', 'CANCELLED') else 'timeout'
        derived.append(value)
    save(dest / 'run.json', dict(meta, runId=derived_id, mode='derived-final-state-audit', finishedAt=now(),
                                originalClientOutcomesPreserved=True, sourceRun=str(output)))
    (dest / 'runner.log').write_text('\n'.join('ET_RESULT ' + json.dumps(dict(r, type='order_result')) for r in derived) + '\n')
    verified = collect(dest, provider_key)
    return {'accepted': len(accepted), 'confirmed': sum(r['status'] == 'CONFIRMED' for r in derived),
            'clientOutcomes': {value: sum(r['outcome'] == value for r in rows) for value in {r['outcome'] for r in rows}},
            'finalAuditVerified': verified}



def money_invariants_verified(provider, verification):
    """Keep failed client delivery separate; never waive a financial violation."""
    violations = verification.get('violations')
    return (provider.get('extraction') == 'COMPLETE'
            and isinstance(violations, list)
            and all(v == 'invalid_acceptance_evidence' for v in violations)
            and (verification.get('passed') is True or bool(violations)))


def server_attribution_audit(output, meta, provider_key):
    """Audit committed requests even when no HTTP response reached the client.

    Never invent HTTP 202: the ordinary verifier must retain acceptance errors.
    Financial checks are reported separately from successful client delivery.
    """
    runner = module(ROOT / 'scripts/reliability-runner.py', 'server_attribution_collector')
    operator = runner.Operator(SimpleNamespace(context=CONTEXT, namespace='eurotransit'))
    rows = [json.loads(l) for l in (output / 'orders.jsonl').read_text().splitlines()]
    keys = [r['idempotencyKey'] for r in rows]
    assert all(key == meta['runId'] + '-' + str(r['iteration']) for key, r in zip(keys, rows))
    literals = ','.join("'" + key.replace("'", "''") + "'" for key in keys)
    mapping = operator.db('orders_db', "SELECT COALESCE(json_agg(t),'[]'::json) FROM (SELECT key,response_body::json->>'orderId' AS order_id,created_at FROM idempotency_keys WHERE key IN (" + literals + ")) t")
    by_key = {r['key']: r for r in mapping}
    dest = output / 'server-attribution'
    dest.mkdir(mode=0o700, exist_ok=True)
    derived_id = meta['runId'] + '-server'
    auth = token()
    derived = []
    for original in rows:
        match = by_key.get(original['idempotencyKey'])
        if not match:
            continue
        oid = str(uuid.UUID(match['order_id']))
        assert not original.get('orderId') or original['orderId'] == oid
        final = request(BASE + '/api/orders/' + oid, token=auth)
        value = dict(original, runId=derived_id, sourceRunId=meta['runId'], orderId=oid,
                     initialClientOutcome=original['outcome'], initialClientHttpStatus=original['httpStatus'],
                     acceptanceSource='client_response' if original.get('orderId') else 'database_idempotency_record',
                     status=final['status'], failureCode=final.get('failureCode'), finalObservedAt=now())
        value['outcome'] = 'confirmed' if final['status']=='CONFIRMED' else 'terminal_failure' if final['status'] in ('FAILED','CANCELLED') else 'timeout'
        derived.append(value)
    save(dest / 'run.json', dict(meta, runId=derived_id, mode='database-committed-request-audit', finishedAt=now(),
                                originalClientOutcomesPreserved=True))
    save(dest / 'request-attributions.json', mapping)
    (dest / 'runner.log').write_text('\n'.join('ET_RESULT ' + json.dumps(dict(r,type='order_result')) for r in derived) + '\n')
    complete_client_proof = collect(dest, provider_key)
    verification = json.loads((dest / 'verification.json').read_text())
    provider = json.loads((dest / 'provider-audit.json').read_text())
    result = {'clientAcknowledged':sum(bool(r.get('orderId')) for r in rows),
              'databaseCommitted':len(derived), 'confirmed':sum(r['status']=='CONFIRMED' for r in derived),
              'committedWithoutClientOrderId':sum(r['acceptanceSource']=='database_idempotency_record' for r in derived),
              'providerCharges':len(provider.get('authorizations',[])),
              'providerAuditComplete':provider.get('extraction')=='COMPLETE',
              'moneyPathInvariantsVerified':money_invariants_verified(provider, verification),
              'clientProofPassed':complete_client_proof,
              'note':'HTTP failures are unchanged; database commitment is not a successful client response.'}
    save(dest / 'attribution-result.json', result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('baseline', 'prepare-cdc', 'warmup', 'fault'))
    p.add_argument('--fault-mode', choices=('worker-stop', 'worker-freeze'), default='worker-stop',
                   help='SIGKILL/start a worker (default), or reproduce the distinct process-freeze fault')
    p.add_argument('--fault-seconds', type=int, choices=(90, 180), default=90,
                   help='Bounded observation window; never changed during a run')
    a = p.parse_args()
    os.umask(0o077)
    if a.action == 'prepare-cdc':
        preflight(False)  # Requires both physical standbys streaming, never changes an unhealthy cluster.
        pods = obj('pods', '-l', 'cnpg.io/cluster=eurotransit-postgres')['items']
        names = sorted(p['metadata']['name'] for p in pods if p['metadata'].get('labels',{}).get('cnpg.io/podRole')=='instance')
        assert len(names)==3 and all(n.startswith('eurotransit-postgres-') and n.rsplit('-',1)[1].isdigit() for n in names)
        slots = ','.join('_cnpg_' + n.replace('-','_') for n in names)
        patch = {'spec':{'postgresql':{'parameters':{'pg_failover_slots.standby_slot_names':slots}}}}
        k('patch','cluster.postgresql.cnpg.io','eurotransit-postgres','--type=merge','-p',json.dumps(patch))
        print('Kind-only CDC barrier aligned with current instance identities:', ', '.join(names), flush=True)
        return 0
    if a.action == 'warmup':
        # At most four two-order sandbox batches. Never bypass another safety gate.
        for batch in range(5):
            try:
                preflight(True)
                print('All standby logical slots initialized; warm-up complete.', flush=True)
                return 0
            except AssertionError as exc:
                if str(exc) != 'Standby logical slots not initialized' or batch == 4:
                    raise
            print('Slot warm-up batch', batch + 1, 'of at most 4 (two sandbox checkouts).', flush=True)
            completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), 'baseline'], cwd=ROOT)
            if completed.returncode:
                return completed.returncode
            time.sleep(6)  # Bound to one HA Connect offset-flush period.
        return 1
    run_id = 'et-kind-' + a.action + '-' + uuid.uuid4().hex[:10]
    output = ROOT / 'load-results' / run_id
    output.mkdir(parents=True, mode=0o700)
    baseline = preflight(a.action == 'fault')
    save(output / 'preflight.json', baseline)
    provider_key = secret('payments-provider-credentials', 'provider-api-key')
    assert provider_key.startswith(('sk_test_', 'rk_test_'))
    attempts = 2 if a.action == 'baseline' else 8
    runner = module(ROOT / 'scripts/reliability-runner.py', 'kind_runner')
    operator = runner.Operator(SimpleNamespace(context=CONTEXT, namespace='eurotransit'))
    operator.cm('eurotransit-load-test-lock', {'runId': run_id, 'mode': 'workstation', 'context': CONTEXT, 'output': str(output)})
    process = guardian = None
    fault_injected = False
    sources = ['scripts/kind-ha-experiment.py', 'load-tests/kind-ha.js', 'load-tests/checkout.js',
               'charts/eurotransit/values-kind-ha.yaml', 'charts/eurotransit/templates/_r2dbc-pool.tpl',
               'platform/cloudnativepg/values-kind-ha.yaml', 'charts/eurotransit/templates/catalog-failover.yaml',
               'platform/strimzi/values-kind-ha.yaml',
               'platform/connectors/environments/kind-ha/shared-ha-patch.yaml']
    meta = {'runId': run_id, 'mode': 'kind-ha-' + a.action, 'context': CONTEXT, 'startedAt': now(),
            'faultMode': a.fault_mode if a.action == 'fault' else None,
            'faultSeconds': a.fault_seconds if a.action == 'fault' else None,
            'configHashes': {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources if (ROOT/name).exists()}}

    timeline = []
    node_lost = promoted_during_fault = False
    confirmed_during_fault = 0
    def event(kind, **fields):
        entry = dict(at=now(), event=kind, **fields)
        timeline.append(entry)
        save(output / 'timeline.json', timeline)
        print(json.dumps(entry), flush=True)
    try:
        choices = operator.db('inventory_db', "SELECT COALESCE(json_agg(t),'[]'::json) FROM (SELECT route_id,travel_date,seat_id FROM seats WHERE status='AVAILABLE' AND route_id='rt-to-mi-001' AND travel_date>=CURRENT_DATE+7 ORDER BY travel_date,seat_id LIMIT 200) t")
        claims = obj('configmap', '-l', 'eurotransit.io/load-test=true')['items']
        claimed = {tuple(json.loads(c['data']['fixture'])) for c in claims if c.get('data', {}).get('fixture')}
        choices = [s for s in choices if (s['route_id'], s['travel_date'], s['seat_id']) not in claimed][:attempts]
        assert len(choices) == attempts
        offers = request(BASE + '/api/catalog/offers')
        offer = next(o for o in offers if o['routeId'] == 'rt-to-mi-001' and o['offerId'] == 'of-001')
        fixtures = [{'routeId':s['route_id'], 'offerId':offer['offerId'], 'travelDate':s['travel_date'],
                     'seatId':s['seat_id'], 'unitPrice':offer['price'], 'currency':offer['currency']} for s in choices]
        for fixture in fixtures:
            key = json.dumps([fixture['routeId'], fixture['travelDate'], fixture['seatId']])
            operator.cm('et-fixture-' + hashlib.sha256(key.encode()).hexdigest()[:24], {'fixture':key, 'runId':run_id})
        save(output / 'fixtures.json', {'version': 1, 'fixtures': fixtures})
        # Explicit bounded warm-up for cold auth/JWK/DB caches, before the measured harness.
        # No order is submitted here; preserve every failed setup response.
        auth = token()
        warm = []
        for _ in range(3):
            began = time.monotonic()
            try:
                request(BASE + '/api/orders/seat-availability?' + urlencode({'routeId':fixtures[0]['routeId'], 'travelDate':fixtures[0]['travelDate']}), token=auth)
                status = 200
            except HTTPError as error:
                status = error.code
            warm.append({'at':now(), 'status':status, 'durationMs':round((time.monotonic()-began)*1000,2)})
            time.sleep(1)
        save(output / 'setup-warmup.json', warm)
        assert all(r['status']==200 for r in warm[-2:]), 'Seat-map preflight not stable after bounded warm-up'

        save(output / 'run.json', meta)
        operator.snapshot(output, 'before')
        env = os.environ.copy()
        env.update(PUBLIC_URL=BASE, TOKEN_URL=ISSUER + '/protocol/openid-connect/token',
                   CLIENT_ID='eurotransit-load-test', CLIENT_SECRET=secret('eurotransit-load-test-credentials','client-secret'),
                   RUN_ID=run_id, SCENARIO='baseline', MAX_ATTEMPTS=str(attempts), MAX_VUS='1',
                   POLL_TIMEOUT_SECONDS='30', ALLOW_INSECURE_TLS='true', OUTPUT_DIR=str(output),
                   FIXTURES_FILE=str(output / 'fixtures.json'), HA_OBSERVE_SECONDS=str(a.fault_seconds + 90))
        script = 'kind-ha.js' if a.action == 'fault' else 'checkout.js'
        with (output / 'runner.log').open('w') as log:
            process = subprocess.Popen([sys.executable, str(ROOT / 'load-tests/run.py'), str(ROOT / 'load-tests' / script)],
                                       cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            expires = time.monotonic() + 500
            promotion = restored = False
            next_replication_sample = 0
            observed = set()
            while process.poll() is None:
                if time.monotonic() >= expires:
                    raise TimeoutError('Bounded experiment deadline reached')
                raw = (output / 'runner.log').read_text()
                for row in runner.parse_results(raw, run_id):
                    if row.get('type') != 'order_result' or row.get('iteration') in observed:
                        continue
                    observed.add(row['iteration'])
                    row_fault = fault_injected and unavailable(json.loads(command(['docker','inspect',baseline['containerId']]))[0]['State'], a.fault_mode)
                    if row_fault and row['outcome'] == 'confirmed' and row['iteration'] > 0:
                        confirmed_during_fault += 1
                    event('client_order', iteration=row['iteration'], status=row.get('status'), outcome=row['outcome'], httpStatus=row['httpStatus'], workerUnavailable=row_fault)
                    if a.action == 'fault' and not fault_injected:
                        assert row['outcome'] == 'confirmed', 'No healthy initial checkout; fault aborted'
                        # Establish a real physical steady state after the first checkout as well.
                        assert obj('cluster.postgresql.cnpg.io','eurotransit-postgres')['status']['currentPrimary'] == baseline['primary']
                        aligned = False
                        for _ in range(5):
                            lag = json.loads(sql(baseline['primary'], "SELECT COALESCE(json_agg(t),'[]'::json) FROM (SELECT application_name,state,pg_wal_lsn_diff(pg_current_wal_lsn(),replay_lsn) AS lag FROM pg_stat_replication WHERE application_name LIKE 'eurotransit-postgres-%') t"))
                            if len(lag)==2 and all(r['state']=='streaming' and r['lag']==0 for r in lag):
                                aligned = True
                                save(output / 'physical-replication-at-injection.json', lag)
                                break
                            time.sleep(1)
                        assert aligned, 'Both physical standbys must have replayed current WAL before injection'
                        # External watchdog survives parent interruption and never touches another container.
                        guard_code = ('import subprocess,time,json,sys; time.sleep(int(sys.argv[3])); '
                                      'v=json.loads(subprocess.check_output(["docker","inspect",sys.argv[1]]))[0]; '
                                      'frozen=sys.argv[2]=="worker-freeze"; '
                                      'needed=v["State"]["Paused"] if frozen else not v["State"]["Running"]; '
                                      'subprocess.run(["docker","unpause" if frozen else "start",sys.argv[1]],check=True) if needed else None')
                        guardian = subprocess.Popen([sys.executable, '-c', guard_code, baseline['containerId'], a.fault_mode, str(a.fault_seconds)],
                                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                        inject = ['docker', 'pause'] if a.fault_mode == 'worker-freeze' else ['docker', 'kill', '--signal=KILL']
                        # Arm cleanup before the call: Docker could stop the node and then time out.
                        fault_injected = True
                        command([*inject, baseline['containerId']])
                        event('worker_paused' if a.fault_mode == 'worker-freeze' else 'worker_stopped', worker=baseline['target'], primary=baseline['primary'], deadlineSeconds=a.fault_seconds)
                if fault_injected:
                    current = obj('cluster.postgresql.cnpg.io', 'eurotransit-postgres')['status'].get('currentPrimary')
                    state = json.loads(command(['docker', 'inspect', baseline['containerId']]))[0]['State']
                    down = unavailable(state, a.fault_mode)
                    if current and current != baseline['primary'] and not promotion:
                        promotion = True
                        promoted_during_fault = down
                        event('primary_changed', primary=current, workerUnavailable=down)
                        try:
                            state_at_promotion = json.loads(sql(current, "SELECT COALESCE(json_agg(t),'[]'::json) FROM (SELECT application_name,state,sync_state FROM pg_stat_replication) t"))
                            save(output / 'replication-at-promotion.json', state_at_promotion)
                        except (RuntimeError, subprocess.TimeoutExpired):
                            event('promotion_replication_sample_unavailable')
                    if not down and not restored:
                        restored = True
                        event('worker_unpaused' if a.fault_mode == 'worker-freeze' else 'worker_started', worker=baseline['target'])
                    if promotion and down and time.monotonic() >= next_replication_sample:
                        next_replication_sample = time.monotonic() + 8
                        try:
                            replication = json.loads(sql(current, "SELECT COALESCE(json_agg(t),'[]'::json) FROM (SELECT application_name,state,sync_state FROM pg_stat_replication) t"))
                            waits = json.loads(sql(current, "SELECT COALESCE(json_agg(t),'[]'::json) FROM (SELECT wait_event_type,wait_event,count(*) FROM pg_stat_activity WHERE wait_event='SyncRep' GROUP BY wait_event_type,wait_event) t"))
                            with (output / 'promoted-replication.jsonl').open('a') as out:
                                out.write(json.dumps({'at':now(),'primary':current,'workerUnavailable':True,
                                                      'replication':replication,'synchronousCommitWaits':waits}) + '\n')
                        except (RuntimeError, subprocess.TimeoutExpired):
                            event('replication_sample_unavailable')
                    samples = {'at':now(), 'primary':current, 'workerUnavailable':down, 'hostMemory':memory_mib(),
                               'nodes':[{ 'name':n['metadata']['name'], 'conditions':n['status']['conditions']} for n in obj('nodes')['items']]}
                    for node in samples['nodes']:
                        if node['name'] == baseline['target'] and any(c['type']=='Ready' and c['status']!='True' for c in node['conditions']):
                            if not node_lost:
                                event('node_not_ready', worker=baseline['target'])
                            node_lost = True
                    with (output / 'samples.jsonl').open('a') as out:
                        out.write(json.dumps(samples) + '\n')
                time.sleep(2)
            meta.update(finishedAt=now(), exitCode=process.returncode)
            save(output / 'run.json', meta)
        if a.action == 'fault':
            assert fault_injected, 'Harness completed without injecting fault'
        event('harness_finished', exitCode=process.returncode)
    finally:
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        if fault_injected:
            state = json.loads(command(['docker','inspect',baseline['containerId']]))[0]['State']
            if unavailable(state, a.fault_mode):
                command(['docker','unpause' if a.fault_mode == 'worker-freeze' else 'start',baseline['containerId']])
                event('worker_restored_cleanup', worker=baseline['target'])
        if guardian:
            if guardian.poll() is None:
                guardian.terminate()
            guardian.wait(timeout=5)
        operator.k('delete','configmap','eurotransit-load-test-lock')
    operator.snapshot(output, 'after')
    original_verified = collect(output, provider_key)
    final = final_audit(output, meta, provider_key)
    server = server_attribution_audit(output, meta, provider_key)
    catalog_samples = []
    for line in (output / 'runner.log').read_text().splitlines():
        if line.startswith('ET_HA_CATALOG '):
            catalog_samples.append(json.loads(line[len('ET_HA_CATALOG '):]))
    catalog_errors = sum(s['status'] != 200 for s in catalog_samples)
    ha_observed = node_lost and promoted_during_fault and confirmed_during_fault > 0 and bool(catalog_samples) and catalog_errors == 0
    result = dict(final, originalClientVerified=original_verified, harnessExitCode=meta['exitCode'],
                  faultMode=meta['faultMode'], nodeNotReadyObserved=node_lost, promotedDuringWorkerFault=promoted_during_fault,
                  confirmedDuringWorkerFault=confirmed_during_fault, catalogSamples=len(catalog_samples),
                  catalogErrors=catalog_errors, haObserved=ha_observed if a.action=='fault' else None, serverAttribution=server)
    save(output / 'experiment-result.json', result)
    event('audit_finished', **final, originalClientVerified=original_verified)
    print('ARTIFACTS', str(output), flush=True)
    return 0 if server['moneyPathInvariantsVerified'] and server['confirmed'] == server['databaseCommitted'] and ((a.action == 'fault' and ha_observed) or (a.action == 'baseline' and original_verified)) else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('Experiment stopped:', type(exc).__name__, str(exc), file=sys.stderr)
        raise SystemExit(1)
