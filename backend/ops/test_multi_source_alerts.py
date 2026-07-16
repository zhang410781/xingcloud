from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from ops.alert_engine.evaluator import evaluate_rule
from ops.alert_rule_presets import ensure_builtin_alert_rule_templates, instantiate_rule_from_template
from ops.alert_rules import build_platform_alert_payload
from ops.alerting import dispatch_alert_notifications, resolve_notification_policies
from ops.models import (
    Alert,
    AlertNotificationChannel,
    AlertNotificationLog,
    AlertNotificationPolicy,
    AlertRule,
    MetricDataSource,
)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class MultiSourceAlertRuleTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('multi-source-admin', 'admin@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)
        self.prod = MetricDataSource.objects.create(
            name='生产 Prometheus',
            environment='prod',
            cluster_name='prod-k8s',
            config={'url': 'http://prometheus-prod.example.com'},
            is_enabled=True,
        )
        self.test = MetricDataSource.objects.create(
            name='测试 Prometheus',
            environment='test',
            cluster_name='test-k8s',
            config={'url': 'http://prometheus-test.example.com'},
            is_enabled=True,
        )
        ensure_builtin_alert_rule_templates()
        self.template = AlertRule.objects.filter(is_template=True, source_type='prometheus', category='k8s').first()
        if not self.template:
            self.template = AlertRule.objects.create(
                name='K8S CPU 使用率过高',
                code='k8s-cpu-high-test-template',
                category='k8s',
                source='k8s-cpu-high-test-template',
                is_template=True,
                source_type='prometheus',
                level='warning',
                query_config={'query': 'node_cpu_usage_percent'},
                condition={'operator': '>', 'threshold': 80},
                is_enabled=False,
            )

    def test_template_instantiation_creates_source_bound_disabled_rule(self):
        AlertRule.objects.filter(template=self.template, metric_datasource=self.prod).delete()
        response = self.client.post(
            '/api/alert-rules/instantiate/',
            {
                'template_code': self.template.code,
                'metric_datasource_id': self.prod.id,
                'overrides': {'condition': {'operator': '>', 'threshold': 88}},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        rule = AlertRule.objects.get(pk=response.json()['id'])
        self.assertEqual(rule.template_id, self.template.id)
        self.assertEqual(rule.metric_datasource_id, self.prod.id)
        self.assertFalse(rule.is_template)
        self.assertFalse(rule.is_enabled)
        self.assertEqual(rule.condition['threshold'], 88)
        self.assertEqual(rule.labels['cluster'], 'prod-k8s')

    @patch('ops.alert_engine.evaluator.execute_promql_query')
    def test_same_template_queries_each_bound_prometheus_source(self, mock_query):
        mock_query.return_value = {
            'result': [{'metric': {'instance': 'node-1'}, 'value': [1710000000, '95']}],
        }
        prod_rule, _ = instantiate_rule_from_template(self.template, self.prod)
        test_rule, _ = instantiate_rule_from_template(self.template, self.test)

        prod_result = evaluate_rule(prod_rule, dry_run=True)
        test_result = evaluate_rule(test_rule, dry_run=True)

        self.assertTrue(prod_result['success'])
        self.assertTrue(test_result['success'])
        self.assertEqual(mock_query.call_args_list[0].kwargs['metric_datasource_id'], self.prod.id)
        self.assertEqual(mock_query.call_args_list[1].kwargs['metric_datasource_id'], self.test.id)
        self.assertEqual(prod_result['results'][0]['labels']['metric_datasource_id'], str(self.prod.id))
        self.assertEqual(test_result['results'][0]['labels']['metric_datasource_id'], str(self.test.id))

        prod_payload = build_platform_alert_payload(prod_rule, prod_result['results'][0])
        test_payload = build_platform_alert_payload(test_rule, test_result['results'][0])
        self.assertNotEqual(prod_payload['fingerprint'], test_payload['fingerprint'])

    def test_unbound_prometheus_rule_returns_configuration_error(self):
        rule = AlertRule.objects.create(
            name='未绑定 Prometheus 规则',
            code='unbound-prometheus-rule',
            source_type='prometheus',
            query_config={'query': 'up'},
            condition={'operator': '>', 'threshold': 0},
            is_enabled=False,
        )

        result = evaluate_rule(rule, dry_run=True)

        self.assertFalse(result['success'])
        self.assertIn('尚未绑定指标数据源', result['error'])

    def test_source_policy_precedes_global_policy_and_preview_matches(self):
        global_policy = AlertNotificationPolicy.objects.create(name='全局策略', priority=100)
        source_policy = AlertNotificationPolicy.objects.create(
            name='生产集群策略',
            metric_datasource=self.prod,
            priority=10,
            matchers=[{'key': 'namespace', 'operator': '=', 'value': 'xing-cloud'}],
        )
        alert = Alert(
            title='Pod 异常', level='warning', source='test', source_type=Alert.SOURCE_PLATFORM,
            message='test', cluster='prod-k8s', namespace='xing-cloud',
            labels={'metric_datasource_id': str(self.prod.id), 'namespace': 'xing-cloud'},
        )

        matched = resolve_notification_policies(alert, metric_datasource_id=self.prod.id)
        self.assertEqual([item.id for item in matched], [source_policy.id])

        source_policy.continue_matching = True
        source_policy.save(update_fields=['continue_matching'])
        matched = resolve_notification_policies(alert, metric_datasource_id=self.prod.id)
        self.assertEqual([item.id for item in matched], [source_policy.id, global_policy.id])

        response = self.client.post(
            '/api/alert-notification-policies/preview/',
            {
                'metric_datasource_id': self.prod.id,
                'level': 'warning',
                'namespace': 'xing-cloud',
                'labels': {'metric_datasource_id': str(self.prod.id), 'namespace': 'xing-cloud'},
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['matched_count'], 2)

    def test_notification_group_and_repeat_dedup_include_datasource(self):
        rule, _ = instantiate_rule_from_template(self.template, self.prod)
        rule.is_enabled = True
        rule.notify_enabled = True
        rule.save(update_fields=['is_enabled', 'notify_enabled'])
        channel = AlertNotificationChannel.objects.create(
            name='平台值班邮箱',
            channel_type=AlertNotificationChannel.CHANNEL_EMAIL,
            config={'to': ['ops@example.com']},
        )
        policy = AlertNotificationPolicy.objects.create(
            name='生产通知策略',
            metric_datasource=self.prod,
            priority=10,
            group_by=['cluster', 'namespace', 'resource'],
            group_wait_seconds=0,
            group_interval_seconds=300,
            repeat_interval_minutes=30,
        )
        policy.channels.add(channel)
        alert = Alert.objects.create(
            title='Pod CPU 高',
            level='warning',
            status=Alert.STATUS_ACTIVE,
            source='Xing-Cloud 告警规则',
            source_type=Alert.SOURCE_PLATFORM,
            message='CPU high',
            cluster='prod-k8s',
            namespace='xing-cloud',
            resource='api-0',
            labels={
                'alert_rule_id': str(rule.id),
                'metric_datasource_id': str(self.prod.id),
                'cluster': 'prod-k8s',
                'namespace': 'xing-cloud',
            },
            starts_at=timezone.now() - timedelta(minutes=1),
        )

        first = dispatch_alert_notifications(alert)
        second = dispatch_alert_notifications(alert)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        alert.refresh_from_db()
        self.assertIn(f'label.metric_datasource_id={self.prod.id}', alert.group_key)
        log = AlertNotificationLog.objects.get()
        self.assertEqual(log.policy_id, policy.id)
