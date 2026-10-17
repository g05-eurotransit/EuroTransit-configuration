#!/usr/bin/env python3
"""Check rendered HA safety invariants without cluster credentials or a live cluster."""
from pathlib import Path
import subprocess
import unittest
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(*args):
    return list(yaml.safe_load_all(subprocess.check_output(args, cwd=ROOT, text=True)))


def resource(docs, kind, name):
    return next(d for d in docs if d and d['kind'] == kind and d['metadata']['name'] == name)


class KindHAProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.platform = render('kubectl', 'kustomize', 'platform/environments/kind-ha')
        cls.connect = render('kubectl', 'kustomize', 'platform/connectors/environments/kind-ha')
        cls.apps = render('helm', 'template', 'eurotransit', 'charts/eurotransit',
                          '-f', 'charts/eurotransit/values.yaml',
                          '-f', 'charts/eurotransit/values-kind-ha.yaml')

    def test_three_workers_separate_from_control_plane(self):
        config = yaml.safe_load((ROOT / 'platform/kind/kind-ha-config.yaml').read_text())
        self.assertEqual([n['role'] for n in config['nodes']],
                         ['control-plane', 'worker', 'worker', 'worker'])

    def test_standby_tcp_timeout_is_ha_only(self):
        ha = yaml.safe_load((ROOT / 'platform/cloudnativepg/values-kind-ha.yaml').read_text())
        self.assertEqual(ha['config']['data']['STANDBY_TCP_USER_TIMEOUT'], '5000')
        for name in ('values.yaml', 'values-kind.yaml'):
            default = yaml.safe_load((ROOT / 'platform/cloudnativepg' / name).read_text())
            self.assertNotIn('STANDBY_TCP_USER_TIMEOUT', default.get('config', {}).get('data', {}))

    def test_connector_restart_policy_has_bounded_detection(self):
        ha = yaml.safe_load((ROOT / 'platform/strimzi/values-kind-ha.yaml').read_text())
        self.assertEqual(ha['fullReconciliationIntervalMs'], 15000)
        for connector in (d for d in self.connect if d and d['kind'] == 'KafkaConnector'):
            self.assertEqual(connector['spec']['autoRestart'], {'enabled': True, 'maxRestarts': 10})

    def test_database_durability_and_failure_domains(self):
        spec = resource(self.platform, 'Cluster', 'eurotransit-postgres')['spec']
        self.assertEqual(spec['instances'], 3)
        self.assertEqual(spec['postgresql']['synchronous'],
                         {'method': 'any', 'number': 1, 'dataDurability': 'required'})
        self.assertEqual(spec['affinity']['podAntiAffinityType'], 'required')
        self.assertEqual(spec['affinity']['topologyKey'], 'kubernetes.io/hostname')
        params = spec['postgresql']['parameters']
        self.assertEqual(params['pg_failover_slots.standby_slots_min_confirmed'], '1')
        self.assertEqual(len(params['pg_failover_slots.standby_slot_names'].split(',')), 3)
        self.assertEqual(params['hot_standby_feedback'], 'on')

    def test_kafka_survives_one_broker_loss(self):
        pool = resource(self.platform, 'KafkaNodePool', 'dual-role')['spec']
        self.assertEqual(pool['replicas'], 3)
        self.assertEqual(pool['storage']['type'], 'persistent-claim')
        self.assertTrue(pool['template']['pod']['affinity']['podAntiAffinity']
                        ['requiredDuringSchedulingIgnoredDuringExecution'])
        kafka = resource(self.platform, 'Kafka', 'eurotransit-kafka')['spec']['kafka']
        self.assertEqual(kafka['config']['min.insync.replicas'], 2)
        for topic in (d for d in self.platform if d and d['kind'] == 'KafkaTopic'):
            with self.subTest(topic=topic['metadata']['name']):
                self.assertEqual(topic['spec']['replicas'], 3)

    def test_idle_heartbeat_is_ha_only_and_bypasses_outbox_routing(self):
        topics = {d['spec']['topicName']: d['spec'] for d in self.connect
                  if d and d['kind'] == 'KafkaTopic'}
        self.assertEqual(set(topics), {topic for service in ('orders', 'inventory', 'payments')
                                      for topic in ('__debezium-heartbeat.' + service, service + '.message')})
        self.assertTrue(all(t['replicas'] == 3 and t['config']['min.insync.replicas'] == 2
                            for t in topics.values()))
        for connector in (d for d in self.connect if d and d['kind'] == 'KafkaConnector'):
            config = connector['spec']['config']
            self.assertEqual(config['heartbeat.interval.ms'], 10000)
            self.assertIn('pg_logical_emit_message(true,', config['heartbeat.action.query'])
            self.assertEqual(config['message.prefix.include.list'], 'eurotransit_kind_heartbeat')
            self.assertEqual(config['transforms.outbox.predicate'], 'outboxTable')
            pattern = config['predicates.outboxTable.pattern']
            self.assertIsNotNone(re.fullmatch(pattern, config['topic.prefix'] + '.public.outbox_events'))
            self.assertIsNone(re.fullmatch(pattern, '__debezium-heartbeat.' + config['topic.prefix']))
            self.assertIsNone(re.fullmatch(pattern, config['topic.prefix'] + '.message'))
        for profile in ('kind', 'aks'):
            docs = render('kubectl', 'kustomize', 'platform/connectors/environments/' + profile)
            for connector in (d for d in docs if d and d['kind'] == 'KafkaConnector'):
                self.assertNotIn('heartbeat.action.query', connector['spec']['config'])

    def test_critical_backends_have_separate_replicas_and_budgets(self):
        for name in ('catalog', 'orders', 'inventory', 'payments'):
            with self.subTest(service=name):
                deployment = resource(self.apps, 'Deployment', name)['spec']
                self.assertEqual(deployment['replicas'], 2)
                pod = deployment['template']['spec']
                self.assertTrue(pod['affinity']['podAntiAffinity']
                                ['requiredDuringSchedulingIgnoredDuringExecution'])
                container = pod['containers'][0]
                self.assertTrue(container['resources']['requests']['memory'])
                self.assertTrue(container['resources']['limits']['memory'])
                self.assertEqual(resource(self.apps, 'PodDisruptionBudget', name)
                                 ['spec']['minAvailable'], 1)

    def test_catalog_failover_retries_only_get(self):
        route = resource(self.apps, 'IngressRoute', 'eurotransit-public-api')
        retried = [r for r in route['spec']['routes'] if any(m['name']=='eurotransit-catalog-failover' for m in r.get('middlewares',[]))]
        self.assertEqual(len(retried), 1)
        self.assertIn('Method(`GET`)', retried[0]['match'])
        self.assertIn('/api/catalog', retried[0]['match'])
        self.assertEqual(resource(self.apps,'Middleware','eurotransit-catalog-failover')['spec']['retry']['attempts'],2)
        for profile in ('kind','production'):
            docs = render('helm','template','eurotransit','charts/eurotransit','-f','charts/eurotransit/values.yaml','-f','charts/eurotransit/values-'+profile+'.yaml')
            self.assertFalse(any(d and d.get('kind') in ('Middleware','ServersTransport') and d['metadata']['name']=='eurotransit-catalog-failover' for d in docs))

    def test_database_pool_settings_are_opt_in(self):
        for name in ('orders', 'inventory', 'payments'):
            container = resource(self.apps, 'Deployment', name)['spec']['template']['spec']['containers'][0]
            env = {e['name']: e.get('value') for e in container['env']}
            self.assertEqual(env['SPRING_R2DBC_POOL_MAX_ACQUIRE_TIME'], '3s')
            self.assertEqual(env['SPRING_R2DBC_POOL_MAX_VALIDATION_TIME'], '1s')
            self.assertEqual(env['SPRING_R2DBC_POOL_VALIDATION_QUERY'], 'SELECT 1')
            self.assertEqual(env['SPRING_R2DBC_POOL_MAX_IDLE_TIME'], '10s')
        for profile in ('kind', 'production'):
            docs = render('helm', 'template', 'eurotransit', 'charts/eurotransit',
                          '-f', 'charts/eurotransit/values.yaml',
                          '-f', 'charts/eurotransit/values-' + profile + '.yaml')
            container = resource(docs, 'Deployment', 'orders')['spec']['template']['spec']['containers'][0]
            self.assertFalse(any(e['name'].startswith('SPRING_R2DBC_POOL_') for e in container['env']))

    def test_rollouts_retain_replica_count_and_use_supported_canary_scaling(self):
        docs = render('helm', 'template', 'eurotransit', 'charts/eurotransit',
                      '-f', 'charts/eurotransit/values-kind-ha.yaml',
                      '--set', 'progressiveDelivery.enabled=true')
        for service in ('orders', 'catalog'):
            self.assertEqual(resource(docs, 'Rollout', service)['spec']['replicas'], 2)
        canary = resource(docs, 'Rollout', 'orders')['spec']['strategy']['canary']
        self.assertNotIn('canaryReplicaCount', canary)
        self.assertEqual(canary['steps'][0]['setCanaryScale'], {'replicas': 1})

    def test_pinned_rollouts_controller_uses_installed_traefik_api(self):
        args = ['--traefik-api-group=traefik.io', '--traefik-api-version=traefik.io/v1alpha1']
        ha = yaml.safe_load((ROOT / 'platform/argo-rollouts/values-kind-ha.yaml').read_text())
        self.assertEqual(ha['controller']['extraArgs'], args)
        apps = list(yaml.safe_load_all((ROOT / 'platform/argocd/base/platform-applications.yaml').read_text()))
        app = resource(apps, 'Application', 'argo-rollouts')
        self.assertEqual(app['spec']['source']['targetRevision'], '2.41.1')
        values = yaml.safe_load(app['spec']['source']['helm']['values'])
        self.assertEqual(values['controller']['extraArgs'], args)

    def test_shared_connect_cluster_is_redundant_with_all_credentials(self):
        clusters = [d for d in self.connect if d and d['kind'] == 'KafkaConnect']
        self.assertEqual(len(clusters), 1)
        spec = clusters[0]['spec']
        self.assertEqual(spec['replicas'], 2)
        self.assertEqual(spec['config']['offset.storage.replication.factor'], 3)
        self.assertEqual(spec['config']['scheduled.rebalance.max.delay.ms'], 10000)
        self.assertEqual(spec['config']['offset.flush.interval.ms'], 5000)
        env = spec['template']['connectContainer']['env']
        self.assertEqual({e['name'] for e in env},
                         {'ORDERS_DB_PASSWORD', 'INVENTORY_DB_PASSWORD', 'PAYMENTS_DB_PASSWORD'})
        connectors = [d for d in self.connect if d and d['kind'] == 'KafkaConnector']
        self.assertEqual(len(connectors), 3)
        self.assertTrue(all(d['metadata']['labels']['strimzi.io/cluster'] ==
                            'orders-outbox-connect' for d in connectors))
        self.assertTrue(spec['template']['pod']['affinity']['podAntiAffinity']
                        ['requiredDuringSchedulingIgnoredDuringExecution'])

    def test_dev_and_aks_remain_single_instance(self):
        for environment in ('kind', 'aks'):
            with self.subTest(environment=environment):
                docs = render('kubectl', 'kustomize', 'platform/environments/' + environment)
                self.assertEqual(resource(docs, 'Cluster', 'eurotransit-postgres')
                                 ['spec']['instances'], 1)


if __name__ == '__main__':
    unittest.main()
