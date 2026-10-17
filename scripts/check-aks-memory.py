#!/usr/bin/env python3
"""Offline render/check of pinned owners; no Kubernetes API calls or deployment.

Requires PyYAML, helm, kubectl and pinned chart archives in --chart-cache.
Use --baseline-root with a git archive of the starting revision to prove Kind
renders are identical. --inventory-pods/--inventory-nodes accept saved read-only
snapshots; they never query a cluster and are not a scheduling guarantee.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tarfile
import yaml

class KubernetesLoader(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
    pass


# CRD enums can contain unquoted "="; Kubernetes treats it as a string.
KubernetesLoader.add_constructor("tag:yaml.org,2002:value", KubernetesLoader.construct_scalar)
LOADER = KubernetesLoader
DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)


def run(args):
    return subprocess.run([str(x) for x in args], check=True, text=True, capture_output=True).stdout


def documents(raw):
    return [x for x in yaml.load_all(raw, Loader=LOADER) if isinstance(x, dict)]


def chart_index(cache):
    result = {}
    for path in Path(cache).rglob('*.chart'):
        with tarfile.open(path) as archive:
            member = next((m for m in archive.getmembers() if re.fullmatch('[^/]+/Chart.yaml', m.name)), None)
            if member:
                meta = yaml.load(archive.extractfile(member), Loader=LOADER)
                result[(meta['name'], str(meta['version']).lstrip('v'))] = path
    for path in Path(cache).rglob('*.tgz'):
        with tarfile.open(path) as archive:
            member = next((m for m in archive.getmembers() if re.fullmatch('[^/]+/Chart.yaml', m.name)), None)
            if member:
                meta = yaml.load(archive.extractfile(member), Loader=LOADER)
                result[(meta['name'], str(meta['version']).lstrip('v'))] = path
    return result


def render(root, env, charts, platform_profile='aks'):
    output = {}
    def kustomize(path):
        return documents(run(['kubectl', 'kustomize', root / path]))
    apps = kustomize('platform/argocd/environments/' + env)
    if env == 'aks' and platform_profile != 'aks':
        runtime = next(a for a in apps if a.get('kind') == 'Application'
                       and a['metadata']['name'] == 'eurotransit-platform-runtime')
        assert runtime['spec']['source']['path'] == 'platform/environments/aks'
        runtime['spec']['source']['path'] = 'platform/environments/' + platform_profile
    output['argocd-applications'] = apps
    output['root-application'] = kustomize('apps/argocd-apps/environments/' + env)
    for app in apps:
        if app.get('kind') != 'Application':
            continue
        name = app['metadata']['name']
        spec = app['spec']
        ns = spec['destination']['namespace']
        for source in spec.get('sources', [spec.get('source', {})]):
            if source.get('chart'):
                key = (source['chart'], str(source['targetRevision']).lstrip('v'))
                cmd = ['helm', 'template', name, charts[key], '--namespace', ns, '--kube-version', '1.33.0', '--include-crds']
                h = source.get('helm', {})
                for value in h.get('valueFiles', []):
                    cmd += ['-f', root / value.removeprefix('$values/')]
                if h.get('values'):
                    cmd += ['-f', '-']
                    raw = subprocess.run([str(x) for x in cmd], input=h['values'], check=True, text=True, capture_output=True).stdout
                else:
                    raw = run(cmd)
                output[name] = documents(raw)
            elif source.get('path') and 'g05-eurotransit/EuroTransit-configuration' in source['repoURL']:
                path = source['path']
                if path.startswith('charts/'):
                    cmd = ['helm', 'template', name, root / path, '--namespace', ns, '--kube-version', '1.33.0', '--include-crds']
                    for value in source['helm']['valueFiles']:
                        cmd += ['-f', root / path / value]
                    output[name] = documents(run(cmd))
                else:
                    output[name] = kustomize(path)
    bootstrap = [('argocd', 'argo-cd', '10.2.2', 'argocd'), ('sealed-secrets', 'sealed-secrets', '2.5.19', 'sealed-secrets')]
    for name, chart, version, ns in bootstrap:
        cmd = ['helm', 'template', name, charts[(chart, version)], '--namespace', ns, '--kube-version', '1.33.0', '--include-crds']
        for value in ['values.yaml', 'values-' + env + '.yaml']:
            path = root / 'platform' / name / value
            if path.exists():
                cmd += ['-f', path]
        output[name] = documents(run(cmd))
    return output


def check_kind_unchanged(current, baseline):
    # The pinned Kind profile renders no random Secret payloads. Compare all data.
    assert current == baseline, 'Kind render changed from baseline'


def check_dashboard_preservation(current, baseline):
    def dashboard_map(docs):
        return {(d['metadata'].get('namespace', ''), d['metadata']['name']): d.get('data', {})
                for d in docs if d.get('kind') == 'ConfigMap'
                and d['metadata'].get('labels', {}).get('grafana_dashboard') == '1'}
    before, after = dashboard_map(baseline), dashboard_map(current)
    assert after.keys() == before.keys(), 'dashboard ConfigMap set changed from baseline'
    assert after == before, 'dashboard content changed from baseline'


def check_filter_preservation(current, previous):
    # New proposals may use a baseline that already includes the drop filter.
    expected = {'action': 'drop', 'sourceLabels': ['__name__'],
                'regex': 'apiserver_(request_duration_seconds|request_body_size_bytes|request_sizes|response_sizes|response_size_bytes)_(bucket|sum|count)'}
    assert current and current[-1] == expected, 'unexpected API server drop filter'
    assert current == previous or current[:-1] == previous, 'chart default API server filter changed'


def quantity(value, cpu=False):
    s = str(value)
    units = {'Ki': 1/1024, 'Mi': 1, 'Gi': 1024, 'Ti': 1024**2, 'K': 1000/1024**2, 'M': 1000**2/1024**2, 'G': 1000**3/1024**2}
    if cpu:
        return float(s[:-1]) / 1000 if s.endswith('m') else float(s)
    for suffix, factor in units.items():
        if s.endswith(suffix):
            return float(s[:-len(suffix)]) * factor
    return float(s) / 1024**2


def effective(pod):
    # Restartable init sidecars count during app execution and subsequent init.
    app = sum(quantity(c.get('resources', {}).get('requests', {}).get('memory', 0)) for c in pod.get('containers', []))
    sidecars, init_peak = 0, 0
    for c in pod.get('initContainers', []):
        req = quantity(c.get('resources', {}).get('requests', {}).get('memory', 0))
        if c.get('restartPolicy') == 'Always':
            sidecars += req
            init_peak = max(init_peak, sidecars)
        else:
            init_peak = max(init_peak, sidecars + req)
    return max(app + sidecars, init_peak) + quantity(pod.get('overhead', {}).get('memory', 0))


def eraser_requests(pods):
    erasers = [x for x in pods if 'eraser-aks-' in x['metadata']['name']]
    return {
        'eraser_request_per_node_mib': max((effective(x['spec']) for x in erasers), default=None),
        'observed_active_eraser_requests_mib': sum(
            effective(x['spec']) for x in erasers
            if x.get('status', {}).get('phase') not in ['Succeeded', 'Failed']),
    }


def audit(rendered, strict, nodes):
    seen, rows, errors = {}, [], []
    namespaces = {'argocd': 'argocd', 'sealed-secrets': 'sealed-secrets'}
    namespaces.update({d['metadata']['name']: d['spec']['destination']['namespace']
                       for d in rendered.get('argocd-applications', [])
                       if d.get('kind') == 'Application'})
    cluster_kinds = {'Namespace', 'CustomResourceDefinition', 'ClusterRole',
                     'ClusterRoleBinding', 'APIService', 'IngressClass', 'PriorityClass',
                     'MutatingWebhookConfiguration', 'ValidatingWebhookConfiguration',
                     'PodSecurityPolicy', 'ClusterIssuer'}
    cluster_crs = {(d['spec']['group'], d['spec']['names']['kind'])
                   for docs in rendered.values() for d in docs
                   if d.get('kind') == 'CustomResourceDefinition'
                   and d['spec']['scope'] == 'Cluster'}
    for owner, docs in rendered.items():
        for d in docs:
            kind, m, s = d.get('kind'), d.get('metadata', {}), d.get('spec', {})
            api = d.get('apiVersion', '')
            group = api.split('/')[0] if '/' in api else ''
            ns = '' if kind in cluster_kinds or (group, kind) in cluster_crs else m.get('namespace', namespaces.get(owner, ''))
            key = (group, kind, ns, m.get('name'))
            if key in seen:
                errors.append(f'duplicate ownership {key}: {seen[key]}, {owner}')
            seen[key] = owner
            pod, replicas, temporary = None, 1, False
            if kind in ['Deployment', 'StatefulSet', 'DaemonSet', 'Job', 'Rollout']:
                pod = s.get('template', {}).get('spec', {})
                replicas = nodes if kind == 'DaemonSet' else s.get('replicas', s.get('parallelism', 1))
                temporary = kind == 'Job'
            elif kind == 'CronJob':
                pod = s['jobTemplate']['spec']['template']['spec']
                temporary = True
            elif kind in ['KafkaConnect', 'KafkaNodePool', 'Cluster', 'Keycloak', 'KeycloakRealmImport']:
                pod = {'containers': [{'name': kind, 'resources': s.get('resources', {})}]}
                replicas = s.get('replicas', s.get('instances', 1))
                temporary = kind == 'KeycloakRealmImport'
            elif kind in ['Prometheus', 'Alertmanager']:
                pod = {'containers': [{'name': kind, 'resources': s.get('resources', {})}] + s.get('containers', [])}
                pod['initContainers'] = s.get('initContainers', [])
                # Prometheus Operator owns both regular and init config reloaders.
                operator = next((x for x in rendered.get('kube-prometheus-stack', []) if x.get('kind') == 'Deployment' and 'operator' in x['metadata']['name']), None)
                if operator:
                    args = operator['spec']['template']['spec']['containers'][0].get('args', [])
                    values = dict(x.removeprefix('--').split('=', 1) for x in args if x.startswith('--') and '=' in x)
                    resources = {t: {q: values.get('config-reloader-' + q + ('-request' if t == 'requests' else '-limit'), 0) for q in ['cpu', 'memory']} for t in ['requests', 'limits']}
                    pod['containers'].append({'name': 'config-reloader', 'resources': resources})
                    pod['initContainers'].append({'name': 'init-config-reloader', 'resources': resources})
                replicas = s.get('replicas', 1)
            elif kind == 'Kafka':
                entity = s.get('entityOperator', {})
                pod = {'containers': [{'name': n, 'resources': cfg.get('resources', {})} for n, cfg in entity.items() if n in ['topicOperator', 'userOperator']]}
            if replicas == 0:
                continue
            if not pod or not pod.get('containers'):
                continue
            for c in pod.get('containers', []) + pod.get('initContainers', []):
                r = c.get('resources', {})
                for q in ['cpu', 'memory']:
                    req, lim = r.get('requests', {}).get(q), r.get('limits', {}).get(q)
                    label = f'{owner}/{kind}/{m.get("name")}/{c["name"]}/{q}'
                    if req is None or lim is None:
                        if strict:
                            errors.append('missing request/limit: ' + label)
                    elif quantity(req, q == 'cpu') > quantity(lim, q == 'cpu'):
                        errors.append('request exceeds limit: ' + label)
            mem = effective(pod)
            surge = 0
            if kind == 'Deployment' and s.get('strategy', {}).get('type', 'RollingUpdate') == 'RollingUpdate':
                value = s.get('strategy', {}).get('rollingUpdate', {}).get('maxSurge', '25%')
                surge = math.ceil(replicas * int(value[:-1]) / 100) if isinstance(value, str) and value.endswith('%') else int(value)
            if kind == 'Cluster':
                rows.append({'owner': owner, 'kind': 'CNPG bootstrap job', 'name': m.get('name'), 'replicas': 1, 'pod_request_mib': mem, 'request_mib': mem, 'temporary': True, 'rollout_surge_mib': 0})
            rows.append({'owner': owner, 'kind': kind, 'name': m.get('name'), 'replicas': replicas, 'pod_request_mib': mem, 'request_mib': mem * replicas, 'temporary': temporary, 'rollout_surge_mib': surge * mem})
    if errors:
        raise AssertionError('\n'.join(errors))
    return rows


def preserve_cpu(rendered, baseline):
    def fields(value, path=()):
        result = {}
        if isinstance(value, dict):
            r = value.get('resources', {})
            if isinstance(r, dict):
                for t in ['requests', 'limits']:
                    cpu = r.get(t, {}).get('cpu')
                    if cpu is not None and isinstance(cpu, (str, int, float)):
                        result[path + (t,)] = quantity(cpu, cpu=True)
            for key, item in value.items():
                result.update(fields(item, path + (key,)))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                label = item.get('name', index) if isinstance(item, dict) else index
                result.update(fields(item, path + (label,)))
        return result
    identity = lambda d: (d.get('apiVersion'), d.get('kind'), d.get('metadata', {}).get('namespace'), d.get('metadata', {}).get('name'))
    updated = {identity(d): d for docs in rendered.values() for d in docs}
    for docs in baseline.values():
        for d in docs:
            current = updated.get(identity(d))
            if current is not None:
                before, after = fields(d), fields(current)
                for path, cpu in before.items():
                    assert after.get(path) == cpu, 'existing CPU budget changed: ' + str(identity(d)) + str(path)
    print('Existing rendered CPU requests/limits preserved')


def topology(rendered, baseline=None):
    all_docs = [d for docs in rendered.values() for d in docs]
    connect = [d for d in all_docs if d.get('kind') == 'KafkaConnect']
    connectors = [d for d in all_docs if d.get('kind') == 'KafkaConnector']
    assert len(connect) == 1 and connect[0]['metadata']['name'] == 'orders-outbox-connect'
    assert len(connectors) == 3
    assert all(d['metadata']['labels']['strimzi.io/cluster'] == 'orders-outbox-connect' and d['spec']['tasksMax'] == 1 for d in connectors)
    kafka = next(d for d in all_docs if d.get('kind') == 'Kafka')
    assert 'userOperator' not in kafka['spec']['entityOperator'] and 'topicOperator' in kafka['spec']['entityOperator']
    argo = [d for d in rendered['argocd'] if d.get('kind') in ['Deployment', 'StatefulSet']]
    assert not any(re.search('dex|applicationset', d['metadata']['name']) and d['spec'].get('replicas', 1) > 0 for d in argo)
    grafana = next(d for d in rendered['kube-prometheus-stack'] if d.get('kind') == 'Deployment' and 'grafana' in d['metadata']['name'])
    pod = grafana['spec']['template']['spec']
    assert len(pod['containers']) == 1
    mounts = pod['containers'][0]['volumeMounts']
    assert not any(m.get('subPath') for m in mounts if m['mountPath'].startswith(('/var/lib/grafana/dashboards', '/etc/grafana/provisioning')))
    cms = {d['metadata']['name']: d for d in all_docs if d.get('kind') == 'ConfigMap'}
    dashboards = {name for name, d in cms.items() if d['metadata'].get('labels', {}).get('grafana_dashboard') == '1'}
    mounted = {v['configMap']['name'] for v in pod['volumes'] if 'configMap' in v}
    assert dashboards <= mounted, 'unmounted dashboards: ' + str(dashboards - mounted)
    datasource = [d for name, d in cms.items() if name in mounted and any('datasource' in key for key in d.get('data', {}))]
    assert datasource, 'missing static datasource provisioning'
    provider_docs = [yaml.load(value, Loader=LOADER) for name, d in cms.items() if name in mounted for key, value in d.get('data', {}).items() if key == 'dashboardproviders.yaml']
    assert len(provider_docs) == 1, 'missing/ambiguous file dashboard provider'
    providers = provider_docs[0]['providers']
    assert len(providers) == 1 and providers[0]['type'] == 'file'
    assert providers[0]['options']['path'] == '/var/lib/grafana/dashboards'
    assert providers[0]['updateIntervalSeconds'] == 30
    if baseline:
        old = [d for docs in baseline.values() for d in docs]
        old_connectors = {d['metadata']['name']: d for d in old if d.get('kind') == 'KafkaConnector'}
        for connector in connectors:
            assert connector['spec'] == old_connectors[connector['metadata']['name']]['spec'], 'connector behavior/config changed'
        old_worker = next(d for d in old if d.get('kind') == 'KafkaConnect' and d['metadata']['name'] == 'orders-outbox-connect')
        assert connect[0]['spec']['config'] == old_worker['spec']['config'], 'Connect group/internal topics changed'
        assert connect[0]['spec']['jvmOptions'] == old_worker['spec']['jvmOptions'], 'Connect heap changed'
        secret_refs = {e['name']: e.get('valueFrom', {}).get('secretKeyRef', {}) for e in connect[0]['spec']['template']['connectContainer']['env']}
        for service in ['orders', 'inventory', 'payments']:
            assert secret_refs[service.upper() + '_DB_PASSWORD'] == {'name': service + '-db-credentials', 'key': 'password'}
        old_cms = {d['metadata']['name']: d for d in old if d.get('kind') == 'ConfigMap'}
        check_dashboard_preservation(all_docs, old)
        for d in datasource:
            assert d['data'] == old_cms[d['metadata']['name']]['data'], 'datasource content changed'
        rules = lambda docs: {d['metadata']['name']: d['spec'] for d in docs if d.get('kind') == 'PrometheusRule'}
        assert rules(all_docs) == rules(old), 'alert/recording rules changed'
        apiserver = lambda docs: next(d for d in docs if d.get('kind') == 'ServiceMonitor' and 'apiserver' in d['metadata']['name'])
        previous = apiserver(old)['spec']['endpoints'][0]['metricRelabelings']
        current = apiserver(all_docs)['spec']['endpoints'][0]['metricRelabelings']
        check_filter_preservation(current, previous)
        drop = current[-1]
        assert drop['action'] == 'drop' and drop['sourceLabels'] == ['__name__']
        assert drop['regex'] == 'apiserver_(request_duration_seconds|request_body_size_bytes|request_sizes|response_sizes|response_size_bytes)_(bucket|sum|count)', 'unexpected API server drop families'
        expression = re.compile(drop['regex'])
        assert expression.fullmatch('apiserver_request_duration_seconds_bucket')
        for name in ['apiserver_request_sli_duration_seconds_bucket', 'apiserver_request_total', 'apiserver_client_certificate_expiration_seconds_bucket', 'container_memory_working_set_bytes', 'node_memory_MemAvailable_bytes']:
            assert not expression.fullmatch(name), 'required metric dropped: ' + name
        for d in all_docs:
            texts = list(d.get('data', {}).values()) if d.get('kind') == 'ConfigMap' and d['metadata']['name'] in dashboards else [yaml.safe_dump(d['spec'])] if d.get('kind') == 'PrometheusRule' else []
            for value in texts:
                for metric in re.findall(r'apiserver_[a-zA-Z0-9_:]+', value):
                    assert not expression.fullmatch(metric), 'dashboard/rule references dropped metric: ' + metric
        for kind in ['Prometheus']:
            original = next(d for d in old if d.get('kind') == kind)['spec']
            updated = next(d for d in all_docs if d.get('kind') == kind)['spec']
            for key in ['retention', 'scrapeInterval', 'evaluationInterval']:
                assert original.get(key) == updated.get(key), key + ' changed'
        print('Baseline: dashboard/datasource content, rules, retention and intervals preserved; filter preserves chart defaults and required metric families')
    print(f'AKS topology: 1 Connect, 3 connectors, 1 Grafana container, {len(dashboards)} dashboard ConfigMaps mounted; Dex/User Operator absent, ApplicationSet disabled')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--chart-cache', type=Path, default=Path.home() / '.cache/helm/content')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--baseline-root', type=Path)
    p.add_argument('--budgets', action='store_true')
    p.add_argument('--nodes', type=int, default=3)
    p.add_argument('--platform-profile', choices=['aks', 'aks-ha'], default='aks',
                   help='Offline AKS runtime source substitution only; does not modify GitOps owners')
    p.add_argument('--inventory-pods', type=Path)
    p.add_argument('--inventory-nodes', type=Path)
    args = p.parse_args()
    if args.nodes < 1:
        p.error('--nodes must be positive')
    if args.inventory_nodes and len(json.loads(args.inventory_nodes.read_text())['items']) != args.nodes:
        p.error('--nodes must match the saved node inventory')
    charts = chart_index(args.chart_cache)
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.output.chmod(0o700)
    os.umask(0o077)
    rendered = {env: render(args.root, env, charts, args.platform_profile) for env in ['aks', 'kind']}
    for env, manifests in rendered.items():
        for owner, docs in manifests.items():
            (args.output / (env + '-' + owner + '.yaml')).write_text(yaml.dump_all(docs, sort_keys=False, Dumper=DUMPER))
    if args.baseline_root:
        before = render(args.baseline_root, 'kind', charts)
        check_kind_unchanged(rendered['kind'], before)
        print('Kind: all pinned Helm and Kustomize fields, including Secret data, identical to baseline')
    baseline = render(args.baseline_root, 'aks', charts) if args.baseline_root else None
    topology(rendered['aks'], baseline)
    if args.budgets and baseline:
        preserve_cpu(rendered['aks'], baseline)
    rows = audit(rendered['aks'], args.budgets, args.nodes)
    report = {'nodes_assumed': args.nodes, 'rows': rows, 'steady_project_requests_mib': sum(r['request_mib'] for r in rows if not r['temporary']), 'temporary_requests_mib': sum(r['request_mib'] for r in rows if r['temporary']), 'largest_single_deployment_surge_mib': max((r['rollout_surge_mib'] for r in rows), default=0), 'all_deployments_surge_mib': sum(r['rollout_surge_mib'] for r in rows)}
    if args.inventory_pods:
        pods = json.loads(args.inventory_pods.read_text())['items']
        managed = [x for x in pods if x['metadata']['namespace'] in ['kube-system', 'gatekeeper-system'] and 'eraser-aks-' not in x['metadata']['name'] and x.get('status', {}).get('phase') not in ['Succeeded', 'Failed']]
        report['observed_managed_requests_mib'] = sum(effective(x['spec']) for x in managed)
        report['observed_managed_by_node_mib'] = {node: sum(effective(x['spec']) for x in managed if x['spec'].get('nodeName') == node) for node in {x['spec'].get('nodeName') for x in managed}}
        report.update(eraser_requests(pods))
    if args.inventory_nodes:
        nodes = json.loads(args.inventory_nodes.read_text())['items']
        report['observed_allocatable_by_node_mib'] = {x['metadata']['name']: quantity(x['status']['allocatable']['memory']) for x in nodes}
        report['observed_allocatable_mib'] = sum(report['observed_allocatable_by_node_mib'].values())
        if 'observed_managed_requests_mib' in report:
            report['estimated_steady_headroom_mib'] = report['observed_allocatable_mib'] - report['observed_managed_requests_mib'] - report['steady_project_requests_mib']
            report['estimated_headroom_all_temporary_and_one_rollout_mib'] = report['estimated_steady_headroom_mib'] - report['temporary_requests_mib'] - report['largest_single_deployment_surge_mib']
            report['estimated_headroom_observed_active_erasers_mib'] = report['estimated_steady_headroom_mib'] - report['observed_active_eraser_requests_mib']
            eraser_request = report['eraser_request_per_node_mib']
            report['estimated_headroom_three_erasers_mib'] = (
                report['estimated_steady_headroom_mib'] - args.nodes * eraser_request
                if eraser_request is not None else None)
    (args.output / 'budget.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ['rows', 'observed_managed_by_node_mib', 'observed_allocatable_by_node_mib']}, indent=2))
    print('Render and checks passed; budget uses owner CR resources, config reloaders and effective init requests. Operator-created bootstrap/realm-import pods require live inventory validation.')


if __name__ == '__main__':
    main()
