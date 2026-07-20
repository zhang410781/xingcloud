from datetime import datetime, time, timedelta, timezone as datetime_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from aiops.models import AIOpsKnowledgeEnvironment
from ops.inspection_reports import compute_next_inspection_report_run, run_due_inspection_reports
from ops.observability_evidence import inspection_result
from ops.models import (
    AlertNotificationChannel,
    AlertRecipient,
    InspectionReportExecution,
    InspectionReportSchedule,
)


class InspectionReportScheduleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='inspection-admin', email='admin@example.com', password='Admin@123456',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.context = AIOpsKnowledgeEnvironment.objects.create(
            name='生产集群', code='production', business_line='XingCloud', is_enabled=True,
        )
        self.channel = AlertNotificationChannel.objects.create(
            name='飞书运维群', channel_type=AlertNotificationChannel.CHANNEL_FEISHU,
            config={'webhook_url': 'https://example.com/hook', 'secret': 'secret'},
        )
        self.recipient = AlertRecipient.objects.create(
            name='张三', email='zhangsan@example.com', is_enabled=True,
        )

    def _payload(self, **overrides):
        payload = {
            'name': '生产集群周报',
            'knowledge_environment': self.context.id,
            'frequency': 'weekly',
            'weekday': 1,
            'send_time': '09:30:00',
            'timezone': 'Asia/Shanghai',
            'profile': 'cluster',
            'depth': 'full',
            'window_minutes': 60,
            'channel_ids': [self.channel.id],
            'recipient_ids': [self.recipient.id],
            'recipient_group_ids': [],
            'is_enabled': True,
        }
        payload.update(overrides)
        return payload

    def test_create_schedule_resolves_recipient_by_name_and_sets_next_run(self):
        response = self.client.post('/api/inspection-report-schedules/', self._payload(), format='json')

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['recipients'][0]['name'], '张三')
        self.assertEqual(payload['channels'][0]['name'], '飞书运维群')
        self.assertIsNotNone(payload['next_run_at'])
        self.assertEqual(payload['last_status'], 'never')

    def test_recipient_uses_channel_choices_without_exposing_user_ids(self):
        response = self.client.post('/api/alert-recipients/', {
            'name': '李四',
            'preferred_channels': ['email', 'feishu'],
            'email': 'lisi@example.com',
            'is_enabled': True,
        }, format='json')

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['contact_channels'], ['email', 'feishu'])
        self.assertNotIn('feishu_user_id', payload)
        self.assertNotIn('dingtalk_user_id', payload)
        self.assertNotIn('wecom_user_id', payload)

    def test_recipient_channel_requires_matching_contact(self):
        response = self.client.post('/api/alert-recipients/', {
            'name': '王五',
            'preferred_channels': ['sms'],
            'is_enabled': True,
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('手机号', str(response.data))

    def test_enabled_schedule_requires_channel_and_recipient(self):
        response = self.client.post(
            '/api/inspection-report-schedules/',
            self._payload(channel_ids=[], recipient_ids=[]),
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('至少需要一个通知渠道', str(response.data))

    def test_schedule_only_accepts_cluster_or_server_profile(self):
        server_response = self.client.post(
            '/api/inspection-report-schedules/',
            self._payload(name='服务器日报', profile='server'),
            format='json',
        )
        legacy_response = self.client.post(
            '/api/inspection-report-schedules/',
            self._payload(name='节点日报', profile='node'),
            format='json',
        )

        self.assertEqual(server_response.status_code, 201)
        self.assertEqual(server_response.json()['profile_display'], '服务器巡检')
        self.assertEqual(legacy_response.status_code, 400)

    def test_weekly_next_run_uses_selected_weekday_and_time(self):
        schedule = InspectionReportSchedule(
            name='weekly', knowledge_environment=self.context,
            frequency='weekly', weekday=3, send_time=time(9, 30), timezone='Asia/Shanghai',
        )
        now = datetime(2026, 7, 20, 2, 0, tzinfo=datetime_timezone.utc)

        next_run = compute_next_inspection_report_run(schedule, now=now)

        local_next = timezone.localtime(next_run, timezone=ZoneInfo('Asia/Shanghai'))
        self.assertEqual(local_next.isoweekday(), 3)
        self.assertEqual((local_next.hour, local_next.minute), (9, 30))

    @patch('ops.inspection_reports.send_plain_notification')
    @patch('ops.inspection_reports.inspection_result')
    @patch('ops.inspection_reports.collect_observability_evidence')
    def test_run_now_generates_report_and_sends_to_selected_recipient(self, collect, build_result, send):
        schedule = InspectionReportSchedule.objects.create(
            name='daily', knowledge_environment=self.context,
            frequency='daily', weekday=1, send_time=time(9, 0), next_run_at=timezone.now() + timedelta(days=1),
        )
        schedule.channels.add(self.channel)
        schedule.recipients.add(self.recipient)
        collect.return_value = {'profile': 'cluster', 'diagnostics': []}
        build_result.return_value = {
            'health_score': 92,
            'conclusion': '集群存在需要关注的问题',
            'cluster_summary': {'node_count': 4, 'ready_nodes': 4, 'pod_count': 20, 'pod_status': {'Running': 20}},
            'findings': [], 'suggestions': ['保持监控'], 'missing_evidence': [],
        }
        send.return_value = {
            'channel_id': self.channel.id, 'channel_name': self.channel.name,
            'channel_type': self.channel.channel_type, 'status': 'success',
            'recipient_summary': '张三', 'request': {}, 'response_body': 'ok',
            'error_message': '', 'sent_at': timezone.now().isoformat(),
        }

        response = self.client.post(f'/api/inspection-report-schedules/{schedule.id}/run-now/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], InspectionReportExecution.STATUS_SUCCESS)
        contacts = send.call_args.args[1]
        self.assertEqual(contacts['names'], ['张三'])
        self.assertEqual(contacts['emails'], ['zhangsan@example.com'])
        schedule.refresh_from_db()
        self.assertEqual(schedule.last_status, InspectionReportSchedule.STATUS_SUCCESS)
        self.assertEqual(schedule.last_report['health_score'], 92)

    @patch('ops.inspection_reports.send_plain_notification')
    @patch('ops.inspection_reports.inspection_result')
    @patch('ops.inspection_reports.collect_observability_evidence')
    def test_server_report_uses_server_profile_without_k8s_scope(self, collect, build_result, send):
        schedule = InspectionReportSchedule.objects.create(
            name='server-daily', knowledge_environment=self.context, profile='server',
            frequency='daily', weekday=1, send_time=time(9, 0), next_run_at=timezone.now() + timedelta(days=1),
        )
        schedule.channels.add(self.channel)
        schedule.recipients.add(self.recipient)
        collect.return_value = {'profile': 'server', 'diagnostics': []}
        build_result.return_value = {
            'profile': 'server', 'health_score': 100, 'conclusion': '服务器运行正常',
            'server_summary': {'node_count': 3, 'node_cpu': 22.5, 'node_memory': 61.2},
            'findings': [], 'suggestions': ['保持监控'], 'missing_evidence': [],
        }
        send.return_value = {'status': 'success', 'error_message': '', 'response_body': 'ok'}

        response = self.client.post(f'/api/inspection-report-schedules/{schedule.id}/run-now/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(collect.call_args.kwargs['profile'], 'server')
        self.assertIn('服务器资源指标', send.call_args.kwargs['body'])
        self.assertNotIn('Pod：', send.call_args.kwargs['body'])

    @patch('ops.inspection_reports.send_plain_notification')
    @patch('ops.inspection_reports.inspection_result')
    @patch('ops.inspection_reports.collect_observability_evidence')
    def test_cluster_report_includes_evidence_sections_and_missing_metric_state(self, collect, build_result, send):
        schedule = InspectionReportSchedule.objects.create(
            name='cluster-daily', knowledge_environment=self.context,
            frequency='daily', send_time=time(9, 0), next_run_at=timezone.now() + timedelta(days=1),
        )
        schedule.channels.add(self.channel)
        schedule.recipients.add(self.recipient)
        collect.return_value = {'profile': 'cluster', 'diagnostics': []}
        build_result.return_value = {
            'health_score': 92, 'conclusion': '集群存在需要关注的问题',
            'cluster_summary': {'node_count': 2, 'ready_nodes': 2, 'pod_count': 3, 'pod_status': {'Running': 3}},
            'findings': [], 'suggestions': ['检查指标采集链路'], 'missing_evidence': ['CPU 指标未获取'],
            'evidence': {
                'source_coverage': {'metrics': False, 'k8s': True, 'logs': True},
                'metrics': [{'title': 'CPU 使用率', 'status': 'error'}],
                'k8s': {
                    'cluster': {'name': 'production'},
                    'nodes': [{'name': 'node-1', 'status': 'Ready'}],
                    'pods': [{'namespace': 'default', 'name': 'api-1', 'status': 'Running', 'restarts': 2}],
                    'resources': {'deployments': [], 'statefulsets': [], 'daemonsets': [], 'pvcs': []},
                },
                'logs': {'samples': [{'message': 'application started'}]},
                'log_findings': [], 'event_findings': [],
            },
        }
        send.return_value = {'status': 'success', 'error_message': '', 'response_body': 'ok'}

        response = self.client.post(f'/api/inspection-report-schedules/{schedule.id}/run-now/')

        self.assertEqual(response.status_code, 200)
        body = send.call_args.kwargs['body']
        self.assertIn('数据源覆盖', body)
        self.assertIn('节点状态', body)
        self.assertIn('Pod 与重启排行', body)
        self.assertIn('指标采样', body)
        self.assertIn('CPU 使用率：未获取', body)
        self.assertIn('日志与事件', body)
        self.assertIn('未获取证据及原因', body)

    @patch('ops.inspection_reports.run_inspection_report_schedule')
    def test_scheduler_advances_next_run_before_execution(self, run_schedule):
        schedule = InspectionReportSchedule.objects.create(
            name='due', knowledge_environment=self.context,
            frequency='daily', weekday=1, send_time=time(9, 0), next_run_at=timezone.now() - timedelta(minutes=1),
        )
        schedule.channels.add(self.channel)
        schedule.recipients.add(self.recipient)
        run_schedule.return_value = InspectionReportExecution.objects.create(
            schedule=schedule, status=InspectionReportExecution.STATUS_SUCCESS,
        )

        result = run_due_inspection_reports()

        self.assertEqual(result, {'checked': 1, 'completed': 1, 'failed': 0})
        schedule.refresh_from_db()
        self.assertGreater(schedule.next_run_at, timezone.now())

    def test_referenced_recipient_cannot_be_deleted(self):
        schedule = InspectionReportSchedule.objects.create(
            name='protected', knowledge_environment=self.context,
            frequency='daily', send_time=time(9, 0), next_run_at=timezone.now() + timedelta(days=1),
        )
        schedule.channels.add(self.channel)
        schedule.recipients.add(self.recipient)

        response = self.client.delete(f'/api/alert-recipients/{self.recipient.id}/')

        self.assertEqual(response.status_code, 409)
        self.assertIn('巡检报告计划', response.json()['detail'])

    def test_incomplete_cluster_evidence_does_not_claim_the_cluster_is_healthy(self):
        result = inspection_result({
            'profile': 'cluster',
            'source_coverage': {'metrics': False, 'k8s': True, 'logs': True},
            'k8s': {'summary': {'node_count': 4, 'ready_nodes': 4, 'pod_count': 10}},
            'k8s_findings': [], 'log_findings': [], 'metric_anomalies': [],
            'metrics': [], 'diagnostics': [{'message': '指标数据缺失'}],
        })

        self.assertEqual(result['status'], 'partial')
        self.assertIn('证据不完整', result['conclusion'])
        self.assertNotEqual(result['conclusion'], '集群运行正常')
