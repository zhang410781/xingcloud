from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .events import record_event, run_due_event_cleanup
from .models import Alert, AlertSource, Event


class EventRecordTests(TestCase):
    def setUp(self):
        self.alert_source = AlertSource.objects.create(
            name='Event Test Source', code='event-test-source', provider=AlertSource.PROVIDER_ZABBIX,
        )
        self.alert = Alert.objects.create(
            title='CPU high', level='warning', source='monitor', source_type=Alert.SOURCE_PLATFORM,
            alert_source=self.alert_source, message='cpu high',
        )

    def test_new_semantics_records_event(self):
        event = record_event(
            source_type='deployment', kind='release_failed', severity='error',
            title='发布失败', message='发布单 demo 执行失败',
            target_type='deployment', target_resource='demo-release-1',
            alert=self.alert,
            payload={'deployment_id': 1, 'actor': 'system'},
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.source_type, 'deployment')
        self.assertEqual(event.kind, 'release_failed')
        self.assertEqual(event.severity, 'error')
        self.assertEqual(event.target_resource, 'demo-release-1')
        self.assertEqual(event.alert_id, self.alert.id)
        self.assertEqual(event.payload['deployment_id'], 1)

    def test_legacy_semantics_maps_to_new_fields(self):
        event = record_event(
            module='ops', category='execution', action='deploy_finish',
            title='发布执行成功', summary='发布单 demo 执行成功',
            result='success', severity='info',
            resource_type='deployment', resource_id=1, resource_name='demo',
            actor_username='zhang', correlation_id='deployment:1',
            metadata={'extra': 1},
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.source_type, 'deployment')
        self.assertEqual(event.kind, 'deploy_finish')
        self.assertEqual(event.target_type, 'deployment')
        self.assertEqual(event.target_resource, 'demo')
        self.assertEqual(event.payload['legacy']['result'], 'success')
        self.assertEqual(event.payload['legacy']['actor_username'], 'zhang')
        self.assertEqual(event.payload['extra'], 1)

    def test_legacy_alert_resource_binds_alert_fk(self):
        event = record_event(
            module='ops', category='alert', action='acknowledge',
            title='确认告警', summary='已确认',
            resource_type='alert', resource_id=self.alert.id, resource_name=self.alert.title,
        )
        self.assertEqual(event.alert_id, self.alert.id)
        self.assertEqual(event.source_type, 'alerting')

    def test_record_event_never_raises(self):
        with patch('ops.events.Event.objects.create', side_effect=RuntimeError('db down')):
            event = record_event(source_type='system', kind='test')
        self.assertIsNone(event)

    def test_empty_kind_defaults_to_system_event(self):
        event = record_event(module='ops', category='security', action='', title='t')
        self.assertEqual(event.kind, 'system_event')
        self.assertEqual(event.source_type, 'security')


class EventWebhookIngestTests(TestCase):
    def _payload(self, status='firing', fingerprint='fp-1', alertname='CPUHigh'):
        return {
            'status': status,
            'alerts': [{
                'status': status,
                'labels': {'alertname': alertname, 'severity': 'warning', 'instance': '10.0.0.1'},
                'annotations': {'summary': 'CPU high'},
                'startsAt': '2026-08-05T10:00:00Z',
                'endsAt': '0001-01-01T00:00:00Z',
                'fingerprint': fingerprint,
            }],
        }

    def _ingest(self, payload):
        from .alert_ingest import ingest_external_alert_payload

        with patch('ops.alert_ingest.dispatch_alert_batch_notifications', return_value={}), \
                patch('ops.alert_ingest.apply_escalation_policy', return_value=False), \
                patch('ops.alert_analysis.enqueue_lightweight_analysis', return_value=(None, False)):
            return ingest_external_alert_payload(payload)

    def test_active_ingest_records_alert_active_event(self):
        result = self._ingest(self._payload())
        alert = Alert.objects.get(fingerprint=result['results'][0]['fingerprint'])
        events = list(Event.objects.filter(alert=alert).order_by('id'))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, 'alert_active')
        self.assertEqual(events[0].source_type, 'webhook')
        self.assertEqual(events[0].severity, 'warning')

    def test_resolved_records_alert_resolved_event(self):
        self._ingest(self._payload())
        result = self._ingest(self._payload(status='resolved'))
        alert = Alert.objects.get(fingerprint=result['results'][0]['fingerprint'])
        kinds = list(Event.objects.filter(alert=alert).values_list('kind', flat=True))
        self.assertEqual(sorted(kinds), ['alert_active', 'alert_resolved'])

    def test_reactivated_records_alert_reactivated_event(self):
        self._ingest(self._payload())
        self._ingest(self._payload(status='resolved'))
        result = self._ingest(self._payload(status='firing'))
        alert = Alert.objects.get(fingerprint=result['results'][0]['fingerprint'])
        kinds = list(Event.objects.filter(alert=alert).values_list('kind', flat=True))
        self.assertEqual(sorted(kinds), ['alert_active', 'alert_reactivated', 'alert_resolved'])

    def test_same_status_upsert_does_not_write_event(self):
        self._ingest(self._payload())
        self._ingest(self._payload(fingerprint='fp-2'))
        self._ingest(self._payload(fingerprint='fp-3'))
        self.assertEqual(Event.objects.filter(kind='alert_active').count(), 3)


