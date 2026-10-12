#!/usr/bin/env python3
"""Render both environments and execute synthetic gates with a local promtool.

Usage: python3 scripts/test-orders-canary-guardrails.py --promtool /path/to/promtool
Without promtool this performs rendering/condition checks and writes the fixture;
it does not claim to execute PromQL.
"""
import argparse
import copy
from pathlib import Path
import re
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]

def render(environment, enabled):
    command = ['helm', 'template', 'eurotransit', str(ROOT / 'charts/eurotransit'),
               '--namespace', 'eurotransit', '-f', str(ROOT / f'charts/eurotransit/values-{environment}.yaml'),
               '--set', f'progressiveDelivery.enabled={str(enabled).lower()}']
    documents = list(yaml.safe_load_all(subprocess.check_output(command, text=True)))
    analyses = [d for d in documents if d and d.get('kind') == 'AnalysisTemplate']
    assert bool(analyses) == enabled, (environment, enabled)
    if enabled:
        return next(d['spec']['metrics'] for d in analyses if d['metadata']['name'] == 'orders-canary-guardrails')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--promtool')
    parser.add_argument('--fixture', default='/tmp/orders-canary-guardrails.test.yaml')
    args = parser.parse_args()
    metrics = None
    for env in ['kind', 'production']:
        render(env, False)
        rendered = render(env, True)
        if metrics:
            assert rendered == metrics
        metrics = rendered
    assert len(metrics) == 8
    assert all(m['failureLimit'] == 0 and m['count'] == 2 for m in metrics)
    assert not any('orders_events_dlt_total' in m['provider']['prometheus']['query'] for m in metrics)
    labels = 'rollouts_pod_template_hash="canary",instance="pod:8080"'
    healthy = [
        {'series': f'up{{{labels},service="orders-canary"}}', 'values': '1+0x10'},
        {'series': f'process_start_time_seconds{{{labels}}}', 'values': '-600+0x10'},
        {'series': f'orders_checkout_completed_total{{{labels},result="confirmed"}}', 'values': '0+1x10'},
        {'series': f'orders_checkout_completed_total{{{labels},result="failed"}}', 'values': '0+0x10'},
        {'series': f'orders_checkout_failed_total{{{labels},reason="payment_declined"}}', 'values': '0+0x10'},
        {'series': f'http_server_requests_seconds_count{{{labels},app="orders",method="POST",uri="/orders",status="200"}}', 'values': '0+2x10'},
    ]
    for topic in ['order-placed', 'refund-requested']:
        for failure_class in ['poison_payload', 'dependency_error', 'unknown']:
            healthy.append({'series': f'orders_events_exhausted_total{{{labels},topic="{topic}",failure_class="{failure_class}"}}', 'values': '0+0x10'})
    for le in ['0.1', '1', '+Inf']:
        healthy.append({'series': f'http_server_requests_seconds_bucket{{{labels},app="orders",le="{le}"}}', 'values': '0+2x10'})
    def changed(series, match, values):
        result = copy.deepcopy(series)
        next(s for s in result if match in s['series'])['values'] = values
        return result
    scenarios = [('healthy', healthy, set()),
                 ('insufficient-confirmations', changed(healthy, 'result="confirmed"', '0+0x10'), {'canary-confirmed-checkouts'}),
                 ('actuator-traffic-is-not-http-evidence', [dict(item, series=item['series'].replace('uri="/orders"', 'uri="/actuator/prometheus"')) for item in healthy], {'canary-http-samples'}),
                 ('expected-payment-decline-invalidates-success-fixture', changed(healthy, 'orders_checkout_failed', '0+0x9 1'), {'canary-checkout-failures'}),
                 ('fresh-first-http-5xx', healthy + [{'series': f'http_server_requests_seconds_count{{{labels},app="orders",status="500"}}', 'values': '_ _ _ _ _ _ _ _ _ _ 1'}], {'http-5xx-count'}),
                 ('emitter-exhaustion-reader-location-irrelevant', changed(healthy, 'failure_class="dependency_error"', '0+0x9 1'), {'canary-exhausted-events'}),
                 ('missing-required-exhaustion-series', [s for s in healthy if not ('topic="refund-requested"' in s['series'] and 'failure_class="unknown"' in s['series'])], {'canary-metric-coverage'}),
                 ('missing-checkout-failure-metric', [s for s in healthy if 'orders_checkout_failed' not in s['series']], {'canary-metric-coverage'}),
                 ('scrape-down', changed(healthy, 'up{', '0+0x10'), {'canary-metric-coverage'}),
                 ('counter-reset', changed(healthy, 'result="confirmed"', '0+1x7 0 1 2'), {'canary-counter-continuity'}),
                 ('young-restarted-process', changed(healthy, 'process_start_time', '100+0x10'), {'canary-metric-coverage'})]
    # Duplicate discovery through both stable and canary Services must not double evidence.
    duplicate = copy.deepcopy(healthy)
    for item in healthy:
        clone = copy.deepcopy(item)
        if 'service=' in clone['series']:
            clone['series'] = clone['series'].replace('orders-canary', 'orders')
        else:
            clone['series'] = clone['series'].replace('instance="pod:8080"', 'instance="pod:8080",service="orders"')
        duplicate.append(clone)
    scenarios.append(('duplicate-service-discovery', duplicate, set()))
    fixture = {'rule_files': [], 'evaluation_interval': '30s', 'tests': []}
    for name, series, failures in scenarios:
        expressions = []
        for metric in metrics:
            condition = re.fullmatch(r'len\(result\) == 1 && result\[0\] (>=|<=|==|<) ([0-9.]+)', metric['successCondition'])
            assert condition, metric
            query = metric['provider']['prometheus']['query'].replace('{{args.canary-hash}}', 'canary').strip()
            # PromQL's bool comparison evaluates the actual rendered numeric predicate.
            expressions.append({'expr': f'({query}) {condition[1]} bool {condition[2]}',
                                'eval_time': '5m', 'exp_samples': [{'labels': '{}', 'value': int(metric['name'] not in failures)}]})
        fixture['tests'].append({'name': name, 'interval': '30s', 'input_series': series, 'promql_expr_test': expressions})
    # No targets must fail the independent coverage check even if error vectors fall back to zero.
    coverage = metrics[0]['provider']['prometheus']['query'].replace('{{args.canary-hash}}', 'canary').strip()
    fixture['tests'].append({'name': 'no-scrape-targets', 'interval': '30s', 'input_series': [],
                             'promql_expr_test': [{'expr': f'({coverage}) == bool 0', 'eval_time': '5m', 'exp_samples': [{'labels': '{}', 'value': 0}]}]})
    Path(args.fixture).write_text(yaml.safe_dump(fixture, sort_keys=False))
    print('PASS: kind/AKS enabled and disabled render; eight fail-closed metric conditions; fixture generated.')
    if args.promtool:
        subprocess.run([args.promtool, 'test', 'rules', args.fixture], check=True)
    else:
        print(f'PromQL execution pending: use --promtool. Fixture: {args.fixture}')

if __name__ == '__main__':
    main()
