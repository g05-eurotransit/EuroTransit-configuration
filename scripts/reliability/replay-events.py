#!/usr/bin/env python3
"""Replay collector-exported original events only; never synthesize business events."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--context', required=True)
    p.add_argument('--namespace', default='eurotransit')
    p.add_argument('--producer-pod', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--preflight', required=True)
    args = p.parse_args()
    root = Path(args.output_dir)
    run = json.loads((root / 'run.json').read_text())
    exported = json.loads((root / 'canonical-events.json').read_text())
    if exported['runId'] != run['runId']:
        p.error('canonical events do not belong to this run')
    preflight = json.loads(Path(args.preflight).read_text())
    stamp = datetime.datetime.fromisoformat(preflight['timestamp'].replace('Z', '+00:00'))
    age = (datetime.datetime.now(datetime.timezone.utc) - stamp).total_seconds()
    if (preflight.get('context') != args.context or preflight.get('namespace') != args.namespace
            or preflight.get('runId') != run['runId']
            or preflight.get('status') != 'passed'
            or preflight.get('faultsPermitted') is not True or not 0 <= age <= 300):
        p.error('fresh successful preflight for this cluster is required')
    ledger = [json.loads(line) for line in (root / 'orders.jsonl').read_text().splitlines() if line]
    allowed = {str(row['orderId']) for row in ledger if row.get('runId') == run['runId'] and row.get('orderId')}
    events = exported['events']
    if not events or len(events) > 20:
        p.error('expected 1..20 original order-placed events')
    records, audit = [], []
    ids = set()
    for event in events:
        payload = event['payload']
        payload = json.loads(payload) if isinstance(payload, str) else payload
        if (event['type'] != 'order-placed' or not event.get('source')
                or str(payload['orderId']) != str(event['aggregate_id'])
                or str(event['aggregate_id']) not in allowed or event['id'] in ids):
            p.error('invalid original event export')
        ids.add(event['id'])
        raw = json.dumps(payload, separators=(',', ':'))
        records.append(str(event['aggregate_id']) + '\t' + raw)
        audit.append({'sourceEventId': event['id'], 'orderId': event['aggregate_id'],
                      'sourceTimestamp': event['created_at'], 'payloadEventId': payload.get('eventId'),
                      'payloadSha256': hashlib.sha256(raw.encode()).hexdigest()})
    if args.execute and (root / 'replay-audit.json').exists():
        p.error('replay already recorded; investigate the prior attempt before retrying')
    if args.execute:
        # Existing broker tool, no new workload. Operator must provide the verified broker pod.
        pod = json.loads(subprocess.check_output([
            'kubectl', '--context', args.context, '-n', args.namespace,
            '--request-timeout=15s', 'get', 'pod', args.producer_pod, '-o', 'json'], text=True, timeout=30))
        if pod['metadata'].get('labels', {}).get('strimzi.io/name') != 'eurotransit-kafka-kafka':
            p.error('producer pod is not an EuroTransit Kafka broker')
        (root / 'replay-audit.json').write_text(json.dumps({'version': 1, 'runId': run['runId'], 'status': 'attempted', 'events': audit}, indent=2) + '\n')
        subprocess.run(['kubectl', '--context', args.context, '-n', args.namespace,
                        '--request-timeout=15s', 'exec', '-i', args.producer_pod, '--',
                        '/opt/kafka/bin/kafka-console-producer.sh',
                        '--bootstrap-server', 'localhost:9092', '--topic', 'order-placed',
                        '--property', 'parse.key=true', '--property', 'key.separator=\t'],
                       input='\n'.join(records) + '\n', text=True, timeout=60, check=True,
                       stdout=subprocess.DEVNULL)
    result = {'version': 1, 'runId': run['runId'], 'executed': args.execute,
              'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'events': audit}
    if args.execute:
        (root / 'replay-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'runId': run['runId'], 'count': len(events), 'executed': args.execute}))


if __name__ == '__main__':
    main()
