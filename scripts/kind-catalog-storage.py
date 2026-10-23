#!/usr/bin/env python3
"""Patch only Kind's Catalog workload; preserve experimental Orders rollouts and Helm drift."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    parser.add_argument('--storage', choices=('in-memory', 'postgres'))
    parser.add_argument('--image')
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    if not args.context.startswith('kind-'):
        parser.error('An explicit kind-* context is required.')
    if not args.restore and (not args.storage or not args.image):
        parser.error('--storage and --image are required unless restoring.')
    os.umask(0o077)

    def run(command):
        return subprocess.check_output(command, text=True)

    k = ['kubectl', '--context', args.context, '-n', 'eurotransit']
    current = json.loads(run([*k, 'get', 'deployment', 'catalog', '-o', 'json']))
    if args.restore:
        snapshot = json.loads(args.snapshot.read_text())
        if snapshot['context'] != args.context or snapshot['uid'] != current['metadata']['uid']:
            raise SystemExit('Snapshot belongs to a different context or workload.')
        template = snapshot['template']
    else:
        # Refuse to overwrite the original recovery point on subsequent deployments.
        if not args.snapshot.exists():
            args.snapshot.parent.mkdir(parents=True, exist_ok=True)
            with args.snapshot.open('x') as output:
                json.dump({'context': args.context, 'uid': current['metadata']['uid'],
                           'template': current['spec']['template']}, output, indent=2)
        else:
            snapshot = json.loads(args.snapshot.read_text())
            if snapshot['context'] != args.context or snapshot['uid'] != current['metadata']['uid']:
                raise SystemExit('Existing snapshot belongs to a different workload.')
        values = run(['helm', '--kube-context', args.context, '-n', 'eurotransit', 'get', 'values', 'eurotransit', '-a', '-o', 'json'])
        rollout = run([*k, 'get', 'rollout', 'catalog', '--ignore-not-found', '-o', 'json'])
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as tmp:
            tmp.write(values)
            tmp.flush()
            rendered = yaml.safe_load(run(['helm', 'template', 'eurotransit', str(ROOT / 'charts/eurotransit'),
                '-f', tmp.name, '--show-only', 'templates/catalog-deployment.yaml',
                '--set-string', 'catalog.storage=' + args.storage,
                '--set', 'progressiveDelivery.enabled=' + str(bool(rollout.strip())).lower()]))
        template = copy.deepcopy(current['spec']['template'])
        template['spec']['affinity'] = rendered['spec']['template']['spec']['affinity']
        spread = rendered['spec']['template']['spec'].get('topologySpreadConstraints')
        if spread:
            template['spec']['topologySpreadConstraints'] = spread
        else:
            template['spec'].pop('topologySpreadConstraints', None)
        init = [c for c in template['spec'].get('initContainers', []) if c['name'] != 'catalog-database-ready']
        init.extend(rendered['spec']['template']['spec'].get('initContainers', []))
        if init:
            template['spec']['initContainers'] = init
        else:
            template['spec'].pop('initContainers', None)
        container = next(c for c in template['spec']['containers'] if c['name'] == 'catalog')
        container['image'] = args.image
        def managed(name):
            return name == 'CATALOG_STORAGE' or name.startswith(('DB_', 'SPRING_R2DBC_POOL_'))
        env = [e for e in container.get('env', []) if not managed(e['name'])]
        env.extend(e for e in rendered['spec']['template']['spec']['containers'][0]['env'] if managed(e['name']))
        container['env'] = env
    patch = [{'op': 'test', 'path': '/metadata/resourceVersion', 'value': current['metadata']['resourceVersion']},
             {'op': 'replace', 'path': '/spec/template', 'value': template}]
    subprocess.run([*k, 'patch', 'deployment', 'catalog', '--type=json', '-p', json.dumps(patch)], check=True)
    print('Catalog template updated. Validate preview and promote through its existing Rollout before checking public traffic.')


if __name__ == '__main__':
    main()
