from unittest.mock import patch
from datetime import timedelta

from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from ops.alert_analysis import execute_lightweight_alert_analysis, serialize_analysis
from ops.alert_ingest import (
    detect_source,
    normalize_alertmanager,
    normalize_zabbix,
    run_due_external_alert_escalations,
)
from ops.alerting import alert_dimension_value, dispatch_alert_notifications, resolve_notification_policies
from ops.models import (
    Alert,
    AlertAnalysis,
    AlertNotificationChannel,
    AlertNotificationPolicy,
    ExternalAlertIngressLog,
    ExternalAlertSource,
    MetricDataSource,
)
from ops.serializers import AlertNotificationPolicySerializer
from aiops.models import AIOpsKnowledgeEnvironment


@override_settings(
    WEBHOOK_TOKENS={'default': 'test-token'},
    ALERT_INGEST_RATE_LIMIT=100,
    ALERT_INGEST_MAX_BODY_BYTES=1_048_576,
)
class ExternalAlertIngestApiTests(TestCase):
    url = '/api/ops/alerts/ingest/'

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.credentials(HTTP_X_WEBHOOK_TOKEN='test-token')

    def zabbix_payload(self, **overrides):
        payload = {
            'event_id': '12345',
            'trigger_id': '67890',
            'trigger_name': 'CPU high on web-server-01',
            'severity': 'high',
            'host_name': 'web-server-01',
            'subject': 'CPU usage > 90%',
            'message': 'CPU usage is 95%.',
            'script_output': 'java process uses 200% CPU',
            'timestamp': '2026-07-24 10:00:00',
            'environment': 'prod',
        }
        payload.update(overrides)
        return payload

    def test_rejects_missing_or_invalid_token(self):
        client = APIClient()
        response = client.post(self.url, self.zabbix_payload(), format='json')
        self.assertEqual(response.status_code, 401)
        client.credentials(HTTP_X_WEBHOOK_TOKEN='wrong-token')
        response = client.post(self.url, self.zabbix_payload(), format='json')
        self.assertEqual(response.status_code, 401)
        client.credentials(HTTP_AUTHORIZATION='Bearer wrong-token')
        response = client.post(self.url, self.zabbix_payload(), format='json')
        self.assertEqual(response.status_code, 401)
        client.credentials(HTTP_AUTHORIZATION='Basic dGVzdC10b2tlbg==')
        response = client.post(self.url, self.zabbix_payload(), format='json')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(Alert.objects.count(), 0)

    def test_accepts_authorization_bearer_token(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer test-token')
        payload = {
            'status': 'firing',
            'receiver': 'xing-cloud',
            'alerts': [
                {
                    'status': 'firing',
                    'labels': {
                        'alertname': 'ExternalPodWaiting',
                        'severity': 'critical',
                        'namespace': 'external-system',
                        'pod': 'pod-a',
                    },
                    'annotations': {'summary': 'External Pod Waiting'},
                    'startsAt': '2026-07-24T02:00:00Z',
                    'fingerprint': 'bearer-alertmanager-a',
                },
            ],
        }

        response = client.post(self.url, payload, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['source'], 'alertmanager')
        self.assertEqual(Alert.objects.count(), 1)
        self.assertEqual(Alert.objects.get().source_type, Alert.SOURCE_ALERTMANAGER)

    def test_keeps_x_webhook_token_compatibility(self):
        response = self.client.post(self.url, self.zabbix_payload(), format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Alert.objects.count(), 1)

    def test_ingests_zabbix_and_deduplicates_active_occurrences(self):
        first = self.client.post(self.url, self.zabbix_payload(), format='json')
        second = self.client.post(
            self.url,
            self.zabbix_payload(event_id='12346', message='CPU usage is 97%.'),
            format='json',
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertTrue(first.data['created'])
        self.assertFalse(second.data['created'])
        self.assertEqual(second.data['occurrence_count'], 2)
        self.assertEqual(Alert.objects.count(), 1)
        alert = Alert.objects.get()
        self.assertEqual(alert.source_type, Alert.SOURCE_ZABBIX)
        self.assertIn('script_output', alert.raw_payload)
        self.assertEqual(alert.analyses.count(), 1)
        self.assertEqual(alert.analyses.get().evidence['source_mode'], 'webhook_text_only')
        self.assertEqual(alert.raw_payload['ai_analysis']['id'], alert.analyses.get().id)
        self.assertEqual(alert.raw_payload['fire_notification_batch']['action'], 'fire')

    def test_zabbix_recovery_resolves_existing_alert(self):
        self.client.post(self.url, self.zabbix_payload(), format='json')
        response = self.client.post(
            self.url,
            self.zabbix_payload(event_id='12347', event_status='RESOLVED'),
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        alert = Alert.objects.get()
        self.assertEqual(alert.status, Alert.STATUS_RESOLVED)
        self.assertIsNotNone(alert.ends_at)
        self.assertEqual(alert.analyses.count(), 1)

    def test_ingests_every_alert_in_alertmanager_batch(self):
        payload = {
            'status': 'firing',
            'receiver': 'xing-cloud',
            'alerts': [
                {
                    'status': 'firing',
                    'labels': {'alertname': 'PodWaiting', 'severity': 'critical', 'namespace': 'kube-ai', 'pod': 'pod-a'},
                    'annotations': {'summary': 'Pod A Waiting', 'description': 'ImagePullBackOff'},
                    'startsAt': '2026-07-24T02:00:00Z',
                    'fingerprint': 'am-a',
                },
                {
                    'status': 'firing',
                    'labels': {'alertname': 'PodWaiting', 'severity': 'warning', 'namespace': 'kube-ai', 'pod': 'pod-b'},
                    'annotations': {'summary': 'Pod B Waiting', 'description': 'ErrImagePull'},
                    'startsAt': '2026-07-24T02:00:01Z',
                    'fingerprint': 'am-b',
                },
            ],
        }

        response = self.client.post(self.url, payload, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(Alert.objects.filter(source_type=Alert.SOURCE_ALERTMANAGER).count(), 2)
        self.assertEqual(AlertAnalysis.objects.count(), 2)

    def test_unknown_payload_returns_diagnostic_400(self):
        response = self.client.post(self.url, {'message': 'unknown'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('无法识别', response.data['detail'])

    @override_settings(ALERT_INGEST_RATE_LIMIT=1)
    def test_rate_limit_is_enforced_per_token(self):
        first = self.client.post(self.url, self.zabbix_payload(), format='json')
        second = self.client.post(self.url, self.zabbix_payload(trigger_id='other'), format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)


class ManagedExternalAlertSourceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_superuser(
            username='external-alert-admin',
            email='external@example.com',
            password='test-password',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.context = AIOpsKnowledgeEnvironment.objects.create(name='外部生产环境', code='external-prod')

    def alertmanager_payload(self, fingerprint='same-external-fingerprint', namespace='external-ns'):
        return {
            'status': 'firing',
            'receiver': 'xing-cloud',
            'alerts': [{
                'status': 'firing',
                'labels': {
                    'alertname': 'ExternalPodWaiting',
                    'severity': 'critical',
                    'namespace': namespace,
                    'pod': 'pod-a',
                },
                'annotations': {'summary': 'External Pod Waiting'},
                'startsAt': '2026-07-24T02:00:00Z',
                'fingerprint': fingerprint,
            }],
        }

    def create_source(self, code, **overrides):
        source = ExternalAlertSource.objects.create(
            name=overrides.pop('name', code),
            code=code,
            provider=overrides.pop('provider', ExternalAlertSource.PROVIDER_ALERTMANAGER),
            analyze_enabled=overrides.pop('analyze_enabled', False),
            **overrides,
        )
        return source, source.issue_token()

    def ingest(self, source, token, payload=None):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        return client.post(
            f'/api/ops/alert-ingress/{source.public_id}/',
            payload or self.alertmanager_payload(),
            format='json',
        )

    def test_create_source_returns_token_once(self):
        response = self.client.post('/api/external-alert-sources/', {
            'name': '生产 Alertmanager',
            'code': 'production-alertmanager',
            'provider': 'alertmanager',
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['token'])
        self.assertIn(str(response.data['public_id']), response.data['endpoint'])
        detail = self.client.get(f"/api/external-alert-sources/{response.data['id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn('token', detail.data)
        self.assertTrue(detail.data['token_configured'])
        self.assertNotIn('default_knowledge_environment', detail.data)
        self.assertNotIn('mapping_rules', detail.data)

    def test_source_token_ingests_without_business_context(self):
        source, token = self.create_source(
            'production-alertmanager',
            default_knowledge_environment=self.context,
        )

        response = self.ingest(source, token)

        self.assertEqual(response.status_code, 201)
        alert = Alert.objects.get()
        self.assertEqual(alert.ingress_source, source)
        self.assertIsNone(alert.knowledge_environment)
        self.assertEqual(alert.binding_status, 'not_applicable')
        self.assertEqual(alert.raw_payload['ingest']['binding_reason'], 'not_required')
        self.assertEqual(alert.labels['namespace'], 'external-ns')
        detail = self.client.get(f'/api/alerts/{alert.id}/')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data['environment_display'], source.name)
        self.assertEqual(detail.data['scope_display'], '外部接入')
        self.assertEqual(detail.data['source_display'], source.name)
        source.refresh_from_db()
        self.assertEqual(source.accepted_requests, 1)
        self.assertEqual(source.received_alerts, 1)
        self.assertEqual(source.ingress_logs.get().status, ExternalAlertIngressLog.STATUS_ACCEPTED)

    def test_same_external_fingerprint_is_isolated_by_source(self):
        first_source, first_token = self.create_source('first-alertmanager')
        second_source, second_token = self.create_source('second-alertmanager')

        self.assertEqual(self.ingest(first_source, first_token).status_code, 201)
        self.assertEqual(self.ingest(second_source, second_token).status_code, 201)

        self.assertEqual(Alert.objects.count(), 2)
        fingerprints = set(Alert.objects.values_list('fingerprint', flat=True))
        self.assertEqual(len(fingerprints), 2)
        self.assertEqual(set(Alert.objects.values_list('ingress_source_id', flat=True)), {first_source.id, second_source.id})

    def test_legacy_context_mapping_is_ignored(self):
        mapped_context = AIOpsKnowledgeEnvironment.objects.create(name='映射环境', code='mapped-context')
        source, token = self.create_source(
            'mapping-alertmanager',
            default_knowledge_environment=self.context,
            mapping_rules=[{
                'priority': 10,
                'matchers': [{'key': 'namespace', 'operator': '==', 'value': 'mapped-ns'}],
                'knowledge_environment_id': mapped_context.id,
            }],
        )

        response = self.ingest(source, token, self.alertmanager_payload(namespace='mapped-ns'))

        self.assertEqual(response.status_code, 201)
        alert = Alert.objects.get()
        self.assertIsNone(alert.knowledge_environment)
        self.assertEqual(alert.binding_status, 'not_applicable')

    def test_external_alert_is_visible_in_external_scope(self):
        source, token = self.create_source('external-alertmanager')

        response = self.ingest(source, token)

        self.assertEqual(response.status_code, 201)
        alert = Alert.objects.get()
        self.assertIsNone(alert.knowledge_environment)
        self.assertEqual(alert.binding_status, 'not_applicable')
        queryset = self.client.get('/api/alerts/?alert_scope=external')
        self.assertEqual(queryset.status_code, 200)
        self.assertEqual(queryset.data['count'], 1)

    def test_payload_preview_has_no_business_context_assignment(self):
        source, _token = self.create_source(
            'preview-alertmanager',
            default_knowledge_environment=self.context,
        )

        response = self.client.post(
            f'/api/external-alert-sources/{source.id}/preview-payload/',
            {'payload': self.alertmanager_payload()},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        result = response.data['results'][0]
        self.assertNotIn('knowledge_environment', result)
        self.assertNotIn('binding_status', result)
        self.assertEqual(result['source'], source.code)

    def test_provider_mismatch_is_rejected_and_logged(self):
        source, token = self.create_source('zabbix-source', provider=ExternalAlertSource.PROVIDER_ZABBIX)

        response = self.ingest(source, token)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Alert.objects.count(), 0)
        source.refresh_from_db()
        self.assertEqual(source.rejected_requests, 1)
        self.assertEqual(source.ingress_logs.get().status, ExternalAlertIngressLog.STATUS_ERROR)

    @override_settings(ALERT_INGRESS_REJECTION_LOG_RATE_LIMIT=1)
    def test_invalid_token_rejections_are_log_rate_limited_by_source_and_address(self):
        source, _token = self.create_source('protected-alertmanager')
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer invalid-token')
        url = f'/api/ops/alert-ingress/{source.public_id}/'

        first = client.post(url, self.alertmanager_payload(), format='json', REMOTE_ADDR='192.0.2.10')
        second = client.post(url, self.alertmanager_payload(), format='json', REMOTE_ADDR='192.0.2.10')

        self.assertEqual(first.status_code, 401)
        self.assertEqual(second.status_code, 401)
        source.refresh_from_db()
        self.assertEqual(source.rejected_requests, 1)
        self.assertEqual(source.ingress_logs.count(), 1)

    def test_invalid_remote_address_is_not_persisted(self):
        source, _token = self.create_source('invalid-address-alertmanager')
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer invalid-token')

        response = client.post(
            f'/api/ops/alert-ingress/{source.public_id}/',
            self.alertmanager_payload(),
            format='json',
            REMOTE_ADDR='not-an-ip-address',
        )

        self.assertEqual(response.status_code, 401)
        self.assertIsNone(source.ingress_logs.get().remote_addr)

    def test_source_identity_fields_cannot_be_changed(self):
        source, _token = self.create_source('immutable-alertmanager')

        response = self.client.patch(
            f'/api/external-alert-sources/{source.id}/',
            {'code': 'changed-code', 'provider': 'zabbix'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('code', response.data)
        self.assertIn('provider', response.data)


class ExternalAlertNormalizationTests(TestCase):
    def test_detects_supported_sources(self):
        self.assertEqual(detect_source({'event_id': '1'}), 'zabbix')
        self.assertEqual(detect_source({'status': 'firing', 'alerts': []}), 'alertmanager')
        self.assertEqual(detect_source({}), 'unknown')

    def test_normalizes_zabbix_severity_and_recovery(self):
        normalized = normalize_zabbix({
            'event_id': '1',
            'trigger_id': '2',
            'host_name': 'node-1',
            'severity': 'Disaster',
            'event_status': 'OK',
            'timestamp': '2026.07.24 10:00:00',
        })
        self.assertEqual(normalized['level'], 'critical')
        self.assertEqual(normalized['status'], Alert.STATUS_RESOLVED)
        self.assertEqual(normalized['fingerprint'], 'zabbix:2:node-1')
        self.assertIsNotNone(normalized['ends_at'])

    def test_normalizes_alertmanager_resolved_alert(self):
        normalized = normalize_alertmanager({
            'status': 'resolved',
            'alerts': [{
                'status': 'resolved',
                'labels': {'alertname': 'NodeDown', 'severity': 'warning', 'instance': 'node-1'},
                'annotations': {'summary': 'Node down'},
                'startsAt': '2026-07-24T01:00:00Z',
                'endsAt': '2026-07-24T01:05:00Z',
                'fingerprint': 'node-down',
            }],
        })
        self.assertEqual(normalized['status'], Alert.STATUS_RESOLVED)
        self.assertEqual(normalized['resource'], 'node-1')
        self.assertEqual(normalized['fingerprint'], 'alertmanager:node-down')
        self.assertIsNotNone(normalized['ends_at'])


class LightweightAlertAnalysisTests(TestCase):
    def setUp(self):
        self.alert = Alert.objects.create(
            title='External CPU alert',
            level='critical',
            status=Alert.STATUS_ACTIVE,
            source='zabbix',
            source_type=Alert.SOURCE_ZABBIX,
            fingerprint='zabbix:test',
            message='CPU usage is 95%',
            resource_type='host',
            resource='node-1',
            raw_payload={'script_output': 'top shows java at 200% CPU'},
            starts_at=timezone.now(),
        )
        self.analysis = AlertAnalysis.objects.create(
            alert=self.alert,
            status=AlertAnalysis.STATUS_RUNNING,
            started_at=timezone.now(),
            evidence={'source_mode': 'webhook_text_only'},
        )

    @patch('ops.alerting.dispatch_alert_notifications', return_value=[])
    @patch('ops.alert_analysis._llm_synthesis')
    def test_lightweight_analysis_caps_confidence_and_skips_collectors(self, synthesize, _dispatch):
        synthesize.return_value = ('provider', 'model', {
            'summary': 'CPU 高使用率文本研判',
            'root_cause': '告警文本指出 java 进程 CPU 使用率较高',
            'confidence': 0.95,
            'candidates': [],
            'suggestions': ['核对主机实时进程指标'],
            'evidence_notes': [],
        })

        execute_lightweight_alert_analysis(self.analysis)

        self.analysis.refresh_from_db()
        self.assertEqual(self.analysis.status, AlertAnalysis.STATUS_COMPLETED)
        self.assertEqual(self.analysis.confidence, 0.5)
        self.assertEqual(self.analysis.evidence['source_mode'], 'webhook_text_only')
        self.assertEqual(self.analysis.evidence['stage_status']['collecting_metrics'], 'skipped')
        self.assertIn('script_output', self.analysis.evidence['external_payload'])

    @patch('ops.alerting.dispatch_alert_notifications', return_value=[])
    @patch('ops.alert_analysis._llm_synthesis', side_effect=RuntimeError('no model'))
    def test_lightweight_analysis_preserves_partial_result_without_model(self, _synthesize, _dispatch):
        execute_lightweight_alert_analysis(self.analysis)
        self.analysis.refresh_from_db()
        self.assertEqual(self.analysis.status, AlertAnalysis.STATUS_PARTIAL)
        self.assertEqual(self.analysis.last_error, 'no model')
        self.assertIsNone(self.analysis.confidence)

    @patch('ops.alerting.dispatch_alert_notifications', return_value=[])
    @patch('ops.alert_analysis._llm_synthesis')
    def test_lightweight_analysis_does_not_notify_when_ingress_source_notifications_are_disabled(self, synthesize, dispatch):
        source = ExternalAlertSource.objects.create(
            name='Silent Alertmanager',
            code='silent-alertmanager',
            provider=ExternalAlertSource.PROVIDER_ALERTMANAGER,
            notify_enabled=False,
            analyze_enabled=True,
        )
        self.alert.ingress_source = source
        self.alert.binding_status = 'not_applicable'
        self.alert.save(update_fields=['ingress_source', 'binding_status'])
        synthesize.return_value = ('provider', 'model', {
            'summary': '分析完成',
            'root_cause': '仅基于外部告警文本',
            'confidence': 0.4,
            'candidates': [],
            'suggestions': [],
            'evidence_notes': [],
        })

        execute_lightweight_alert_analysis(self.analysis)

        dispatch.assert_not_called()
        self.analysis.refresh_from_db()
        self.assertEqual(self.analysis.status, AlertAnalysis.STATUS_COMPLETED)
        self.assertEqual(serialize_analysis(self.analysis)['notification_delivery']['status'], 'disabled')


class ExternalAlertNotificationPolicyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser(username='external-policy-admin', password='test-pass')
        self.client.force_authenticate(self.user)

    def test_external_source_code_is_available_as_notification_dimension(self):
        source = ExternalAlertSource.objects.create(
            name='Production Alertmanager',
            code='production-alertmanager',
            provider=ExternalAlertSource.PROVIDER_ALERTMANAGER,
        )
        alert = Alert.objects.create(
            title='External alert',
            level='warning',
            status=Alert.STATUS_ACTIVE,
            source=source.code,
            source_type=Alert.SOURCE_ALERTMANAGER,
            ingress_source=source,
            binding_status='not_applicable',
            fingerprint='alertmanager:dimension',
            starts_at=timezone.now(),
        )

        self.assertEqual(alert_dimension_value(alert, 'ingress_source_code'), source.code)
        self.assertEqual(alert_dimension_value(alert, 'ingress_source_id'), str(source.id))

    def test_external_alert_without_rule_uses_notification_policy(self):
        channel = AlertNotificationChannel.objects.create(
            name='email-test',
            channel_type=AlertNotificationChannel.CHANNEL_EMAIL,
            config={},
        )
        policy = AlertNotificationPolicy.objects.create(
            name='external-alerts',
            matchers=[{'key': 'source_type', 'op': '==', 'value': 'zabbix'}],
            group_wait_seconds=0,
        )
        policy.channels.add(channel)
        alert = Alert.objects.create(
            title='External alert',
            level='warning',
            status=Alert.STATUS_ACTIVE,
            source='zabbix',
            source_type=Alert.SOURCE_ZABBIX,
            fingerprint='zabbix:notify',
            message='external alert',
            starts_at=timezone.now(),
        )

        logs = dispatch_alert_notifications(alert, action='fire', force=True)

        self.assertEqual(len(logs), 1)
        self.assertIsNone(logs[0].rule_id)
        self.assertEqual(logs[0].policy_id, policy.id)

    def test_external_source_policy_only_matches_selected_source(self):
        first_source = ExternalAlertSource.objects.create(
            name='First Alertmanager', code='first-alertmanager', provider=ExternalAlertSource.PROVIDER_ALERTMANAGER,
        )
        second_source = ExternalAlertSource.objects.create(
            name='Second Alertmanager', code='second-alertmanager', provider=ExternalAlertSource.PROVIDER_ALERTMANAGER,
        )
        first_policy = AlertNotificationPolicy.objects.create(
            name='first-source-policy', external_alert_source=first_source, priority=10, continue_matching=True,
        )
        AlertNotificationPolicy.objects.create(
            name='second-source-policy', external_alert_source=second_source, priority=20, continue_matching=True,
        )
        global_policy = AlertNotificationPolicy.objects.create(name='global-policy', priority=100)
        external_alert = Alert(
            title='External alert', level='warning', source=first_source.code,
            source_type=Alert.SOURCE_ALERTMANAGER, ingress_source=first_source,
        )
        platform_alert = Alert(
            title='Platform alert', level='warning', source='platform', source_type=Alert.SOURCE_PLATFORM,
        )

        self.assertEqual(resolve_notification_policies(external_alert), [first_policy, global_policy])
        self.assertEqual(resolve_notification_policies(platform_alert), [global_policy])

    @patch('ops.alerting.compute_group_key', return_value='external-source-group')
    def test_external_notification_group_includes_ingress_source(self, compute_group_key):
        source = ExternalAlertSource.objects.create(
            name='Production Zabbix', code='production-zabbix', provider=ExternalAlertSource.PROVIDER_ZABBIX,
        )
        channel = AlertNotificationChannel.objects.create(
            name='external-email', channel_type=AlertNotificationChannel.CHANNEL_EMAIL, config={},
        )
        policy = AlertNotificationPolicy.objects.create(
            name='zabbix-policy', external_alert_source=source, group_by=['namespace'], group_wait_seconds=0,
        )
        policy.channels.add(channel)
        alert = Alert.objects.create(
            title='External alert', level='warning', status=Alert.STATUS_ACTIVE,
            source=source.code, source_type=Alert.SOURCE_ZABBIX, ingress_source=source,
            namespace='production', fingerprint='zabbix:group-source', starts_at=timezone.now(),
        )

        dispatch_alert_notifications(alert, action='fire', force=True)

        self.assertEqual(compute_group_key.call_args.args[1], ['ingress_source_code', 'namespace'])

    def test_policy_rejects_metric_and_external_sources_together(self):
        metric_source = MetricDataSource.objects.create(name='Prometheus')
        external_source = ExternalAlertSource.objects.create(
            name='Zabbix', code='zabbix-source', provider=ExternalAlertSource.PROVIDER_ZABBIX,
        )

        serializer = AlertNotificationPolicySerializer(data={
            'name': 'invalid-policy',
            'metric_datasource': metric_source.id,
            'external_alert_source': external_source.id,
        })

        self.assertFalse(serializer.is_valid())
        self.assertIn('指标数据源与外部告警接入源不能同时选择', str(serializer.errors))

    def test_policy_preview_uses_external_source_scope(self):
        external_source = ExternalAlertSource.objects.create(
            name='Production Zabbix', code='production-zabbix', provider=ExternalAlertSource.PROVIDER_ZABBIX,
        )
        policy = AlertNotificationPolicy.objects.create(
            name='zabbix-policy', external_alert_source=external_source, priority=10,
        )

        response = self.client.post('/api/alert-notification-policies/preview/', {
            'external_alert_source_id': external_source.id,
            'level': 'warning',
            'labels': {'host': 'server-01'},
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['matched_count'], 1)
        self.assertEqual(response.data['policies'][0]['id'], policy.id)

    def test_scheduler_applies_due_external_escalation(self):
        policy = AlertNotificationPolicy.objects.create(
            name='external-escalation',
            matchers=[{'key': 'source_type', 'op': '==', 'value': 'zabbix'}],
            escalation_steps=[{'after_minutes': 5, 'channel_ids': []}],
        )
        alert = Alert.objects.create(
            title='External alert',
            level='critical',
            status=Alert.STATUS_ACTIVE,
            source='zabbix',
            source_type=Alert.SOURCE_ZABBIX,
            fingerprint='zabbix:escalate',
            message='external alert',
            starts_at=timezone.now() - timedelta(minutes=10),
        )

        result = run_due_external_alert_escalations()

        alert.refresh_from_db()
        self.assertEqual(result['escalated'], 1)
        self.assertEqual(result['ids'], [alert.id])
        self.assertEqual(alert.escalation_level, 1)
        self.assertEqual(alert.actions.filter(action='escalate').count(), 1)
        self.assertTrue(policy.is_enabled)
