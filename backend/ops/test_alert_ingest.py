from unittest.mock import patch
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from ops.alert_analysis import execute_lightweight_alert_analysis
from ops.alert_ingest import (
    detect_source,
    normalize_alertmanager,
    normalize_zabbix,
    run_due_external_alert_escalations,
)
from ops.alerting import dispatch_alert_notifications
from ops.models import (
    Alert,
    AlertAnalysis,
    AlertNotificationChannel,
    AlertNotificationPolicy,
)


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
        self.assertEqual(Alert.objects.count(), 0)

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


class ExternalAlertNotificationPolicyTests(TestCase):
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
