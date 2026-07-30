from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .alert_ingest import prepare_external_alerts
from .alert_rule_presets import instantiate_rule_from_template
from .alerting import apply_escalation_policy, dispatch_alert_notifications
from .models import (
    Alert,
    AlertNotificationChannel,
    AlertNotificationLog,
    AlertNotificationPolicy,
    AlertNotificationRoute,
    AlertRecipient,
    AlertRule,
    AlertSource,
    AlertSourceOwner,
    MetricDataSource,
)
from .serializers import AlertSourceSerializer
from .serializers import AlertNotificationPolicySerializer


class UnifiedAlertSourceTests(TestCase):
    def setUp(self):
        self.recipient = AlertRecipient.objects.create(
            name='张三',
            phone='13800000000',
            preferred_channels=['feishu', 'voice'],
            feishu_user_id='ou_test',
        )
        self.metric = MetricDataSource.objects.create(
            name='生产 Prometheus',
            provider='prometheus',
            config={'base_url': 'http://prometheus.example'},
        )

    def source_payload(self, provider, **overrides):
        payload = {
            'name': f'{provider} source',
            'provider': provider,
            'metric_datasource': self.metric.id if provider == 'prometheus' else None,
            'owner_bindings': [{
                'recipient': self.recipient.id,
                'role': 'primary',
                'levels': ['warning', 'critical'],
                'is_enabled': True,
            }],
            'is_enabled': True,
        }
        payload.update(overrides)
        return payload

    def create_source(self, provider, **overrides):
        serializer = AlertSourceSerializer(data=self.source_payload(provider, **overrides))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.save()

    def test_all_source_types_use_one_serializer_contract(self):
        for provider in ('prometheus', 'alertmanager', 'zabbix'):
            serializer = AlertSourceSerializer(data=self.source_payload(provider))
            self.assertTrue(serializer.is_valid(), serializer.errors)
            source = serializer.save()
            self.assertEqual(source.provider, provider)
            self.assertEqual(source.owner_bindings.get().role, AlertSourceOwner.ROLE_PRIMARY)

    def test_enabled_source_requires_exactly_one_primary_owner(self):
        serializer = AlertSourceSerializer(data={
            'name': 'Missing owner',
            'provider': 'alertmanager',
            'owner_bindings': [],
            'is_enabled': True,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('owner_bindings', serializer.errors)

    def test_alertmanager_fingerprint_is_source_scoped_and_ignores_waiting_reason(self):
        first = AlertSourceSerializer(data=self.source_payload('alertmanager', name='AM first'))
        second = AlertSourceSerializer(data=self.source_payload('alertmanager', name='AM second'))
        self.assertTrue(first.is_valid(), first.errors)
        self.assertTrue(second.is_valid(), second.errors)
        first_source = first.save()
        second_source = second.save()

        def payload(reason):
            return {
                'status': 'firing',
                'alerts': [{
                    'status': 'firing',
                    'labels': {
                        'alertname': 'K8S容器组Waiting',
                        'cluster': 'prod',
                        'namespace': 'kube-ai',
                        'pod': 'nginx-123',
                        'container': 'nginx',
                        'uid': 'pod-uid-1',
                        'reason': reason,
                        'severity': 'warning',
                    },
                    'annotations': {'message': reason},
                    'startsAt': '2026-07-29T08:00:00Z',
                    'fingerprint': f'upstream-{reason}',
                }],
            }

        _, first_reason = prepare_external_alerts(payload('ErrImagePull'), first_source)
        _, second_reason = prepare_external_alerts(payload('ImagePullBackOff'), first_source)
        _, other_source = prepare_external_alerts(payload('ErrImagePull'), second_source)
        self.assertEqual(first_reason[0]['fingerprint'], second_reason[0]['fingerprint'])
        self.assertNotEqual(first_reason[0]['fingerprint'], other_source[0]['fingerprint'])

    def test_routes_select_level_and_unacknowledged_voice_escalation(self):
        source = self.create_source('zabbix')
        source.owner_bindings.update(levels=['critical'])
        feishu = AlertNotificationChannel.objects.create(
            name='警告群', channel_type='feishu', config={'webhook_url': 'https://example.test'},
        )
        voice = AlertNotificationChannel.objects.create(
            name='严重语音', channel_type='voice', config={},
        )
        policy = AlertNotificationPolicy.objects.create(
            name='生产分级通知', alert_source=source, group_wait_seconds=0,
        )
        AlertNotificationRoute.objects.create(
            policy=policy, level='warning', trigger='immediate', channel=feishu, target_type='fixed',
        )
        escalation = AlertNotificationRoute.objects.create(
            policy=policy,
            level='warning',
            trigger='unacknowledged',
            after_minutes=5,
            escalate_to_level='critical',
            channel=voice,
            target_type='source_owners',
        )
        alert = Alert.objects.create(
            title='Redis 内存风险',
            level='warning',
            status=Alert.STATUS_ACTIVE,
            source=source.code,
            source_type=Alert.SOURCE_ZABBIX,
            alert_source=source,
            message='memory high',
            starts_at=timezone.now() - timedelta(minutes=6),
        )

        with patch('ops.alerting.send_alert_notification') as send:
            dispatch_alert_notifications(alert, action='fire', force=True)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.args[0].id, feishu.id)

        captured = {}

        def fake_send(channel, target_alert, contacts, **kwargs):
            captured.update({'channel': channel, 'contacts': contacts, 'metadata': kwargs['notification_metadata']})
            return AlertNotificationLog.objects.create(
                alert=target_alert,
                policy_id=policy.id,
                channel_id=channel.id,
                action='escalation',
                status=AlertNotificationLog.STATUS_SUCCESS,
                request_payload=kwargs['notification_metadata'],
                sent_at=timezone.now(),
            )

        with patch('ops.alerting.send_alert_notification', side_effect=fake_send):
            self.assertTrue(apply_escalation_policy(alert))
        alert.refresh_from_db()
        self.assertEqual(captured['channel'].id, voice.id)
        self.assertEqual(captured['metadata']['route_id'], escalation.id)
        self.assertEqual(captured['contacts']['voice_phones'], ['13800000000'])
        self.assertEqual(alert.level, 'critical')

    def test_analysis_inherits_successful_warning_route_after_level_escalation(self):
        source = self.create_source('zabbix')
        feishu = AlertNotificationChannel.objects.create(
            name='警告群', channel_type='feishu', config={'webhook_url': 'https://example.test'},
        )
        voice = AlertNotificationChannel.objects.create(
            name='严重语音', channel_type='voice', config={},
        )
        policy = AlertNotificationPolicy.objects.create(
            name='分级通知', alert_source=source, group_wait_seconds=0,
        )
        warning_route = AlertNotificationRoute.objects.create(
            policy=policy, level='warning', trigger='immediate', channel=feishu, target_type='fixed',
        )
        AlertNotificationRoute.objects.create(
            policy=policy, level='critical', trigger='immediate', channel=voice, target_type='fixed',
        )
        alert = Alert.objects.create(
            title='内存风险', level='critical', status=Alert.STATUS_ACTIVE,
            source=source.code, source_type=Alert.SOURCE_ZABBIX, alert_source=source,
            starts_at=timezone.now() - timedelta(minutes=1),
        )
        AlertNotificationLog.objects.create(
            alert=alert, policy_id=policy.id, channel_id=feishu.id, action='fire',
            status=AlertNotificationLog.STATUS_SUCCESS,
            request_payload={'route_id': warning_route.id}, sent_at=timezone.now(),
        )

        with patch('ops.alerting.send_alert_notification') as send:
            dispatch_alert_notifications(alert, action='analysis', force=True)

        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[0].id, feishu.id)

    def test_policy_rejects_duplicate_routes_with_empty_recipient_group(self):
        source = self.create_source('alertmanager')
        channel = AlertNotificationChannel.objects.create(
            name='飞书群', channel_type='feishu', config={'webhook_url': 'https://example.test'},
        )
        route = {
            'level': 'warning', 'trigger': 'immediate', 'channel': channel.id,
            'target_type': 'fixed', 'recipient_group': None,
        }
        serializer = AlertNotificationPolicySerializer(data={
            'name': '重复路由', 'alert_source': source.id, 'routes': [route, route],
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('routes', serializer.errors)

    def test_only_published_template_can_be_instantiated(self):
        source = self.create_source('prometheus')
        template = AlertRule.objects.create(
            name='CPU 高使用率',
            code='custom-cpu-high',
            source='custom-cpu-high',
            source_type='prometheus',
            category='server',
            is_template=True,
            template_status='draft',
            query_config={'promql': 'up'},
            condition={'operator': '>', 'threshold': 0},
        )
        with self.assertRaisesMessage(ValueError, '只有已发布'):
            instantiate_rule_from_template(template, alert_source=source)
        template.template_status = 'published'
        template.save(update_fields=['template_status'])
        rule, created = instantiate_rule_from_template(template, alert_source=source)
        self.assertTrue(created)
        self.assertEqual(rule.alert_source, source)
        self.assertFalse(rule.is_enabled)
