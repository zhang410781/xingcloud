from unittest.mock import patch
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from aiops.models import AIOpsKnowledgeEnvironment
from ops.alert_analysis import (
    _analysis_depth,
    collect_alert_evidence,
    enqueue_alert_analysis,
    enqueue_for_rule_alert,
    enqueue_missing_active_analyses,
    execute_alert_analysis,
    run_due_alert_analyses,
)
from ops.alerting import _default_body, _policy_inhibits_alert, dispatch_alert_notifications, upsert_alert
from ops.alert_rules import trigger_alert_rule
from ops.alert_rule_presets import ensure_builtin_alert_rule_templates
from ops.observability_evidence import _targeted_alert_metrics
from ops.models import (
    Alert,
    AlertAnalysis,
    AlertNotificationChannel,
    AlertNotificationPolicy,
    AlertRule,
    LogDataSource,
    MetricDataSource,
)


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
            starts_at=timezone.now() - timedelta(minutes=2),
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
                    'service': 'kubernetes',
                    'namespace': 'ops',
                    'pod': 'ops-agent-abc',
                    'message': 'CrashLoopBackOff token=secret-value phone=13800138000',
                },
                {
                    'timestamp': '2026-07-16T01:36:00+08:00',
                    'level': 'error',
                    'source': 'ops-agent',
                    'service': 'kubernetes',
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
        payload = run_query.call_args_list[0].args[2]
        self.assertIn('ops-agent-abc', payload['query'])
        self.assertIn('ops', payload['query'])
        self.assertGreaterEqual(payload['end_ms'] - payload['start_ms'], 60 * 1000)
        self.assertLess(payload['end_ms'] - payload['start_ms'], 5 * 60 * 1000)
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
            'logs': [{'level': 'error', 'message': 'OOMKilled', 'pod': 'ops-agent-abc', 'namespace': 'ops', 'service': 'kubernetes'}],
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
        dispatch.assert_called_once_with(analysis.alert, action='analysis', force=True)

    @patch('ops.alerting.dispatch_alert_notifications')
    @patch('ops.alert_analysis._llm_synthesis')
    @patch('ops.observability_evidence._run_query')
    def test_completed_analysis_dispatches_after_alert_recovers(self, run_query, llm_synthesis, dispatch):
        run_query.return_value = {'total': 0, 'logs': []}
        llm_synthesis.side_effect = RuntimeError('provider unavailable')
        self.alert.status = Alert.STATUS_RESOLVED
        self.alert.save(update_fields=['status'])
        analysis = AlertAnalysis.objects.create(alert=self.alert, trigger=AlertAnalysis.TRIGGER_MANUAL)

        execute_alert_analysis(analysis)

        dispatch.assert_called_once_with(analysis.alert, action='analysis', force=True)

    @patch('ops.alerting.send_alert_notification', return_value='sent')
    def test_notification_dispatch_allows_resolved_analysis(self, send_notification):
        rule = AlertRule.objects.create(
            name='analysis rule', source_type='prometheus', category='k8s',
            metric_datasource=self.metric, is_template=False, notify_enabled=True,
        )
        channel = AlertNotificationChannel.objects.create(
            name='analysis feishu', channel_type='feishu',
            config={'webhook_url': 'https://open.feishu.cn/test', 'secret': 'secret'},
        )
        policy = AlertNotificationPolicy.objects.create(
            name='analysis policy', metric_datasource=self.metric, notify_on_analysis=True,
        )
        policy.channels.add(channel)
        self.alert.status = Alert.STATUS_RESOLVED
        self.alert.labels = {**self.alert.labels, 'alert_rule_id': str(rule.id)}
        self.alert.save(update_fields=['status', 'labels'])

        logs = dispatch_alert_notifications(self.alert, action='analysis')

        self.assertEqual(logs, ['sent'])
        send_notification.assert_called_once()

    @patch('ops.alert_analysis.execute_alert_analysis')
    def test_scheduler_retries_processing_failure_twice(self, execute):
        execute.side_effect = RuntimeError('unexpected worker failure')
        analysis, _ = enqueue_alert_analysis(self.alert, trigger=AlertAnalysis.TRIGGER_MANUAL, force=True)

        first = run_due_alert_analyses(limit=1)
        analysis.refresh_from_db()

        self.assertEqual(first['retried'], 1)
        self.assertEqual(analysis.status, AlertAnalysis.STATUS_PENDING)
        self.assertEqual(analysis.retry_count, 1)

    def test_automatic_analysis_is_immediately_due_and_deduplicates(self):
        self.alert.starts_at = timezone.now()
        self.alert.save(update_fields=['starts_at'])

        analysis, created = enqueue_alert_analysis(self.alert, requested_by='alert-engine')
        duplicate, duplicate_created = enqueue_alert_analysis(self.alert, requested_by='alert-engine')

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(duplicate.id, analysis.id)
        self.assertLessEqual(analysis.next_retry_at, timezone.now())
        self.assertEqual(analysis.evidence['stage_status']['queued_after_first_notification'], 'waiting')

    def test_existing_active_alert_without_analysis_is_backfilled_once(self):
        rule = AlertRule.objects.create(
            name='existing active rule', source_type='prometheus', category='k8s',
            metric_datasource=self.metric, is_template=False, auto_analyze=True,
        )

        analysis, created = enqueue_for_rule_alert(self.alert, rule, created=False)
        duplicate, duplicate_created = enqueue_for_rule_alert(self.alert, rule, created=False)

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(duplicate.id, analysis.id)
        self.assertEqual(self.alert.analyses.count(), 1)

    def test_worker_repairs_active_alert_with_pending_marker_only(self):
        rule = AlertRule.objects.create(
            name='repair rule', source_type='prometheus', category='k8s',
            metric_datasource=self.metric, is_template=False, auto_analyze=True,
        )
        self.alert.raw_payload = {
            **self.alert.raw_payload,
            'rule': {'id': rule.id, 'metric_datasource_id': self.metric.id},
            'ai_analysis': {'status': 'pending'},
        }
        self.alert.save(update_fields=['raw_payload'])

        first = enqueue_missing_active_analyses()
        second = enqueue_missing_active_analyses()

        self.assertEqual(first['queued'], 1)
        self.assertEqual(second['queued'], 0)
        self.assertEqual(self.alert.analyses.count(), 1)

    def test_legacy_k8s_templates_and_instances_are_deleted(self):
        legacy = AlertRule.objects.create(
            name='legacy pod restart', code='k8s-abnormal-pods', source='builtin',
            source_type='prometheus', category='k8s', is_template=True,
        )
        instance = AlertRule.objects.create(
            name='legacy pod restart instance', source='k8s-abnormal-pods',
            source_type='prometheus', category='k8s', is_template=False,
            template=legacy, metric_datasource=self.metric,
        )

        ensure_builtin_alert_rule_templates()

        self.assertFalse(AlertRule.objects.filter(pk=legacy.pk).exists())
        self.assertFalse(AlertRule.objects.filter(pk=instance.pk).exists())

    def test_resolve_does_not_cancel_queued_analysis(self):
        self.alert.fingerprint = 'resolve-keeps-analysis'
        self.alert.save(update_fields=['fingerprint'])
        analysis, _ = enqueue_alert_analysis(self.alert, requested_by='alert-engine')
        upsert_alert({
            'title': self.alert.title,
            'level': self.alert.level,
            'status': Alert.STATUS_RESOLVED,
            'source': self.alert.source,
            'source_type': self.alert.source_type,
            'fingerprint': self.alert.fingerprint,
            'message': self.alert.message,
            'environment': self.alert.environment,
            'labels': self.alert.labels,
            'raw_payload': self.alert.raw_payload,
            'ends_at': timezone.now(),
        })

        analysis.refresh_from_db()
        self.assertEqual(analysis.status, AlertAnalysis.STATUS_PENDING)

    @patch('ops.alert_analysis.enqueue_for_rule_alert')
    @patch('ops.alert_rules.dispatch_alert_notifications')
    def test_direct_rule_trigger_notifies_before_enqueue(self, dispatch, enqueue):
        order = []
        dispatch.side_effect = lambda *args, **kwargs: order.append('notify') or []
        enqueue.side_effect = lambda *args, **kwargs: order.append('enqueue') or (None, False)
        rule = AlertRule.objects.create(
            name='ordered rule', code='ordered-rule', source_type='prometheus', category='k8s',
            metric_datasource=self.metric, is_template=False, is_enabled=True,
            notify_enabled=True, auto_analyze=True,
        )

        trigger_alert_rule(rule, payload={'title': 'ordered alert', 'labels': {'pod': 'api-0'}})

        self.assertEqual(order, ['notify', 'enqueue'])

    @patch('ops.alert_analysis.execute_alert_analysis')
    def test_recovered_alert_still_executes_queued_analysis(self, execute):
        analysis, _ = enqueue_alert_analysis(self.alert, requested_by='alert-engine')
        analysis.next_retry_at = timezone.now() - timedelta(seconds=1)
        analysis.save(update_fields=['next_retry_at'])
        self.alert.status = Alert.STATUS_RESOLVED
        self.alert.save(update_fields=['status'])

        outcome = run_due_alert_analyses(limit=1)
        analysis.refresh_from_db()

        self.assertEqual(outcome['cancelled'], 0)
        execute.assert_called_once()

    def test_non_pod_alert_can_enqueue_automatic_analysis(self):
        self.alert.resource_type = 'database'
        self.alert.resource = 'mysql-primary'
        self.alert.namespace = ''
        self.alert.labels = {'metric_datasource_id': str(self.metric.id)}
        self.alert.save(update_fields=['resource_type', 'resource', 'namespace', 'labels'])

        analysis, created = enqueue_alert_analysis(self.alert, requested_by='alert-engine')

        self.assertIsNotNone(analysis)
        self.assertTrue(created)

    def test_related_alert_burst_uses_full_analysis(self):
        for index in range(2):
            Alert.objects.create(
                title=f'related-{index}', level='warning', status=Alert.STATUS_ACTIVE,
                source='test', source_type=Alert.SOURCE_PLATFORM,
                environment='prod', namespace='ops', starts_at=timezone.now(),
            )

        self.assertEqual(_analysis_depth(self.alert), 'full')

    def test_agent4_policy_inhibits_lower_level_same_object(self):
        self.alert.labels = {**self.alert.labels, 'alert_rule_code': 'pod-restarts'}
        self.alert.save(update_fields=['labels'])
        Alert.objects.create(
            title='critical source', level='critical', status=Alert.STATUS_ACTIVE,
            source='test', source_type=Alert.SOURCE_PLATFORM,
            environment='prod', namespace='ops',
            labels={'alert_rule_code': 'pod-restarts'}, starts_at=timezone.now(),
        )
        policy = AlertNotificationPolicy.objects.create(
            name='agent4', inhibition_matchers=[{
                'source_level': 'critical',
                'target_levels': ['warning', 'info'],
                'equal': ['environment', 'namespace', 'alert_rule_code'],
            }],
        )

        self.assertTrue(_policy_inhibits_alert(policy, self.alert))

    @patch('ops.observability_views.execute_promql_query')
    def test_targeted_metrics_use_exact_pod_dimensions_and_alert_window(self, query):
        query.return_value = {'result': [], 'series_count': 0}
        self.alert.labels = {**self.alert.labels, 'container': 'api', 'node': 'worker-1'}
        self.alert.save(update_fields=['labels'])
        start_at = self.alert.starts_at - timedelta(minutes=10)
        end_at = timezone.now()

        result = _targeted_alert_metrics(self.environment, self.alert, start_at, end_at)

        self.assertEqual(result['target']['namespace'], 'ops')
        self.assertEqual(result['target']['pod'], 'ops-agent-abc')
        self.assertEqual(result['target']['container'], 'api')
        queries = [call.args[0] for call in query.call_args_list]
        self.assertTrue(any('increase(kube_pod_container_status_restarts_total' in item for item in queries))
        self.assertTrue(all('namespace="ops"' in item and 'pod="ops-agent-abc"' in item for item in queries[:6]))
        first_kwargs = query.call_args_list[0].kwargs
        self.assertEqual(first_kwargs['start_time'], start_at)
        self.assertEqual(first_kwargs['end_time'], end_at)

    @patch('ops.observability_evidence._run_query')
    def test_delayed_analysis_caps_primary_log_window_at_five_minutes(self, run_query):
        run_query.return_value = {'total': 0, 'logs': []}
        self.alert.starts_at = timezone.now() - timedelta(minutes=30)
        self.alert.save(update_fields=['starts_at'])

        collect_alert_evidence(self.alert)

        primary = run_query.call_args_list[0].args[2]
        self.assertLessEqual(primary['end_ms'] - primary['start_ms'], 5 * 60 * 1000)

    def test_notification_policy_exposes_analysis_switch_default(self):
        policy = AlertNotificationPolicy.objects.create(name='analysis policy')
        self.assertTrue(policy.notify_on_analysis)

    def test_default_notification_formats_value_threshold_and_hides_promql(self):
        body = _default_body(self.alert, action='fire')

        self.assertIn('4.13次 / 15分钟', body)
        self.assertIn('> 3次', body)
        self.assertIn('Pod 15 分钟内重启超过阈值', body)
        self.assertNotIn('increase(restarts[15m])', body)

    def test_analysis_notification_includes_current_alert_status(self):
        self.alert.status = Alert.STATUS_RESOLVED

        body = _default_body(self.alert, action='analysis')

        self.assertIn('研判状态：** 研判期间已恢复', body)


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
