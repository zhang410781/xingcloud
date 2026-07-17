from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from aiops.models import AIOpsKnowledgeEnvironment
from ops.alert_analysis import (
    collect_alert_evidence,
    enqueue_alert_analysis,
    execute_alert_analysis,
    run_due_alert_analyses,
)
from ops.alerting import _default_body
from ops.models import Alert, AlertAnalysis, AlertNotificationPolicy, LogDataSource, MetricDataSource


class AlertAnalysisTests(TestCase):
    def setUp(self):
        self.metric = MetricDataSource.objects.create(
            name='analysis-prometheus',
            provider='prometheus',
            environment='prod',
            cluster_name='cluster-a',
            config={'endpoint': 'http://prometheus.example'},
        )
        self.logs = LogDataSource.objects.create(
            name='analysis-elasticsearch',
            provider='elk',
            config={
                'endpoint': 'http://elasticsearch.example',
                'index_pattern': 'logs-*',
                'field_map': {'namespace': 'kubernetes.namespace_name', 'pod': 'kubernetes.pod_name'},
            },
        )
        self.environment = AIOpsKnowledgeEnvironment.objects.create(
            name='production',
            code='prod',
            business_line='xing-cloud',
            metric_datasource=self.metric,
            log_datasource=self.logs,
            is_enabled=True,
        )
        self.alert = Alert.objects.create(
            title='Pod 重启频繁',
            level='warning',
            status=Alert.STATUS_ACTIVE,
            source='Xing-Cloud 告警规则',
            source_type=Alert.SOURCE_PLATFORM,
            message='Pod 15 分钟内重启超过阈值',
            environment='prod',
            knowledge_environment=self.environment,
            cluster='cluster-a',
            namespace='ops',
            service='kubernetes',
            resource_type='pod',
            resource='ops-agent-abc',
            labels={
                'metric_datasource_id': str(self.metric.id),
                'pod': 'ops-agent-abc',
                'namespace': 'ops',
            },
            raw_payload={
                'event': {'value': 4.1286},
                'rule': {
                    'metric_datasource_id': self.metric.id,
                    'query_config': {'promql': 'increase(restarts[15m])', 'window': '15m'},
                    'condition': {'operator': 'gt', 'warning': 3},
                },
            },
        )

    @patch('ops.observability_evidence._run_query')
    def test_collects_elasticsearch_logs_with_environment_dimensions_and_window(self, run_query):
        run_query.return_value = {
            'total': 2,
            'logs': [
                {
                    'timestamp': '2026-07-16T01:37:00+08:00',
                    'level': 'error',
                    'source': 'ops-agent',
                    'namespace': 'ops',
                    'pod': 'ops-agent-abc',
                    'message': 'CrashLoopBackOff token=secret-value phone=13800138000',
                },
                {
                    'timestamp': '2026-07-16T01:36:00+08:00',
                    'level': 'error',
                    'source': 'ops-agent',
                    'namespace': 'ops',
                    'pod': 'ops-agent-abc',
                    'message': 'CrashLoopBackOff token=another-value phone=13800138000',
                },
            ],
        }

        evidence = collect_alert_evidence(self.alert)

        self.assertEqual(evidence['knowledge_environment']['id'], self.environment.id)
        self.assertEqual(evidence['logs']['datasource']['id'], self.logs.id)
        self.assertEqual(evidence['logs']['dimensions']['pod'], 'ops-agent-abc')
        self.assertEqual(evidence['logs']['field_map']['pod'], 'kubernetes.pod_name')
        payload = run_query.call_args.args[2]
        self.assertIn('ops-agent-abc', payload['query'])
        self.assertIn('ops', payload['query'])
        self.assertGreaterEqual(payload['end_ms'] - payload['start_ms'], 15 * 60 * 1000)
        sample = evidence['logs']['samples'][0]['message']
        self.assertNotIn('secret-value', sample)
        self.assertNotIn('13800138000', sample)

    def test_mismatched_alert_environment_is_diagnostic_and_never_falls_back(self):
        self.alert.environment = 'other-prod'
        self.alert.save(update_fields=['environment'])

        with patch('ops.observability_evidence._run_query') as run_query:
            evidence = collect_alert_evidence(self.alert)

        self.assertEqual(evidence['logs']['status'], 'configuration_error')
        self.assertIn('不一致', evidence['logs']['error'])
        run_query.assert_not_called()

    @patch('ops.alerting.dispatch_alert_notifications')
    @patch('ops.alert_analysis._llm_synthesis')
    @patch('ops.observability_evidence._run_query')
    def test_model_failure_keeps_evidence_and_marks_partial(self, run_query, llm_synthesis, dispatch):
        run_query.return_value = {
            'total': 1,
            'logs': [{'level': 'error', 'message': 'OOMKilled', 'pod': 'ops-agent-abc', 'namespace': 'ops'}],
        }
        llm_synthesis.side_effect = RuntimeError('provider unavailable')
        analysis = AlertAnalysis.objects.create(alert=self.alert, trigger=AlertAnalysis.TRIGGER_MANUAL)

        execute_alert_analysis(analysis)

        analysis.refresh_from_db()
        self.alert.refresh_from_db()
        self.assertEqual(analysis.status, AlertAnalysis.STATUS_PARTIAL)
        self.assertEqual(analysis.evidence['logs']['sample_count'], 1)
        self.assertEqual(analysis.candidates[0]['code'], 'oom_killed')
        self.assertEqual(self.alert.raw_payload['ai_analysis']['status'], AlertAnalysis.STATUS_PARTIAL)
        dispatch.assert_called_once_with(analysis.alert, action='analysis')

    @patch('ops.alert_analysis.execute_alert_analysis')
    def test_scheduler_retries_processing_failure_twice(self, execute):
        execute.side_effect = RuntimeError('unexpected worker failure')
        analysis, _ = enqueue_alert_analysis(self.alert, trigger=AlertAnalysis.TRIGGER_MANUAL, force=True)

        first = run_due_alert_analyses(limit=1)
        analysis.refresh_from_db()

        self.assertEqual(first['retried'], 1)
        self.assertEqual(analysis.status, AlertAnalysis.STATUS_PENDING)
        self.assertEqual(analysis.retry_count, 1)

    def test_notification_policy_exposes_analysis_switch_default(self):
        policy = AlertNotificationPolicy.objects.create(name='analysis policy')
        self.assertTrue(policy.notify_on_analysis)

    def test_default_notification_formats_value_threshold_and_hides_promql(self):
        body = _default_body(self.alert, action='fire')

        self.assertIn('4.13次 / 15分钟', body)
        self.assertIn('> 3次', body)
        self.assertIn('Pod 15 分钟内重启超过阈值', body)
        self.assertNotIn('increase(restarts[15m])', body)


class AlertAnalysisApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('analysis-admin', 'analysis@example.com', 'Admin@123456')
        self.client.force_authenticate(self.user)
        self.alert = Alert.objects.create(
            title='API alert',
            level='critical',
            status=Alert.STATUS_ACTIVE,
            source='Xing-Cloud 告警规则',
            source_type=Alert.SOURCE_PLATFORM,
            message='api test',
        )

    def test_manual_analysis_and_history_api(self):
        analyze_response = self.client.post(reverse('alert-analyze', args=[self.alert.id]), {}, format='json')
        self.assertEqual(analyze_response.status_code, 201)
        self.assertEqual(analyze_response.data['analysis']['status'], AlertAnalysis.STATUS_PENDING)

        history_response = self.client.get(reverse('alert-analysis', args=[self.alert.id]))
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(len(history_response.data['results']), 1)
        self.assertEqual(history_response.data['latest']['status'], AlertAnalysis.STATUS_PENDING)
