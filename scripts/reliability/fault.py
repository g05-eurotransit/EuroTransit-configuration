#!/usr/bin/env python3
"""Explicit single-fault commands; no GitOps edits, fixture writes or automatic recovery claims."""
import argparse
import datetime
import json
import pathlib
import subprocess
import urllib.request
import urllib.parse


def kube(args, *command, stdin=None):
    result = subprocess.run(['kubectl', '--context', args.context, '-n', args.namespace, '--request-timeout=15s',
                             *command], input=stdin, text=True, check=True, capture_output=True, timeout=30)
    return result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('scenario', choices=['payments-latency', 'payments-reset', 'inventory-kill'])
    parser.add_argument('--context', required=True)
    parser.add_argument('--namespace', default='eurotransit')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--lease-url', default='http://127.0.0.1:18474')
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--preflight', required=True, help='Fresh successful #46 preflight JSON')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    endpoint = urllib.parse.urlsplit(args.lease_url)
    if (endpoint.scheme != 'http' or endpoint.hostname not in ('127.0.0.1', 'localhost', '::1')
            or endpoint.username or endpoint.password or endpoint.path not in ('', '/')
            or endpoint.query or endpoint.fragment):
        parser.error('lease URL must be a loopback HTTP port-forward without credentials or path')
    if args.scenario != 'payments-reset':
        preflight = json.loads(pathlib.Path(args.preflight).read_text())
        if (preflight.get('faultsPermitted') is not True or preflight.get('status') != 'passed'
                or preflight.get('context') != args.context or preflight.get('namespace') != args.namespace
                or preflight.get('runId') != args.run_id):
            parser.error('preflight must permit faults and match context, namespace and runId')
        timestamp = datetime.datetime.fromisoformat(preflight['timestamp'].replace('Z', '+00:00'))
        age = (datetime.datetime.now(datetime.timezone.utc) - timestamp).total_seconds()
        if not 0 <= age <= 300:
            parser.error('preflight is stale (>300 seconds) or from the future')
        if args.scenario == 'payments-latency' and preflight.get('extraMemoryMiB', 0) < 576:
            parser.error('Payments gate must reserve proxy64Mi plus Orders rollout512Mi')
        if (pathlib.Path(args.output_dir) / (args.scenario + '-fault.json')).exists():
            parser.error('fault already recorded for this run; use a new run')
    if not args.execute:
        print(json.dumps({'dryRun': True, 'scenario': args.scenario, 'runId': args.run_id}))
        return
    if not 1 <= args.seconds <= 175:
        parser.error('lease seconds must be between 1 and 175')
    evidence = {'version': 1, 'runId': args.run_id, 'scenario': args.scenario,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'overlapEvidence': False}
    target = pathlib.Path(args.output_dir)
    target.mkdir(parents=True, exist_ok=True)
    evidence['status'] = 'attempted'
    evidence_path = target / (args.scenario + '-fault.json')
    evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')
    if args.scenario == 'inventory-kill':
        pods = json.loads(kube(args, 'get', 'pods', '-l', 'app=inventory', '-o', 'json'))['items']
        ready = [p for p in pods if any(c.get('type') == 'Ready' and c.get('status') == 'True'
                                       for c in p.get('status', {}).get('conditions', []))]
        if len(ready) != 1:
            parser.error('expected exactly one Ready Inventory pod in fixed-capacity topology')
        pod = ready[0]
        name, uid = pod['metadata']['name'], pod['metadata']['uid']
        # Kubernetes DeleteOptions UID precondition prevents deleting a replacement pod.
        endpoint = '/api/v1/namespaces/' + args.namespace + '/pods/' + name
        options = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'preconditions': {'uid': uid},
                   'gracePeriodSeconds': 0}
        evidence.update(podName=name, podUID=uid)
        evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')
        kube(args, 'delete', '--raw', endpoint, '-f', '-', stdin=json.dumps(options))
    else:
        method = 'DELETE' if args.scenario == 'payments-reset' else 'POST'
        body = None if method == 'DELETE' else json.dumps({'seconds': args.seconds}).encode()
        request = urllib.request.Request(args.lease_url + '/lease', data=body, method=method,
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=5) as response:
            evidence['lease'] = json.load(response)
    evidence['status'] = 'completed'
    evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
