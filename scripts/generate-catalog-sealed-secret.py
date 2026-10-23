#!/usr/bin/env python3
"""Create only Catalog's AKS ciphertext locally; all cluster operations are read-only."""
import argparse
import base64
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'platform/environments/aks/secrets/catalog-db-credentials.sealedsecret.yaml'


def command(argv, payload=None):
    result = subprocess.run(argv, input=payload, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Read/seal operation failed; sensitive diagnostics suppressed.')
    return result.stdout


def secret_document(existing):
    if existing:
        if base64.b64decode(existing['data']['username']).decode() != 'catalog':
            raise ValueError('Existing Catalog credentials have an unexpected username.')
        password = base64.b64decode(existing['data']['password']).decode()
        if not password:
            raise ValueError('Existing Catalog password is empty.')
    else:
        password = secrets.token_urlsafe(32)
    return {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'kubernetes.io/basic-auth',
            'metadata': {'name': 'catalog-db-credentials', 'namespace': 'eurotransit',
                         'labels': {'cnpg.io/reload': 'true'}},
            'stringData': {'username': 'catalog', 'password': password}}


def generate(context, certificate=None, target=TARGET):
    if target.exists():
        raise ValueError('Catalog ciphertext already exists; refusing to overwrite or rotate it.')
    raw = command(['kubectl', '--context', context, '-n', 'eurotransit', 'get', 'secret',
                   'catalog-db-credentials', '--ignore-not-found', '-o', 'json'])
    document = secret_document(json.loads(raw) if raw.strip() else None)
    with tempfile.TemporaryDirectory(prefix='catalog-public-cert-') as tmp:
        cert = Path(certificate) if certificate else Path(tmp) / 'controller.crt'
        if certificate is None:
            cert.write_text(command(['kubeseal', '--context', context, '--controller-name', 'sealed-secrets-controller',
                                     '--controller-namespace', 'sealed-secrets', '--fetch-cert']))
        ciphertext = command(['kubeseal', '--cert', str(cert), '--scope', 'strict', '--format', 'yaml'], json.dumps(document))
    sealed = yaml.safe_load(ciphertext)
    if sealed['kind'] != 'SealedSecret' or sealed['metadata']['name'] != 'catalog-db-credentials' or sealed['metadata']['namespace'] != 'eurotransit':
        raise ValueError('Unexpected sealed identity; no output was saved.')
    if set(sealed['spec']['encryptedData']) != {'username', 'password'} or 'stringData' in sealed['spec']:
        raise ValueError('Unexpected sealed data; no output was saved.')
    with target.open('x') as output:
        output.write(ciphertext)
    print('Created only Catalog ciphertext locally. No cluster resources were applied or changed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True, help='Explicit context used only to read existing credentials and the public sealing certificate')
    parser.add_argument('--cert', type=Path, help='Optional public controller certificate')
    args = parser.parse_args()
    generate(args.context, args.cert)
