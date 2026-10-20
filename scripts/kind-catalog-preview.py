#!/usr/bin/env python3
"""Compare Catalog preview with active APIs and drive the existing Prometheus gate."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import time
from urllib.error import URLError
from urllib.request import urlopen

spec = importlib.util.spec_from_file_location('catalog_check', Path(__file__).with_name('kind-catalog-check.py'))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def normalized(offer):
    value = copy.deepcopy(offer)
    if value['offerId'] == 'of-003':
        value['conditions'] = 'Non-refundable.'
        if 'displayNote' in value:
            value['displayNote'] = None
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--storage', choices=('in-memory', 'postgres'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verified-analysis', help='Explicit prior successful analysis for restoration of the identical stable pod hash')
    args = parser.parse_args()
    assert 1024 <= args.port <= 65535
    os.umask(0o077)
    base = 'http://127.0.0.1:' + str(args.port) + '/api/catalog'

    def get(path):
        with urlopen(base + path, timeout=5) as response:
            return json.load(response)

    deadline = time.monotonic() + 60
    while True:
        try:
            routes = get('/routes')
            break
        except URLError:
            assert time.monotonic() < deadline, 'Preview startup deadline exceeded'
            time.sleep(1)
    offers = get('/offers')
    assert routes == c.h.request(c.h.BASE + '/api/catalog/routes')
    active = c.h.request(c.h.BASE + '/api/catalog/offers')
    assert [normalized(o) for o in offers] == [normalized(o) for o in active]
    assert len(routes) == 5 and len(offers) == 6
    for offer in offers:
        detail = get('/offers/' + offer['offerId'])
        assert normalized(detail) == normalized(c.h.request(c.h.BASE + '/api/catalog/offers/' + offer['offerId']))
    if args.storage == 'postgres':
        assert next(o for o in offers if o['offerId'] == 'of-003')['conditions'] == 'Non-refundable.'
    selector = c.h.obj('service', 'catalog-preview')['spec']['selector']
    pods = c.h.obj('pods', '-l', ','.join(k + '=' + v for k, v in selector.items()))['items']
    assert pods
    for pod in pods:
        container = next(v for v in pod['spec']['containers'] if v['name'] == 'catalog')
        storage = next((e.get('value') for e in container['env'] if e['name'] == 'CATALOG_STORAGE'), 'in-memory')
        assert storage == args.storage
    proof = {'startedAt': c.h.now(), 'routes': 5, 'offers': 6, 'allDetailsEquivalent': True,
             'storage': args.storage, 'previewHash': selector['rollouts-pod-template-hash'], 'requests': 0}
    args.output.write_text(json.dumps(proof, indent=2) + '\n')
    deadline = time.monotonic() + 210
    next_poll = 0
    while time.monotonic() < deadline:
        get('/routes')
        get('/offers/of-003')
        proof['requests'] += 2
        if time.monotonic() >= next_poll:
            rollout = c.h.obj('rollout', 'catalog')
            analysis = rollout['status'].get('blueGreen', {}).get('prePromotionAnalysisRunStatus', {})
            deployment = c.h.obj('deployment', 'catalog')
            rs = c.h.obj('replicaset', 'catalog-' + proof['previewHash'])
            revision = rs['metadata']['annotations']['rollout.argoproj.io/revision']
            expected_name = 'catalog-' + proof['previewHash'] + '-' + revision + '-pre'
            observed = str(rollout['status'].get('workloadObservedGeneration')) == str(deployment['metadata']['generation'])
            status = rollout['status']
            if args.verified_analysis and observed and status.get('phase') == 'Healthy' and status.get('stableRS') == proof['previewHash'] and status.get('blueGreen', {}).get('activeSelector') == proof['previewHash']:
                prior = c.h.obj('analysisrun', args.verified_analysis)
                assert prior['status']['phase'] == 'Successful'
                assert any(a['name'] == 'preview-hash' and a.get('value') == proof['previewHash'] for a in prior['spec']['args'])
                proof.update(passed=True, analysis={'name': args.verified_analysis, 'status': 'Successful'},
                    restoredPreviouslyVerifiedStable=True, finishedAt=c.h.now())
                args.output.write_text(json.dumps(proof, indent=2) + '\n')
                print(json.dumps(proof))
                return
            if observed and analysis.get('name') == expected_name:
                assert analysis['status'] not in ('Failed', 'Error'), 'Preview analysis failed'
                if analysis['status'] == 'Successful':
                    proof.update(passed=True, analysis=analysis, finishedAt=c.h.now())
                    args.output.write_text(json.dumps(proof, indent=2) + '\n')
                    print(json.dumps(proof))
                    return
            next_poll = time.monotonic() + 5
        time.sleep(.5)
    raise AssertionError('Preview analysis did not complete within its deadline')


if __name__ == '__main__':
    main()