class EventInternalHookTests(TestCase):
    def test_deployer_emit_deployment_event_uses_new_semantics(self):
        from . import deployer

        deployment = Mock()
        deployment.release_name = 'demo-release-1'
        deployment.app_name = 'demo'
        deployment.version = 'v1'
        deployment.business_line = 'demo-biz'
        deployment.environment = 'prod'
        deployment.deployer = 'zhang'

        with patch('ops.deployer.record_event') as mocked:
            deployer._emit_deployment_event(
                deployment, 'service_started', 'info', '启动应用实例', '应用 demo 已启动',
            )
        mocked.assert_called_once()
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs['source_type'], 'deployment')
        self.assertEqual(kwargs['kind'], 'service_started')
        self.assertEqual(kwargs['target_type'], 'deployment')
        self.assertEqual(kwargs['target_resource'], 'demo-release-1')
        self.assertEqual(kwargs['payload']['environment'], 'prod')

    def test_discovery_run_records_event(self):
        from resource_center.discovery import _record_discovery_event

        run = Mock()
        run.status = 'completed'
        run.id = 42
        run.source_id = 7
        run.source = Mock(name='k8s-prod')
        run.source.name = 'k8s-prod'
        run.source.source_type = 'k8s'
        run.error = ''
        _record_discovery_event(run)
        event = Event.objects.get(kind='discovery_success')
        self.assertEqual(event.source_type, 'discovery')
        self.assertEqual(event.target_resource, 'k8s-prod')
        self.assertEqual(event.payload['run_id'], 42)

    def test_discovery_failed_records_error_event(self):
        from resource_center.discovery import _record_discovery_event

        run = Mock()
        run.status = 'failed'
        run.id = 43
        run.source_id = 7
        run.source = Mock(name='k8s-prod')
        run.source.name = 'k8s-prod'
        run.source.source_type = 'k8s'
        run.error = 'timeout'
        _record_discovery_event(run)
        event = Event.objects.get(kind='discovery_failed')
        self.assertEqual(event.severity, 'error')
        self.assertEqual(event.payload['error'], 'timeout')

    def test_inspection_run_records_event(self):
        from .inspection_reports import _record_inspection_event
        from .models import InspectionReportExecution, InspectionReportSchedule
        from aiops.models import AIOpsKnowledgeEnvironment

        environment = AIOpsKnowledgeEnvironment.objects.create(name='测试环境')
        schedule = InspectionReportSchedule.objects.create(name='每日巡检', is_enabled=True, knowledge_environment=environment)
        execution = InspectionReportExecution.objects.create(
            schedule=schedule, status=InspectionReportExecution.STATUS_SUCCESS,
        )
        _record_inspection_event(schedule, execution, 'inspection_completed', 'info')
        event = Event.objects.get(kind='inspection_completed')
        self.assertEqual(event.source_type, 'inspection')
        self.assertEqual(event.target_resource, '每日巡检')
        self.assertEqual(event.payload['execution_id'], execution.id)


class EventApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('event-user', 'event@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)
        self.alert_source = AlertSource.objects.create(
            name='Event API Source', code='event-api-source', provider=AlertSource.PROVIDER_ZABBIX,
        )
        self.alert = Alert.objects.create(
            title='CPU high', level='warning', source='monitor', source_type=Alert.SOURCE_PLATFORM,
            alert_source=self.alert_source, message='cpu high',
        )
        self.event_a = record_event(
            source_type='deployment', kind='release_success', severity='info',
            title='发布成功', message='app-a 发布成功',
            target_type='deployment', target_resource='app-a-release',
            alert=self.alert,
        )
        self.event_b = record_event(
            source_type='webhook', kind='alert_active', severity='warning',
            title='告警触发', message='CPU 高',
            target_type='pod', target_resource='pod-a',
            occurred_at=timezone.now() - timedelta(days=5),
        )

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/events/')
        self.assertEqual(response.status_code, 401)

    def test_list_and_filter(self):
        response = self.client.get('/api/events/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 2)

        response = self.client.get('/api/events/', {'source_type': 'webhook'})
        self.assertEqual(response.json()['count'], 1)
        self.assertEqual(response.json()['results'][0]['kind'], 'alert_active')

        response = self.client.get('/api/events/', {'kind': 'release_success'})
        self.assertEqual(response.json()['count'], 1)

        response = self.client.get('/api/events/', {'alert_id': self.alert.id})
        self.assertEqual(response.json()['count'], 1)
        self.assertEqual(response.json()['results'][0]['alert_id'], self.alert.id)

        response = self.client.get('/api/events/', {'target_resource': 'app-a'})
        self.assertEqual(response.json()['count'], 1)

        response = self.client.get('/api/events/', {'search': 'CPU'})
        self.assertEqual(response.json()['count'], 1)

    def test_ordering_by_occurred_at(self):
        response = self.client.get('/api/events/', {'ordering': '-occurred_at'})
        results = response.json()['results']
        self.assertEqual(results[0]['id'], self.event_a.id)
        response = self.client.get('/api/events/', {'ordering': 'occurred_at'})
        results = response.json()['results']
        self.assertEqual(results[0]['id'], self.event_b.id)

    def test_retrieve_detail(self):
        response = self.client.get(f'/api/events/{self.event_a.id}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['kind'], 'release_success')
        self.assertEqual(data['alert_id'], self.alert.id)


class EventCleanupTests(TestCase):
    def test_expired_events_are_removed(self):
        record_event(source_type='system', kind='old', occurred_at=timezone.now() - timedelta(days=40))
        record_event(source_type='system', kind='recent', occurred_at=timezone.now() - timedelta(days=5))
        deleted = run_due_event_cleanup()
        self.assertEqual(deleted, 1)
        self.assertEqual(Event.objects.filter(kind='old').count(), 0)
        self.assertEqual(Event.objects.filter(kind='recent').count(), 1)

    @override_settings(EVENT_RETENTION_DAYS=7)
    def test_retention_days_configurable(self):
        record_event(source_type='system', kind='old', occurred_at=timezone.now() - timedelta(days=10))
        record_event(source_type='system', kind='recent', occurred_at=timezone.now() - timedelta(days=3))
        self.assertEqual(run_due_event_cleanup(), 1)
        self.assertEqual(Event.objects.filter(kind='old').count(), 0)
        self.assertEqual(Event.objects.filter(kind='recent').count(), 1)

    def test_cleanup_limit(self):
        for index in range(5):
            record_event(source_type='system', kind=f'old-{index}', occurred_at=timezone.now() - timedelta(days=40))
        self.assertEqual(run_due_event_cleanup(limit=2), 2)
        self.assertEqual(Event.objects.count(), 3)


class EventSchedulerHookTests(TestCase):
    def test_scheduler_runs_event_cleanup_hourly(self):
        from .ops_scheduler import run_ops_scheduler_once

        with patch('ops.ops_scheduler.run_due_schedules', return_value={}), \
                patch('ops.ops_scheduler.run_datasource_health_checks', return_value={}), \
                patch('ops.ops_scheduler.run_due_alert_rules', return_value={}), \
                patch('ops.ops_scheduler.run_due_external_alert_escalations', return_value={}), \
                patch('ops.ops_scheduler.run_due_alert_analyses', return_value={}), \
                patch('ops.ops_scheduler.run_due_inspection_reports', return_value={}), \
                patch('ops.ops_scheduler.run_due_discoveries', return_value={}), \
                patch('ops.ops_scheduler.run_due_event_cleanup', return_value=0) as mocked_cleanup:
            result = run_ops_scheduler_once()
            result = run_ops_scheduler_once()

        self.assertEqual(mocked_cleanup.call_count, 1)
        self.assertIn('event_cleanup', result)
