#!/usr/bin/env python3
"""Verify a Catalog database edit survives replacement of one active Kind pod."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import time
import uuid

spec = importlib.util.spec_from_file_location('catalog_check', Path(__file__).with_name('kind-catalog-check.py'))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    selector = c.h.obj('service', 'catalog')['spec']['selector']
    labels = ','.join(k + '=' + v for k, v in selector.items())
    pods = c.h.obj('pods', '-l', labels)['items']
    ready = lambda p: not p['metadata'].get('deletionTimestamp') and all(x.get('ready') for x in p['status'].get('containerStatuses', [])) and bool(p['status'].get('containerStatuses'))
    assert len([p for p in pods if ready(p)]) >= 2, 'Two healthy active replicas are required before restarting one'
    assert all(any(e['name'] == 'CATALOG_STORAGE' and e.get('value') == 'postgres'
        for e in next(v for v in p['spec']['containers'] if v['name'] == 'catalog')['env']) for p in pods)
    assert c.sql('catalog_db', "SELECT display_note IS NULL FROM offers WHERE offer_id='of-003';").strip() == 't', 'Unexpected existing note; refusing to overwrite it'
    old_names = {p['metadata']['name'] for p in pods}
    marker = 'persistence-proof-' + uuid.uuid4().hex
    proof = {'startedAt': c.h.now(), 'context': c.h.CONTEXT}
    try:
        c.sql('catalog_db', "UPDATE offers SET display_note='" + marker + "' WHERE offer_id='of-003';")
        name = next(p['metadata']['name'] for p in pods if ready(p))
        c.h.k('delete', 'pod', name, '--wait=false')
        deadline = time.monotonic() + 90
        while True:
            candidates = c.h.obj('pods', '-l', labels)['items']
            new = [p for p in candidates if p['metadata']['name'] not in old_names and ready(p)]
            if new:
                break
            assert time.monotonic() < deadline, 'Replacement Catalog pod did not become ready'
            time.sleep(1)
        replacement = new[0]['metadata']['name']
        detail = json.loads(c.h.k('exec', replacement, '--', 'wget', '-qO-', 'http://127.0.0.1:8080/api/catalog/offers/of-003'))
        assert detail['conditions'] == 'Non-refundable. ' + marker
        migrations = c.sql('catalog_db', 'SELECT count(*) FROM flyway_schema_history WHERE success;').strip()
        assert migrations == '2'
        proof.update(passed=True, replacedPod=name, replacementPod=replacement, storedNoteSurvived=True, migrationCount=2)
    finally:
        c.sql('catalog_db', "UPDATE offers SET display_note=NULL WHERE offer_id='of-003';")
        proof['noteRestored'] = True
        proof['finishedAt'] = c.h.now()
        args.output.write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof))


if __name__ == '__main__':
    main()
