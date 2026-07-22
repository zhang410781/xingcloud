from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from aiops.business_context import assign_alert_context, validate_context_bindings
from aiops.models import AIOpsKnowledgeEnvironment
from ops.anomaly_detection import detect_anomaly
from ops.models import Alert, AlertNotificationPolicy, AlertRule, K8sCluster, LogDataSource, MetricDataSource, TaskResource, TaskResourceGroup
from ops.observability_evidence import _k8s_evidence, _log_evidence, _series_values, collect_observability_evidence, inspection_result


class BusinessContextTests(TestCase):
    def setUp(self):
        self.metric = MetricDataSource.objects.create(name='ctx-prom', environment='xing-prod', config={})
        self.logs = LogDataSource.objects.create(name='ctx-logs', provider='elk', config={})
        self.cluster = K8sCluster.objects.create(name='ctx-k8s', kubeconfig='apiVersion: v1')
        self.assets = TaskResourceGroup.objects.create(name='生产资产', code='xing-prod', group_type='environment')
        self.cluster_asset = TaskResource.objects.create(
            name='ctx-k8s', resource_type=TaskResource.RESOURCE_K8S,
            environment=self.assets, cluster=self.cluster,
        )
        self.cluster_asset.business_groups.add(self.assets)
        self.context = AIOpsKnowledgeEnvironment.objects.create(
            name='XingCloud 生产',
            code='xing-prod',
            business_line='XingCloud',
            metric_datasource=self.metric,
            log_datasource=self.logs,
            k8s_cluster=self.cluster,
            task_resource_environment=self.assets,
        )

    def test_registered_datasources_can_be_reused(self):
        other_group = TaskResourceGroup.objects.create(name='共享业务', code='shared', group_type='environment')
        context = AIOpsKnowledgeEnvironment.objects.create(
            name='重复使用数据源', code='duplicate', business_line='XingCloud',
            metric_datasource=self.metric, log_datasource=self.logs,
            task_resource_environment=other_group,
        )
        self.assertEqual(context.metric_datasource_id, self.metric.id)
        self.assertEqual(context.log_datasource_id, self.logs.id)

    def test_alert_context_requires_exact_code(self):
        alert = Alert.objects.create(title='test', source='platform', message='test', environment='xing-prod')
        resolved = assign_alert_context(alert)
        self.assertEqual(resolved.id, self.context.id)

        alert.environment = 'XingCloud 生产'
        self.assertIsNone(assign_alert_context(alert))

    def test_binding_health_exposes_all_resources(self):
        result = validate_context_bindings(self.context)
        self.assertTrue(result['ready'])
        self.assertEqual(result['context']['k8s_cluster_id'], self.cluster.id)

    def test_binding_health_reads_clickhouse_collection_field_mapping(self):
        self.logs.provider = 'clickhouse'
        self.logs.config = {
            'default_collection': 'container-logs',
            'collections': [{
                'key': 'container-logs',
                'database': 'logs',
                'table': 'container_logs',
                'time_field': 'event_time',
                'message_fields': 'message,log',
                'level_field': 'level',
                'source_fields': 'namespace,pod_name',
            }],
        }
        self.logs.save(update_fields=['provider', 'config', 'updated_at'])

        result = validate_context_bindings(self.context)
        check = next(item for item in result['checks'] if item['code'] == 'log_field_map')

        self.assertEqual(check['status'], 'ready')
        self.assertEqual(check['detail'], '已配置')

    def test_context_options_are_available_to_authenticated_users(self):
        user = get_user_model().objects.create_user(username='context-viewer', password='test-password')
        self.client.force_login(user)

        response = self.client.get('/api/aiops/knowledge-environments/context-options/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['id'], self.context.id)
        self.assertEqual(response.json()[0]['metric_datasource'], self.metric.id)

    def test_alert_list_filters_by_business_context(self):
        other_context = AIOpsKnowledgeEnvironment.objects.create(
            name='XingCloud 测试', code='xing-test', business_line='XingCloud',
        )
        expected = Alert.objects.create(
            title='production alert', source='platform', message='test', environment='xing-prod',
            knowledge_environment=self.context,
        )
        Alert.objects.create(
            title='test alert', source='platform', message='test', environment='xing-test',
            knowledge_environment=other_context,
        )
        user = get_user_model().objects.create_superuser(username='context-admin', password='test-password')
        self.client.force_login(user)

        response = self.client.get('/api/alerts/', {'knowledge_environment_id': self.context.id})

        self.assertEqual(response.status_code, 200)
        ids = [item['id'] for item in response.json()['results']]
        self.assertEqual(ids, [expected.id])

    def test_alert_rules_and_policies_filter_by_business_context(self):
        other_metric = MetricDataSource.objects.create(name='other-prom', environment='other', config={})
        other_context = AIOpsKnowledgeEnvironment.objects.create(
            name='Other Context', code='other', business_line='Other', metric_datasource=other_metric,
        )
        expected_rule = AlertRule.objects.create(
            name='Context rule', code='context-rule', source_type='prometheus', category='k8s',
            metric_datasource=self.metric, is_template=False,
        )
        AlertRule.objects.create(
            name='Other rule', code='other-rule', source_type='prometheus', category='k8s',
            metric_datasource=other_metric, is_template=False,
        )
        global_policy = AlertNotificationPolicy.objects.create(name='Global policy')
        expected_policy = AlertNotificationPolicy.objects.create(name='Context policy', metric_datasource=self.metric)
        AlertNotificationPolicy.objects.create(name='Other policy', metric_datasource=other_metric)
        user = get_user_model().objects.create_superuser(username='rules-context-admin', password='test-password')
        self.client.force_login(user)

        rule_response = self.client.get('/api/alert-rules/', {
            'knowledge_environment_id': self.context.id,
            'is_template': 'false',
        })
        policy_response = self.client.get('/api/alert-notification-policies/', {
            'knowledge_environment_id': self.context.id,
        })

        self.assertEqual(rule_response.status_code, 200)
        self.assertEqual(policy_response.status_code, 200)
        rule_ids = [item['id'] for item in rule_response.json()['results']]
        policy_ids = [item['id'] for item in policy_response.json()['results']]
        self.assertEqual(rule_ids, [expected_rule.id])
        self.assertCountEqual(policy_ids, [global_policy.id, expected_policy.id])
        self.assertNotEqual(other_context.id, self.context.id)

    @patch('ops.observability_evidence._query_metric')
    @patch('ops.observability_evidence._k8s_evidence')
    def test_inspection_is_deterministic_without_model(self, k8s_evidence, query_metric):
        query_metric.return_value = {
            'code': 'node_count', 'title': '节点数量', 'status': 'ok', 'series_count': 1,
            'sample_count': 2, 'latest': 3, 'anomaly': {'is_anomaly': False},
        }
        k8s_evidence.return_value = {
            'status': 'ok',
            'summary': {'node_count': 3, 'ready_nodes': 3, 'pod_count': 10, 'pod_status': {'Running': 10}},
            'findings': [], 'nodes': [], 'pods': [], 'resources': {},
        }
        evidence = collect_observability_evidence(self.context.id, depth='light')
        result = inspection_result(evidence)
        self.assertEqual(result['health_score'], 100)
        self.assertEqual(result['cluster_summary']['node_count'], 3)
        self.assertTrue(evidence['source_coverage']['assets'])
        self.assertEqual(len(evidence['topology_findings']), 4)

    def test_inspection_score_deducts_same_problem_type_per_target_once(self):
        evidence = {
            'k8s_findings': [],
            'log_findings': [
                {'fingerprint': 'log:api:timeout-a', 'severity': 'warning', 'code': 'log_error', 'target': 'api'},
                {'fingerprint': 'log:api:timeout-b', 'severity': 'warning', 'code': 'log_error', 'target': 'api'},
            ],
            'metric_anomalies': [],
            'diagnostics': [],
        }

        result = inspection_result(evidence)

        self.assertEqual(len(result['findings']), 2)
        self.assertEqual(result['health_score'], 92)
        self.assertEqual(result['score_deductions'], [{
            'code': 'log_error', 'target': 'api', 'namespace': None,
            'severity': 'warning', 'points': 8,
        }])

    @patch('ops.k8s_views.get_k8s_resource_snapshot', return_value=[])
    @patch('ops.k8s_views.get_k8s_pods_snapshot')
    @patch('ops.k8s_views.get_k8s_nodes_snapshot')
    def test_control_plane_inspection_excludes_unrelated_and_historical_pod_restarts(
        self, nodes_snapshot, pods_snapshot, resource_snapshot,
    ):
        nodes_snapshot.return_value = [{'name': 'master', 'status': 'Ready'}]
        pods_snapshot.return_value = [
            {
                'name': 'old-job', 'namespace': 'default', 'status': 'Failed', 'restarts': 20,
                'containers': [{'name': 'job', 'ready': False}],
            },
            {
                'name': 'kube-apiserver-master', 'namespace': 'kube-system', 'status': 'Running', 'restarts': 11,
                'containers': [{'name': 'kube-apiserver', 'ready': True}],
            },
            {
                'name': 'coredns-123', 'namespace': 'kube-system', 'status': 'Running', 'restarts': 5,
                'containers': [{'name': 'coredns', 'ready': False}],
            },
        ]

        result = _k8s_evidence(self.context, 'full', profile='control_plane')

        self.assertEqual([item['name'] for item in result['pods']], ['kube-apiserver-master', 'coredns-123'])
        self.assertEqual(result['summary']['pod_count'], 2)
        self.assertEqual([item['code'] for item in result['findings']], ['pod_not_ready'])
        self.assertNotIn('old-job', str(result['findings']))

    @patch('ops.k8s_views.get_k8s_resource_snapshot', return_value=[])
    @patch('ops.k8s_views.get_k8s_pods_snapshot', return_value=[])
    @patch('ops.k8s_views.get_k8s_nodes_snapshot', return_value=[])
    def test_node_inspection_without_target_does_not_fall_back_to_cluster_resources(
        self, nodes_snapshot, pods_snapshot, resource_snapshot,
    ):
        result = _k8s_evidence(self.context, 'full', profile='node')

        self.assertEqual(result['resources'], {})
        resource_snapshot.assert_not_called()

    @patch('ops.observability_evidence._run_query')
    @patch('ops.observability_evidence._query_metric')
    @patch('ops.observability_evidence._k8s_evidence')
    def test_inspection_collects_bound_elasticsearch_logs(self, k8s_evidence, query_metric, run_query):
        query_metric.return_value = {
            'code': 'node_count', 'title': '节点数量', 'status': 'ok', 'series_count': 1,
            'sample_count': 1, 'latest': 3, 'anomaly': {'is_anomaly': False},
        }
        k8s_evidence.return_value = {
            'status': 'ok', 'summary': {}, 'findings': [], 'nodes': [], 'pods': [], 'resources': {},
        }
        run_query.return_value = {
            'total': 1,
            'logs': [{'level': 'error', 'source': 'api', 'message': 'timeout token=secret-value'}],
        }

        evidence = collect_observability_evidence(self.context.id, depth='light', target='api')

        self.assertTrue(evidence['source_coverage']['logs'])
        self.assertEqual(evidence['logs']['datasource']['id'], self.logs.id)
        self.assertNotIn('secret-value', evidence['logs']['samples'][0]['message'])
        self.assertEqual(evidence['log_findings'][0]['code'], 'log_error')
        self.assertEqual(run_query.call_args.args[0], 'elk')

    @patch('ops.observability_evidence._run_query')
    def test_clickhouse_log_evidence_uses_bound_collection(self, run_query):
        self.logs.provider = 'clickhouse'
        self.logs.config = {'default_collection': 'container-logs'}
        self.logs.save(update_fields=['provider', 'config'])
        run_query.return_value = {'total': 0, 'logs': []}

        result = _log_evidence(self.context, target='ops-agent', window_minutes=30)

        self.assertEqual(result['datasource']['provider'], 'clickhouse')
        self.assertEqual(run_query.call_args.args[0], 'clickhouse')
        self.assertEqual(run_query.call_args.args[2]['collection'], 'container-logs')

    @patch('ops.observability_evidence._run_query')
    def test_control_plane_log_evidence_queries_only_control_plane_components(self, run_query):
        run_query.side_effect = lambda provider, config, payload: {
            'total': 1,
            'logs': [{
                'timestamp': timezone.now().isoformat(), 'level': 'info',
                'source': payload['query'].strip('"'), 'message': 'component healthy',
            }],
        }

        result = _log_evidence(self.context, profile='control_plane', window_minutes=5)

        self.assertEqual(run_query.call_count, 5)
        queries = {call.args[2]['query'] for call in run_query.call_args_list}
        self.assertEqual(queries, {
            '"kube-apiserver"', '"etcd"', '"coredns"',
            '"kube-scheduler"', '"kube-controller-manager"',
        })
        self.assertEqual(result['sample_count'], 5)

    @patch('ops.observability_evidence._run_query')
    def test_alert_log_evidence_uses_alert_start_primary_window_and_baseline(self, run_query):
        starts_at = timezone.now() - timedelta(minutes=10)
        alert = Alert.objects.create(
            title='K8S的APISERVER请求延迟过高',
            source='platform',
            message='latency high',
            environment='xing-prod',
            starts_at=starts_at,
            knowledge_environment=self.context,
        )
        run_query.side_effect = [
            {'total': 2, 'logs': [
                {'timestamp': starts_at.isoformat(), 'level': 'error', 'source': 'kube-apiserver', 'service': 'kube-apiserver', 'message': 'etcd request timeout'},
                {'timestamp': starts_at.isoformat(), 'level': 'info', 'source': 'kube-apiserver', 'service': 'kube-apiserver', 'message': 'request completed'},
            ]},
            {'total': 1, 'logs': [
                {'timestamp': (starts_at - timedelta(minutes=10)).isoformat(), 'level': 'info', 'source': 'kube-apiserver', 'service': 'kube-apiserver', 'message': 'healthy'},
            ]},
        ]

        result = _log_evidence(self.context, alert=alert, window_minutes=30, profile='alert_analysis')

        primary_payload = run_query.call_args_list[0].args[2]
        baseline_payload = run_query.call_args_list[1].args[2]
        self.assertEqual(primary_payload['start_ms'], int(starts_at.timestamp() * 1000))
        self.assertEqual(primary_payload['end_ms'], int((starts_at + timedelta(minutes=5)).timestamp() * 1000))
        self.assertEqual(baseline_payload['start_ms'], int((starts_at - timedelta(minutes=30)).timestamp() * 1000))
        self.assertEqual(baseline_payload['end_ms'], int(starts_at.timestamp() * 1000))
        self.assertEqual(result['dimensions']['service'], 'kube-apiserver')
        self.assertEqual(result['error_count'], 1)
        self.assertEqual(result['baseline']['error_count'], 0)


class AnomalyDetectionTests(TestCase):
    def test_prometheus_series_discards_non_finite_values(self):
        result = {
            'result': [
                {'values': [[1, '1.5'], [2, 'NaN'], [3, '+Inf'], [4, '-Inf'], [5, '2.5']]},
            ],
        }

        self.assertEqual(_series_values(result), [1.5, 2.5])

    def test_ensemble_detects_large_spike(self):
        values = [10 + (index % 3) * 0.1 for index in range(40)] + [100]
        result = detect_anomaly(values)
        self.assertTrue(result['is_anomaly'])
        self.assertGreaterEqual(result['vote_count'], 2)

    def test_short_series_abstains(self):
        result = detect_anomaly([1, 2])
        self.assertFalse(result['is_anomaly'])
        self.assertEqual(result['eligible_count'], 0)
