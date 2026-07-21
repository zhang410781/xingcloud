from urllib.parse import quote
import copy
import importlib
from datetime import datetime, timedelta
from decimal import Decimal
import ssl
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from cmdb.models import ResourceNode
from ops.models import (
    Alert,
    AlertAction,
    AlertInteractionToken,
    AlertRule,
    AlertNotificationChannel,
    AlertNotificationLog,
    AlertNotificationPolicy,
    AlertRecipient,
    AlertRecipientGroup,
    DockerHost,
    Deployment,
    Host,
    K8sCluster,
    K8sConfigRevision,
    LogDataSource,
    MetricDataSource,
    MiddlewareAsset,
    ObservabilityDashboard,
    ObservabilityDashboardPanel,
    TaskResourceGroup,
    TransactionTicket,
)
from ops.k8s_views import (
    _K8sApiProxy,
    _prepare_kubeconfig,
    _resource_stale_cache_key,
    _service_external_ips,
    _serialize_service_item,
    _summary_stale_cache_key,
)
from ops.datasource_health import check_log_datasource


TEST_LOG_PROVIDER_CONFIGS = {
    'loki': {
        'endpoint': 'http://loki.example:3100',
    },
    'elk': {
        'endpoint': 'https://es.example.com:9200',
        'auth_type': 'none',
        'index_pattern': 'logs-*',
        'time_field': '@timestamp',
        'message_fields': 'message,log,msg',
    },
    'clickhouse': {
        'endpoint': 'http://clickhouse.example:8123',
        'username': 'xinghai',
        'password': 'Aws_kkk',
        'collections': [
            {
                'key': 'container-logs',
                'name': 'K8S Container Logs',
                'database': 'container_logs',
                'table': 'logs',
                'time_field': 'timestamp',
                'message_fields': 'message,log_message',
                'level_field': 'log_level',
                'source_fields': 'namespace,pod_name,container_name',
                'search_fields': 'namespace,pod_name,node_name,container_name,log_level,message,log_message,source,log_file_path',
            }
        ],
    },
}

TEST_OBSERVABILITY_CONFIG = {
    'grafana': {
        'enabled': True,
        'url': 'http://grafana.example.com',
        'default_path': '/d/apm-overview',
        'demo_mode': True,
    },
}


class DashboardStatsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('dashboard-admin', 'dashboard@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)

    def test_dashboard_stats_returns_sla_cockpit_for_management(self):
        now = timezone.now()
        month_alert_time = now - timedelta(hours=3)
        old_time = now - timedelta(days=2)
        db_alert = Alert.objects.create(
            title='MySQL 涓诲簱杩炴帴澶辫触',
            level='critical',
            status=Alert.STATUS_ACTIVE,
            source='prometheus',
            message='mysql primary unavailable',
            environment='prod',
            resource_type='database',
            service='mysql',
            is_acknowledged=False,
            labels={'severity': 'disaster'},
            starts_at=month_alert_time,
            last_received_at=now,
        )
        Alert.objects.filter(pk=db_alert.pk).update(created_at=month_alert_time, updated_at=now)
        network_alert = Alert.objects.create(
            title='核心交换机丢包',
            level='warning',
            status=Alert.STATUS_ACTIVE,
            source='prometheus',
            message='packet loss',
            environment='prod',
            resource_type='network',
            service='core-network',
            is_acknowledged=True,
            starts_at=now - timedelta(minutes=20),
            last_received_at=now,
        )
        Alert.objects.filter(pk=network_alert.pk).update(created_at=now - timedelta(minutes=20), updated_at=now)
        ticket = TransactionTicket.objects.create(
            title='数据库扩容审批',
            ticket_type=TransactionTicket.TYPE_CHANGE,
            priority=TransactionTicket.PRIORITY_HIGH,
            business_line='数据库平台',
            environment='prod',
            owner='dba',
            applicant='ops',
            status=TransactionTicket.STATUS_PENDING,
        )
        TransactionTicket.objects.filter(pk=ticket.pk).update(created_at=old_time, updated_at=old_time)
        deployment = Deployment.objects.create(
            app_name='mysql-maintenance',
            business_line='数据库平台',
            version='2026.07.08',
            environment='prod',
            status='failed',
            approval_status='approved',
            action_type='deploy',
            submitter='ops',
        )
        Deployment.objects.filter(pk=deployment.pk).update(deployed_at=old_time, finished_at=old_time)

        response = self.client.get('/api/dashboard/stats/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['cockpit_title'], 'Xing-Cloud 运行总览')
        self.assertEqual(payload['sla']['target'], 99.96)
        self.assertIn(payload['sla']['month_status'], ['达标', '风险', '未达标'])
        self.assertEqual(payload['sla']['month_status'], '未达标')
        self.assertEqual(payload['sla']['annual_goal_status'], '无法达成')
        database_sla = next(item for item in payload['product_slas'] if item['key'] == 'database')
        self.assertEqual(database_sla['name'], '数据库')
        self.assertEqual(database_sla['status'], '未达标')
        self.assertGreater(database_sla['downtime_minutes'], 0)
        self.assertGreaterEqual(database_sla['alerts'], 1)
        self.assertEqual(payload['workorders']['total'], 2)
        self.assertEqual(payload['workorders']['overdue'], 2)
        self.assertLess(payload['workorders']['timely_rate'], 100)
        self.assertEqual(payload['alerts']['critical'], 1)
        self.assertEqual(payload['alerts']['warning'], 1)
        self.assertEqual(payload['alerts']['unacknowledged'], 1)
        self.assertTrue(any(item['product'] == '数据库' for item in payload['alerts']['by_product']))
        self.assertTrue(any(item['level'] == 'critical' for item in payload['alerts']['recent']))
        self.assertTrue(any('SLA' in item['title'] for item in payload['risk_items']))
        self.assertTrue(any('超时工单' in item['title'] for item in payload['risk_items']))

    def test_dashboard_sla_downtime_only_counts_disaster_alert_duration(self):
        now = timezone.now()
        critical_alert = Alert.objects.create(
            title='MySQL 连接池严重告警',
            level='critical',
            status=Alert.STATUS_ACTIVE,
            source='prometheus',
            message='database connection pool saturation',
            environment='prod',
            resource_type='database',
            service='mysql',
            is_acknowledged=False,
            starts_at=now - timedelta(hours=2),
            last_received_at=now,
        )
        Alert.objects.filter(pk=critical_alert.pk).update(created_at=now - timedelta(hours=2), updated_at=now)

        response = self.client.get('/api/dashboard/stats/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        database_sla = next(item for item in payload['product_slas'] if item['key'] == 'database')
        self.assertEqual(payload['sla']['month_status'], '达标')
        self.assertEqual(payload['sla']['month_downtime_minutes'], 0)
        self.assertEqual(database_sla['status'], '达标')
        self.assertEqual(database_sla['downtime_minutes'], 0)
        self.assertEqual(payload['alerts']['critical'], 1)


class MockHttpResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = str(payload)

    def json(self):
        return self.payload


class ClickHouseLogMigrationTests(TestCase):
    def test_legacy_container_logs_upgrade_does_not_duplicate_default_collection(self):
        migration = importlib.import_module('ops.migrations.0064_clickhouse_collections')

        class FakeDataSource:
            def __init__(self):
                self.config = {
                    'endpoint': 'http://10.132.46.52:30812',
                    'database': 'container_logs',
                    'table': 'logs',
                    'time_field': 'timestamp',
                    'message_fields': 'message,log_message',
                    'level_field': 'log_level',
                    'source_fields': 'namespace,pod_name,container_name',
                    'search_fields': 'namespace,pod_name,node_name,container_name,log_level,message,log_message,source,log_file_path',
                }
                self.saved_fields = None

            def save(self, update_fields=None):
                self.saved_fields = update_fields

        datasource = FakeDataSource()

        class FakeManager:
            def filter(self, **kwargs):
                self.filter_kwargs = kwargs
                return [datasource]

        class FakeLogDataSource:
            objects = FakeManager()

        apps = SimpleNamespace(get_model=lambda app_label, model_name: FakeLogDataSource)

        migration.upgrade_clickhouse_datasources(apps, None)

        collections = datasource.config['collections']
        self.assertEqual([item['key'] for item in collections], ['container-logs', 'k8s-events', 'ingress-access'])
        self.assertEqual(
            [(item['database'], item['table']) for item in collections],
            [('container_logs', 'logs'), ('container_logs', 'events'), ('nginxlogs', 'nginx_access')],
        )
        self.assertNotIn('database', datasource.config)
        self.assertNotIn('table', datasource.config)
        self.assertEqual(datasource.saved_fields, ['config', 'updated_at'])


@override_settings(LOG_PROVIDER_CONFIGS=TEST_LOG_PROVIDER_CONFIGS)
class LogViewsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('ops-admin', 'ops@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)

    def test_log_providers_returns_loki_elk_and_clickhouse(self):
        response = self.client.get('/api/log/providers/')

        self.assertEqual(response.status_code, 200)
        providers = response.json()['providers']
        self.assertEqual([item['id'] for item in providers], ['loki', 'elk', 'clickhouse'])
        self.assertEqual(providers[0]['defaults']['endpoint'], 'http://loki.example:3100')
        self.assertEqual(providers[2]['defaults']['endpoint'], 'http://clickhouse.example:8123')
        self.assertNotIn('table', providers[2]['defaults'])

    def test_can_create_log_datasource(self):
        response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'Production Loki',
                'provider': 'loki',
                'description': 'Production application logs',
                'is_enabled': True,
                'is_default': True,
                'config': {'endpoint': 'http://loki.internal:3100'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['name'], 'Production Loki')
        self.assertEqual(payload['config']['endpoint'], 'http://loki.internal:3100')

    def test_can_create_clickhouse_log_datasource_connection_only(self):
        response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'Oncall ClickHouse',
                'provider': 'clickhouse',
                'description': 'Ingress access logs stored in ClickHouse',
                'is_enabled': True,
                'is_default': True,
                'config': {
                    'endpoint': 'http://10.132.46.52:30812',
                    'username': 'xinghai',
                    'password': 'Aws_kkk',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['provider'], 'clickhouse')
        self.assertEqual(payload['config']['endpoint'], 'http://10.132.46.52:30812')
        self.assertNotIn('table', payload['config'])

    @patch('ops.log_views.http_requests.request')
    def test_clickhouse_catalog_lists_tables(self, mock_request):
        mock_request.return_value = MockHttpResponse({'data': [{'name': 'nginx_access'}]})

        response = self.client.post(
            '/api/log/providers/clickhouse/catalog/',
            {
                'config': {
                    'endpoint': 'http://clickhouse.example:8123',
                    'username': 'xinghai',
                    'password': 'Aws_kkk',
                    'database': 'nginxlogs',
                },
                'action': 'tables',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['kind'], 'tables')
        self.assertEqual(payload['items'][0]['name'], 'nginx_access')
        self.assertIn('SHOW TABLES FROM `nginxlogs`', mock_request.call_args.kwargs['data'])

    @patch('ops.log_views.http_requests.request')
    def test_clickhouse_catalog_recommends_collection_fields(self, mock_request):
        mock_request.return_value = MockHttpResponse({
            'data': [
                {'name': 'timestamp', 'type': "DateTime64(3, 'Asia/Shanghai')"},
                {'name': 'namespace', 'type': 'String'},
                {'name': 'pod_name', 'type': 'String'},
                {'name': 'container_name', 'type': 'String'},
                {'name': 'log_level', 'type': 'String'},
                {'name': 'message', 'type': 'String'},
                {'name': 'log_message', 'type': 'String'},
                {'name': 'createdtime', 'type': "DateTime64(3, 'Asia/Shanghai')"},
            ],
        })

        response = self.client.post(
            '/api/log/providers/clickhouse/catalog/',
            {
                'config': {
                    'endpoint': 'http://clickhouse.example:8123',
                    'username': 'xinghai',
                    'password': 'Aws_kkk',
                },
                'action': 'recommend_fields',
                'database': 'container_logs',
                'table': 'logs',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['kind'], 'field_recommendation')
        self.assertEqual(payload['recommendation']['time_field'], 'timestamp')
        self.assertEqual(payload['recommendation']['message_fields'], 'message,log_message')
        self.assertEqual(payload['recommendation']['level_field'], 'log_level')
        self.assertIn('namespace', payload['recommendation']['search_fields'])

    @patch('ops.log_views.http_requests.request')
    def test_clickhouse_query_uses_named_collection(self, mock_request):
        datasource = LogDataSource.objects.create(
            name='K8S ClickHouse',
            provider='clickhouse',
            config={
                'endpoint': 'http://clickhouse.example:8123',
                'username': 'xinghai',
                'password': 'Aws_kkk',
                'collections': [
                    {
                        'key': 'container-logs',
                        'name': 'K8S Container Logs',
                        'database': 'container_logs',
                        'table': 'logs',
                        'time_field': 'timestamp',
                        'message_fields': 'message,log_message',
                        'level_field': 'log_level',
                        'source_fields': 'namespace,pod_name,container_name',
                        'search_fields': 'namespace,pod_name,node_name,container_name,log_level,message,log_message,source,log_file_path',
                    }
                ],
            },
        )
        mock_request.return_value = MockHttpResponse({
            'statistics': {'elapsed': 0.004},
            'rows_before_limit_at_least': 1,
            'data': [
                {
                    'timestamp': '2026-07-08 10:01:02.123',
                    'namespace': 'monitoring',
                    'pod_name': 'prometheus-k8s-0',
                    'container_name': 'prometheus',
                    'log_level': 'WARN',
                    'message': 'failed to list endpoints',
                    'log_message': 'failed to list endpoints',
                    'source': 'kubernetes_logs',
                }
            ],
        })

        response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': datasource.id,
                'collection': 'container-logs',
                'query': 'endpoints',
                'start_ms': '1783495200000',
                'end_ms': '1783498800000',
                'limit': 50,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['provider'], 'clickhouse')
        self.assertEqual(payload['source'], 'container_logs.logs')
        self.assertEqual(payload['collection'], 'container-logs')
        self.assertEqual(payload['logs'][0]['source'], 'monitoring/prometheus-k8s-0/prometheus')
        self.assertEqual(payload['logs'][0]['level'], 'warning')
        self.assertEqual(payload['logs'][0]['message'], 'failed to list endpoints')
        self.assertIn('FROM `container_logs`.`logs`', mock_request.call_args.kwargs['data'])
        self.assertIn('`message`', mock_request.call_args.kwargs['data'])

    @patch('ops.log_views.http_requests.request')
    def test_clickhouse_query_normalizes_nginx_access_rows(self, mock_request):
        mock_request.return_value = MockHttpResponse({
            'statistics': {'elapsed': 0.012},
            'rows_before_limit_at_least': 1,
            'data': [
                {
                    'timestamp': '2026-07-08 10:01:02.123',
                    'server_ip': '10.132.46.52',
                    'domain': 'xinghai.example.com',
                    'request_method': 'GET',
                    'status': 500,
                    'path': '/api/orders',
                    'query': 'id=1001',
                    'protocol': 'HTTP/1.1',
                    'responsetime': 0.234,
                    'duration': 0.235,
                    'client_ip': '192.168.10.8',
                    'http_user_agent': 'curl/8.0',
                }
            ],
        })

        response = self.client.post(
            '/api/log/query/',
            {
                'provider': 'clickhouse',
                'query': 'orders',
                'source': 'nginx_access',
                'database': 'nginxlogs',
                'start_ms': '1783495200000',
                'end_ms': '1783498800000',
                'limit': 50,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['provider'], 'clickhouse')
        self.assertEqual(payload['source'], 'nginxlogs.nginx_access')
        self.assertEqual(payload['total'], 1)
        self.assertEqual(payload['logs'][0]['source'], 'xinghai.example.com')
        self.assertEqual(payload['logs'][0]['level'], 'error')
        self.assertIn('GET', payload['logs'][0]['message'])
        self.assertIn('/api/orders', payload['logs'][0]['message'])
        self.assertIn('500', payload['logs'][0]['message'])

    @patch('ops.log_views.http_requests.get')
    def test_datasource_test_connection_uses_saved_config(self, mock_get):
        create_response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'Loki Test Source',
                'provider': 'loki',
                'config': {'endpoint': 'http://saved-loki:3100'},
            },
            format='json',
        )
        datasource_id = create_response.json()['id']

        mock_get.return_value = MockHttpResponse({'data': ['job', 'namespace']})

        response = self.client.post(f'/api/log/datasources/{datasource_id}/test_connection/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['preview_kind'], 'labels')
        mock_get.assert_called_once()

    @patch('ops.log_views.http_requests.get')
    def test_loki_query_normalizes_response(self, mock_get):
        mock_get.return_value = MockHttpResponse(
            {
                'data': {
                    'result': [
                        {
                            'stream': {'job': 'gateway', 'level': 'error'},
                            'values': [
                                ['1710000000000000000', 'request timeout'],
                                ['1710000001000000000', 'handled request'],
                            ],
                        }
                    ]
                }
            }
        )

        response = self.client.post(
            '/api/log/query/',
            {
                'provider': 'loki',
                'query': '{job="gateway"}',
                'start_ms': '1710000000000',
                'end_ms': '1710003600000',
                'limit': 100,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['provider'], 'loki')
        self.assertEqual(payload['total'], 2)
        self.assertEqual(payload['logs'][0]['source'], 'gateway')
        self.assertEqual(payload['logs'][0]['level'], 'error')
        self.assertTrue(payload['logs'][0]['timestamp'].endswith('Z'))
        mock_get.assert_called_once()

    @patch('ops.log_views.http_requests.get')
    def test_loki_query_can_use_saved_datasource(self, mock_get):
        create_response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'Saved Loki',
                'provider': 'loki',
                'config': {'endpoint': 'http://saved-loki:3100'},
            },
            format='json',
        )
        datasource_id = create_response.json()['id']
        mock_get.return_value = MockHttpResponse(
            {
                'data': {
                    'result': [
                        {
                            'stream': {'job': 'api'},
                            'values': [['1710000000000000000', 'api started']],
                        }
                    ]
                }
            }
        )

        response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': datasource_id,
                'query': '{job="api"}',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['logs'][0]['source'], 'api')

    def test_demo_loki_catalog_and_query_return_fake_logs(self):
        response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'Loki Demo CN',
                'provider': 'loki',
                'config': {
                    'endpoint': 'http://demo-loki.example.com:3100',
                    'demo_mode': True,
                },
            },
            format='json',
        )
        datasource_id = response.json()['id']

        catalog_response = self.client.post(
            '/api/log/providers/loki/catalog/',
            {
                'datasource_id': datasource_id,
                'action': 'labels',
            },
            format='json',
        )
        self.assertEqual(catalog_response.status_code, 200)
        self.assertIn('job', catalog_response.json()['items'])

        query_response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': datasource_id,
                'query': '{job="gateway-service"} |= "timeout"',
                'limit': 50,
            },
            format='json',
        )

        self.assertEqual(query_response.status_code, 200)
        payload = query_response.json()
        self.assertEqual(payload['provider'], 'loki')
        self.assertGreaterEqual(payload['total'], 1)
        self.assertEqual(payload['logs'][0]['source'], 'gateway-service')
        self.assertIn('timeout', payload['logs'][0]['message'])
        self.assertIn('trace_id', payload['logs'][0]['attributes'])

        label_values_response = self.client.post(
            '/api/log/providers/loki/catalog/',
            {
                'datasource_id': datasource_id,
                'action': 'label_values',
                'label': 'release',
            },
            format='json',
        )
        self.assertEqual(label_values_response.status_code, 200)
        self.assertIn('gray', label_values_response.json()['items'])

    def test_demo_loki_supports_stacktrace_and_gray_release_queries(self):
        response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'Loki Demo Spring Cloud',
                'provider': 'loki',
                'config': {
                    'endpoint': 'http://demo-loki.example.com:3100',
                    'demo_mode': True,
                },
            },
            format='json',
        )

        stack_response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': response.json()['id'],
                'query': '{job="quality-service"} |= "NullPointerException"',
                'limit': 20,
            },
            format='json',
        )
        self.assertEqual(stack_response.status_code, 200)
        self.assertGreaterEqual(stack_response.json()['total'], 1)
        self.assertIn('PaymentCallbackController', stack_response.json()['logs'][0]['message'])

        gray_response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': response.json()['id'],
                'query': '{release="gray"} |= "tenantId"',
                'limit': 20,
            },
            format='json',
        )
        self.assertEqual(gray_response.status_code, 200)
        self.assertGreaterEqual(gray_response.json()['total'], 1)
        self.assertEqual(gray_response.json()['logs'][0]['attributes']['release'], 'gray')

    @patch('ops.log_views.http_requests.request')
    def test_elk_catalog_lists_indices(self, mock_request):
        mock_request.return_value = MockHttpResponse(
            [
                {'index': 'logs-prod-2026.03.15', 'docs.count': '12', 'store.size': '48kb'},
                {'index': 'logs-stage-2026.03.15', 'docs.count': '6', 'store.size': '18kb'},
            ]
        )

        response = self.client.post(
            '/api/log/providers/elk/catalog/',
            {
                'config': {'endpoint': 'https://es.example.com:9200'},
                'index_pattern': 'logs-*',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['kind'], 'indices')
        self.assertEqual(payload['items'][0]['name'], 'logs-prod-2026.03.15')
        self.assertEqual(payload['items'][1]['docs_count'], '6')

    @patch('ops.log_views.http_requests.request')
    def test_elk_catalog_recommends_kubernetes_field_map_from_sample(self, mock_request):
        mock_request.return_value = MockHttpResponse({
            'hits': {'hits': [{'_source': {
                '@timestamp': '2026-07-20T00:00:00Z', 'message': 'container started', 'log': {'level': 'INFO'},
                'kubernetes': {
                    'namespace_name': 'xing-cloud', 'pod_name': 'api-7d5f', 'container_name': 'api',
                    'node_name': 'k8s-master', 'labels': {'app': 'xing-cloud'},
                },
            }}]},
        })

        response = self.client.post(
            '/api/log/providers/elk/catalog/',
            {'config': {'endpoint': 'https://es.example.com:9200'}, 'action': 'recommend_fields', 'index_pattern': 'k8s-*'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        recommendation = response.json()['recommendation']
        self.assertEqual(recommendation['timestamp'], '@timestamp')
        self.assertEqual(recommendation['namespace'], 'kubernetes.namespace_name')
        self.assertEqual(recommendation['pod'], 'kubernetes.pod_name')
        self.assertEqual(recommendation['service'], 'kubernetes.labels.app')

    @patch('ops.log_views.http_requests.request')
    def test_elk_query_accepts_iso_timestamps(self, mock_request):
        mock_request.return_value = MockHttpResponse(
            {
                'took': 21,
                'hits': {
                    'total': {'value': 1},
                    'hits': [
                        {
                            '_index': 'logs-prod-2026.03.15',
                            '_source': {
                                '@timestamp': '2026-03-15T08:30:00Z',
                                'message': 'quality error in workorder',
                                'level': 'ERROR',
                                'service': {'name': 'quality'},
                            },
                        }
                    ],
                },
            }
        )

        response = self.client.post(
            '/api/log/query/',
            {
                'provider': 'elk',
                'query': 'service.name:"quality"',
                'source': 'logs-prod-*',
                'start_ms': '1710000000000',
                'end_ms': '1710003600000',
                'limit': 50,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['provider'], 'elk')
        self.assertEqual(payload['took_ms'], 21)
        self.assertEqual(payload['logs'][0]['timestamp'], '2026-03-15T08:30:00Z')
        self.assertEqual(payload['logs'][0]['level'], 'error')
        self.assertEqual(payload['logs'][0]['source'], 'quality')
        self.assertEqual(payload['logs'][0]['service'], 'quality')

    def test_demo_elk_query_returns_fake_logs_without_network(self):
        response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'ELK Demo CN',
                'provider': 'elk',
                'config': {
                    'endpoint': 'https://demo-elastic.example.com:9200',
                    'index_pattern': 'logs-demo-*',
                    'time_field': '@timestamp',
                    'message_fields': 'message,log,msg',
                    'demo_mode': True,
                    'demo_indices': ['logs-demo-app-2026.03.15', 'logs-demo-security-2026.03.15'],
                },
            },
            format='json',
        )
        datasource_id = response.json()['id']

        query_response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': datasource_id,
                'query': 'quality error',
                'source': 'logs-demo-*',
            },
            format='json',
        )

        self.assertEqual(query_response.status_code, 200)
        payload = query_response.json()
        self.assertEqual(payload['provider'], 'elk')
        self.assertGreaterEqual(payload['total'], 1)
        self.assertIn('quality', payload['logs'][0]['message'])
        self.assertIn('trace_id', payload['logs'][0]['attributes'])
        self.assertIn('com.xing-cloud', payload['logs'][0]['message'])

    def test_demo_elk_query_honors_high_limit_when_matches_are_available(self):
        response = self.client.post(
            '/api/log/datasources/',
            {
                'name': 'ELK Demo Large',
                'provider': 'elk',
                'config': {
                    'endpoint': 'https://demo-elastic.example.com:9200',
                    'index_pattern': 'logs-demo-*',
                    'demo_mode': True,
                },
            },
            format='json',
        )

        query_response = self.client.post(
            '/api/log/query/',
            {
                'datasource_id': response.json()['id'],
                'query': '',
                'source': 'logs-demo-*',
                'limit': 200,
            },
            format='json',
        )

        self.assertEqual(query_response.status_code, 200)
        payload = query_response.json()
        self.assertGreaterEqual(payload['total'], 200)
        self.assertEqual(len(payload['logs']), 200)


@override_settings(LOG_PROVIDER_CONFIGS=TEST_LOG_PROVIDER_CONFIGS, OBSERVABILITY_CONFIG=TEST_OBSERVABILITY_CONFIG)
class ObservabilityViewsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('observer-admin', 'observer@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)

    def test_tracing_runtime_routes_are_removed(self):
        removed_routes = [
            ('get', '/api/observability/tracing/providers/'),
            ('get', '/api/observability/tracing/catalog/'),
            ('post', '/api/observability/tracing/search/'),
            ('get', '/api/observability/tracing/traces/demo-trace-id/'),
            ('get', '/api/observability/tracing/datasources/'),
            ('post', '/api/observability/tracing/datasources/'),
            ('get', '/api/observability/datasource-links/'),
            ('post', '/api/observability/datasource-links/resolve_trace_to_logs/'),
            ('post', '/api/observability/datasource-links/resolve_log_to_trace/'),
        ]

        for method, route in removed_routes:
            response = getattr(self.client, method)(route, {}, format='json')
            self.assertEqual(response.status_code, 404, route)

    def test_observability_overview_has_no_tracing_payload(self):
        response = self.client.get('/api/observability/overview/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('tracing', payload['modules'])
        self.assertNotIn('recent_traces', payload)
        self.assertNotIn('providers', payload)
        self.assertFalse(any('/tracing' in item['path'] for item in payload['navigation']))

    def test_observability_overview_reports_datasource_health(self):
        checked_at = timezone.now() - timedelta(minutes=2)
        MetricDataSource.objects.create(
            name='Healthy Prometheus',
            environment='prod',
            is_default=True,
            config={'query_url': 'http://prometheus.prod.local:9090'},
            last_check_at=checked_at,
            last_check_status='ok',
            last_check_message='up query returned samples',
            last_check_latency_ms=21,
        )
        LogDataSource.objects.create(
            name='Missing Test Logs',
            provider='clickhouse',
            is_enabled=False,
            config={},
            last_check_status='not_configured',
            last_check_message='test environment logs are not connected',
        )

        response = self.client.get('/api/observability/overview/')

        self.assertEqual(response.status_code, 200)
        health = response.json()['datasource_health']
        self.assertEqual(health['summary']['ok'], 1)
        self.assertEqual(health['summary']['not_configured'], 1)
        metric_health = next(item for item in health['metrics'] if item['name'] == 'Healthy Prometheus')
        log_health = next(item for item in health['logs'] if item['name'] == 'Missing Test Logs')
        self.assertEqual(metric_health['last_check_status'], 'ok')
        self.assertEqual(metric_health['last_check_latency_ms'], 21)
        self.assertEqual(log_health['last_check_status'], 'not_configured')
        self.assertIn('not connected', log_health['last_check_message'])

    @patch('ops.log_views._elk_request')
    def test_elasticsearch_datasource_health_check_uses_cluster_health(self, mock_request):
        datasource = LogDataSource.objects.create(
            name='Healthy Elasticsearch',
            provider='elk',
            config={'endpoint': 'https://es.example.com:9200', 'index_pattern': 'k8s-*'},
        )
        mock_request.return_value = {'status': 'yellow', 'cluster_name': 'logs'}

        checked = check_log_datasource(datasource)

        self.assertEqual(checked.last_check_status, 'ok')
        self.assertIn('yellow', checked.last_check_message)
        mock_request.assert_called_once_with(
            'GET', 'https://es.example.com:9200', '/_cluster/health',
            {'endpoint': 'https://es.example.com:9200', 'auth_type': 'none', 'index_pattern': 'k8s-*',
             'time_field': '@timestamp', 'message_fields': 'message,log,msg'},
        )

    def test_sla_summary_api_uses_disaster_alert_duration(self):
        now = timezone.now()
        alert = Alert.objects.create(
            title='database p0 unavailable',
            level='critical',
            status=Alert.STATUS_RESOLVED,
            source='prometheus',
            source_type=Alert.SOURCE_PLATFORM,
            message='mysql disaster outage',
            resource_type='database',
            service='mysql',
            labels={'severity': 'disaster', 'product': 'database'},
            starts_at=now - timedelta(minutes=45),
            ends_at=now - timedelta(minutes=15),
            last_received_at=now,
        )
        Alert.objects.filter(pk=alert.pk).update(created_at=now - timedelta(minutes=45), updated_at=now - timedelta(minutes=15))

        response = self.client.get('/api/observability/sla/summary/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['target'], 99.96)
        self.assertGreater(payload['month_downtime_minutes'], 0)
        self.assertTrue(any(item['key'] == 'database' for item in payload['product_slas']))
        self.assertEqual(payload['disaster_events'][0]['id'], alert.id)

    def test_datasource_link_grafana_routes_are_removed(self):
        removed_routes = [
            '/api/observability/datasource-links/resolve_trace_to_grafana/',
            '/api/observability/datasource-links/resolve_log_to_grafana/',
            '/api/observability/datasource-links/resolve_grafana_to_logs/',
            '/api/observability/datasource-links/resolve_grafana_to_trace/',
        ]

        for route in removed_routes:
            response = self.client.post(route, {}, format='json')
            self.assertEqual(response.status_code, 404, route)

    @patch('ops.observability_views.user_has_permissions')
    def test_observability_overview_allows_log_only_user_without_trace_visibility(self, mock_permissions):
        existing_payload = self.client.get('/api/log/datasources/').json()
        existing_count = existing_payload.get('count', 0) if isinstance(existing_payload, dict) else len(existing_payload)
        self.client.post(
            '/api/log/datasources/',
            {
                'name': 'Overview Loki',
                'provider': 'loki',
                'config': {'endpoint': 'http://overview-loki:3100'},
            },
            format='json',
        )
        limited_user = get_user_model().objects.create_user('log-viewer', password='Admin@123456')
        self.client.force_authenticate(user=limited_user)

        def permission_side_effect(user, codes):
            code = codes[0] if codes else ''
            return code == 'ops.log.datasource.view'

        mock_permissions.side_effect = permission_side_effect

        response = self.client.get('/api/observability/overview/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('tracing', payload['modules'])
        self.assertIsNone(payload['modules']['dashboards'])
        self.assertEqual(payload['modules']['logs']['datasource_count'], existing_count + 1)
        self.assertEqual(len(payload['navigation']), 1)
        self.assertEqual(payload['navigation'][0]['path'], '/logs/query')

    def test_observability_overview_ignores_grafana_config_for_native_dashboards(self):
        from ops.dashboard_presets import ensure_builtin_dashboards

        ensure_builtin_dashboards()
        with override_settings(
            OBSERVABILITY_CONFIG={
                **TEST_OBSERVABILITY_CONFIG,
                'grafana': {
                    'enabled': True,
                    'url': 'http://grafana.example.com',
                    'default_path': '',
                    'demo_mode': True,
                    'dashboards': [{'key': 'custom-trace', 'title': '鑷畾涔夐摼璺€昏'}],
                },
            }
        ):
            response = self.client.get('/api/observability/overview/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('grafana', payload['modules'])
        dashboard_titles = [item['title'] for item in payload['modules']['dashboards']['dashboards']]
        self.assertIn('K8S Cluster Health', dashboard_titles)
        self.assertIn('Linux Server Resources', dashboard_titles)
        self.assertIn('ClickHouse Container Logs', dashboard_titles)
        self.assertNotIn('自定义链路总览', dashboard_titles)

    def test_observability_grafana_routes_are_removed(self):
        routes = [
            ('get', '/api/observability/grafana/config/'),
            ('put', '/api/observability/grafana/config/'),
            ('post', '/api/observability/grafana/promql/query/'),
            ('post', '/api/observability/grafana/panel/query/'),
        ]

        for method, route in routes:
            response = getattr(self.client, method)(route, {}, format='json')
            self.assertEqual(response.status_code, 404, route)

    def test_grafana_setting_model_is_removed(self):
        from ops import models as ops_models

        self.assertFalse(hasattr(ops_models, 'GrafanaSetting'))

    def test_promql_query_api_has_no_grafana_parameters(self):
        import inspect
        from ops.observability_views import execute_promql_query

        parameter_names = set(inspect.signature(execute_promql_query).parameters)

        self.assertFalse({'datasource_uid', 'datasource_id', 'grafana_url'} & parameter_names)

    @patch('ops.observability_views.http_requests.get')
    def test_metrics_query_uses_metric_datasource(self, mock_get):
        datasource = MetricDataSource.objects.create(
            name='Retail Test Prometheus',
            environment='test',
            is_default=True,
            config={
                'query_url': 'http://prometheus.test.local:9090',
                'auth_type': 'bearer',
                'bearer_token': 'secret-token',
                'headers': {'X-Scope-OrgID': 'retail'},
            },
        )
        mock_get.return_value = MockHttpResponse({
            'status': 'success',
            'data': {
                'resultType': 'vector',
                'result': [{'metric': {'job': 'api'}, 'value': [1710000000, '1']}],
            },
        })

        response = self.client.post(
            '/api/observability/metrics/query/',
            {'query': 'up', 'metric_datasource_id': datasource.id},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['source'], 'metric_datasource')
        self.assertEqual(payload['metric_datasource']['id'], datasource.id)
        self.assertIn('/api/v1/query', mock_get.call_args.args[0])
        self.assertEqual(mock_get.call_args.kwargs['headers']['Authorization'], 'Bearer secret-token')

    @patch('ops.observability_views.http_requests.get')
    def test_metrics_series_names_uses_prometheus_label_values(self, mock_get):
        datasource = MetricDataSource.objects.create(
            name='Retail Metrics',
            environment='test',
            is_default=True,
            config={
                'query_url': 'http://prometheus.test.local:9090',
                'headers': {'X-Scope-OrgID': 'retail'},
            },
        )
        mock_get.return_value = MockHttpResponse({
            'status': 'success',
            'data': [
                'http_requests_total',
                'node_cpu_seconds_total',
                'node_memory_MemAvailable_bytes',
                'process_cpu_seconds_total',
            ],
        })

        response = self.client.get(
            '/api/observability/metrics/series-names/',
            {'metric_datasource_id': datasource.id, 'q': 'node_', 'limit': 5},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['metrics'], ['node_cpu_seconds_total', 'node_memory_MemAvailable_bytes'])
        self.assertEqual(payload['metric_datasource']['id'], datasource.id)
        self.assertIn('/api/v1/label/__name__/values', mock_get.call_args.args[0])
        self.assertEqual(mock_get.call_args.kwargs['headers']['X-Scope-OrgID'], 'retail')
        self.assertEqual(mock_get.call_args.kwargs['params']['match[]'], '{__name__=~".*node_.*"}')

    def test_old_native_dashboard_query_endpoint_is_removed(self):
        response = self.client.post('/api/observability/dashboards/query/', {'dashboard': 'kubernetes'}, format='json')

        self.assertEqual(response.status_code, 404)

    def test_observability_integrations_returns_catalog_and_status(self):
        from ops.alert_rule_presets import ensure_builtin_alert_rule_templates
        from ops.dashboard_presets import ensure_builtin_dashboards

        ensure_builtin_dashboards()
        ensure_builtin_alert_rule_templates()
        MetricDataSource.objects.create(
            name='Default Prometheus',
            provider='prometheus',
            config={'query_url': 'http://prometheus.local:9090'},
            is_default=True,
            is_enabled=True,
            last_check_status='ok',
        )

        response = self.client.get('/api/observability/integrations/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        keys = [item['key'] for item in payload['integrations']]
        self.assertIn('mysql', keys)
        self.assertIn('redis', keys)
        self.assertIn('kafka', keys)
        mysql = next(item for item in payload['integrations'] if item['key'] == 'mysql')
        self.assertEqual(mysql['brand'], 'Xing-Cloud')
        self.assertEqual(mysql['source_types'], ['prometheus'])
        self.assertIn(mysql['status'], ['source_available', 'rules_installed', 'dashboards_installed'])
        self.assertGreaterEqual(mysql['template_count'], 1)
        self.assertGreaterEqual(mysql['dashboard_count'], 1)

    def test_install_integration_rules_creates_rules_from_builtin_templates(self):
        datasource = MetricDataSource.objects.create(
            name='Redis Prometheus',
            provider='prometheus',
            config={'query_url': 'http://prometheus.local:9090'},
            is_enabled=True,
        )
        response = self.client.post(
            '/api/observability/integrations/redis/install-rules/',
            {
                'template_codes': ['redis-down', 'redis-high-memory'],
                'metric_datasource_id': datasource.id,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['created_count'], 2)
        self.assertEqual(payload['skipped_count'], 0)
        self.assertTrue(AlertRule.objects.filter(template__code='redis-down').exists())
        self.assertTrue(AlertRule.objects.filter(code='redis-down', is_template=True).exists())

    def test_integration_dashboard_install_enables_builtin_json_dashboard(self):
        response = self.client.post('/api/observability/integrations/redis/install-dashboards/', {}, format='json')

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['integration'], 'redis')
        self.assertGreaterEqual(payload['enabled_count'], 1)
        self.assertTrue(ObservabilityDashboard.objects.filter(title='Redis Overview', is_builtin=True, is_enabled=True).exists())

    def test_observability_overview_dashboard_summary_uses_json_definitions(self):
        from ops.dashboard_presets import ensure_builtin_dashboards

        ensure_builtin_dashboards()
        response = self.client.get('/api/observability/overview/')

        self.assertEqual(response.status_code, 200)
        dashboards = response.json()['modules']['dashboards']
        self.assertEqual(dashboards['source'], 'json')
        self.assertIn('Redis Overview', [item['title'] for item in dashboards['dashboards']])

    def test_dashboard_read_endpoints_do_not_seed_presets(self):
        ObservabilityDashboard.objects.all().delete()

        list_response = self.client.get('/api/observability/dashboard-definitions/')
        overview_response = self.client.get('/api/observability/overview/')

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(overview_response.status_code, 200)
        self.assertEqual(ObservabilityDashboard.objects.count(), 0)

    def test_seed_observability_presets_command_initializes_catalog(self):
        from django.core.management import call_command

        ObservabilityDashboard.objects.all().delete()
        AlertRule.objects.filter(is_template=True).delete()

        call_command('seed_observability_presets')

        self.assertTrue(ObservabilityDashboard.objects.filter(is_builtin=True).exists())
        self.assertTrue(AlertRule.objects.filter(is_template=True).exists())

    def test_builtin_dashboards_update_log_and_k8s_panels(self):
        from ops.dashboard_presets import ensure_builtin_dashboards

        dashboard = ObservabilityDashboard.objects.create(
            title='ClickHouse Container Logs',
            description='old',
            tags=['old'],
            is_builtin=True,
        )
        ObservabilityDashboardPanel.objects.create(
            dashboard=dashboard,
            key='container-error-total',
            title='Old Error Count',
            chart_type='stat',
            datasource_type='clickhouse',
            targets=[{'collection': 'container-logs', 'sql': 'SELECT 1 AS value'}],
            sort_order=1,
        )

        ensure_builtin_dashboards()

        dashboard.refresh_from_db()
        error_panel = dashboard.panels.get(key='container-error-total')
        ingress_dashboard = ObservabilityDashboard.objects.get(title='Ingress Access Logs')
        k8s_dashboard = ObservabilityDashboard.objects.get(title='K8S Cluster Health')

        self.assertIn('container', dashboard.tags)
        self.assertIn("upper(toString(log_level)) IN ('ERROR','FATAL','CRITICAL')", error_panel.targets[0]['sql'])
        self.assertTrue(ingress_dashboard.panels.filter(key='ingress-5xx-path-top').exists())
        self.assertTrue(k8s_dashboard.panels.filter(key='k8s-pod-restart-top').exists())

    @patch('ops.views.evaluate_rule')
    def test_alert_rule_dry_run_draft_creates_unsaved_preview_rule(self, mock_evaluate):
        mock_evaluate.return_value = {'success': True, 'matched_count': 1, 'would_fire_count': 1, 'dry_run': True}
        datasource = MetricDataSource.objects.create(
            name='Draft Prometheus',
            provider='prometheus',
            config={'query_url': 'http://prometheus.local:9090'},
            is_enabled=True,
        )
        response = self.client.post(
            '/api/alert-rules/dry-run-draft/',
            {
                'name': 'Draft Redis Down',
                'source_type': 'prometheus',
                'metric_datasource': datasource.id,
                'level': 'critical',
                'query_config': {'query': 'redis_up == 0'},
                'condition': {'operator': '>', 'threshold': 0},
                'labels': {'integration': 'redis'},
                'annotations': {},
                'interval_seconds': 60,
                'duration_seconds': 60,
                'notify_enabled': True,
                'auto_analyze': False,
                'is_enabled': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['would_fire_count'], 1)
        self.assertFalse(AlertRule.objects.filter(name='Draft Redis Down').exists())

    def test_metric_datasource_serializer_masks_secrets(self):
        datasource = MetricDataSource.objects.create(
            name='Secure Prometheus',
            config={
                'query_url': 'http://prometheus.local:9090',
                'password': 'secret',
                'bearer_token': 'token',
                'headers': {'Authorization': 'Bearer token', 'X-Team': 'ops'},
                'prometheus.basic': {'prometheus.user': 'admin', 'prometheus.password': 'secret'},
            },
        )

        response = self.client.get(f'/api/observability/metric/datasources/{datasource.id}/')

        self.assertEqual(response.status_code, 200)
        config = response.json()['config']
        self.assertEqual(config['password'], 'configured')
        self.assertEqual(config['bearer_token'], 'configured')
        self.assertEqual(config['headers']['Authorization'], 'configured')
        self.assertEqual(config['headers']['X-Team'], 'ops')
        self.assertEqual(config['prometheus.basic']['prometheus.password'], 'configured')

    @patch('ops.observability_views.execute_promql_query')
    def test_dashboard_definition_crud_export_and_query(self, mock_promql):
        from ops.models import ObservabilityDashboard

        mock_promql.return_value = {
            'result': [{'metric': {'instance': 'server-01'}, 'value': [1710000000, '3']}],
        }
        create_response = self.client.post(
            '/api/observability/dashboard-definitions/',
            {
                'title': 'Custom Server Health',
                'description': 'JSON driven dashboard',
                'tags': ['server'],
                'layout': {'columns': 12},
                'is_builtin': False,
                'is_enabled': True,
                'panels': [
                    {
                        'title': 'Node count',
                        'key': 'node-count',
                        'chart_type': 'stat',
                        'datasource_type': 'prometheus',
                        'targets': [{'query': 'up'}],
                        'options': {'unit': 'nodes'},
                        'sort_order': 1,
                    }
                ],
            },
            format='json',
        )

        self.assertEqual(create_response.status_code, 201)
        dashboard_id = create_response.json()['id']
        self.assertTrue(ObservabilityDashboard.objects.filter(pk=dashboard_id).exists())

        query_response = self.client.post(
            f'/api/observability/dashboard-definitions/{dashboard_id}/query/',
            {'step': 60},
            format='json',
        )
        self.assertEqual(query_response.status_code, 200)
        payload = query_response.json()
        self.assertEqual(payload['dashboard']['id'], dashboard_id)
        self.assertEqual(payload['panels'][0]['key'], 'node-count')
        self.assertEqual(payload['panels'][0]['data']['value'], 3)

        export_response = self.client.get(f'/api/observability/dashboard-definitions/{dashboard_id}/export/')
        self.assertEqual(export_response.status_code, 200)
        exported = export_response.json()
        self.assertEqual(exported['title'], 'Custom Server Health')
        self.assertEqual(exported['panels'][0]['targets'][0]['query'], 'up')

    def test_sls_catalog_is_not_supported(self):
        response = self.client.post(
            '/api/log/providers/sls/catalog/',
            {'provider': 'sls'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Unsupported log provider')

    def test_sls_datasource_creation_is_rejected(self):
        response = self.client.post(
            '/api/log/datasources/',
            {'name': 'Legacy SLS', 'provider': 'sls', 'config': {}},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('provider', response.json())

    def test_sls_query_is_not_supported(self):
        query_response = self.client.post(
            '/api/log/query/',
            {
                'provider': 'sls',
                'query': '*',
            },
            format='json',
        )

        self.assertEqual(query_response.status_code, 400)
        self.assertEqual(query_response.json()['error'], 'Unsupported log provider')


class ContainerManagementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('container-admin', 'container@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)
        cache.clear()

    def test_k8s_api_proxy_preserves_bound_method_owner_for_stream(self):
        class FakeApi:
            def __init__(self):
                self.api_client = object()
                self.kwargs = None

            def connect_get_namespaced_pod_exec(self, **kwargs):
                self.kwargs = kwargs
                return 'connected'

        fake_api = FakeApi()
        proxy = _K8sApiProxy(fake_api)
        wrapped = proxy.connect_get_namespaced_pod_exec

        self.assertIs(wrapped.__self__, fake_api)
        self.assertIs(wrapped.__self__.api_client, fake_api.api_client)
        self.assertEqual(wrapped(name='pod-a'), 'connected')
        self.assertEqual(fake_api.kwargs['_request_timeout'], (1.5, 3))

    def test_prepare_kubeconfig_overrides_active_cluster_server(self):
        cluster = K8sCluster.objects.create(
            name='prod-k8s',
            api_server='https://k8s.example.com:6443',
            kubeconfig=(
                'apiVersion: v1\n'
                'kind: Config\n'
                'current-context: prod\n'
                'contexts:\n'
                '  - name: prod\n'
                '    context:\n'
                '      cluster: prod-cluster\n'
                '      user: prod-user\n'
                'clusters:\n'
                '  - name: prod-cluster\n'
                '    cluster:\n'
                '      server: https://203.0.113.176:6443\n'
            ),
        )

        rendered = _prepare_kubeconfig(cluster)

        self.assertIn('server: https://k8s.example.com:6443', rendered)
        self.assertNotIn('server: https://203.0.113.176:6443', rendered)

    def test_service_external_ips_supports_current_client_field_name(self):
        spec = SimpleNamespace(external_ips=['203.0.113.10', '203.0.113.11'])

        self.assertEqual(_service_external_ips(spec), ['203.0.113.10', '203.0.113.11'])

    def test_serialize_service_item_supports_legacy_client_field_name(self):
        svc = SimpleNamespace(
            metadata=SimpleNamespace(
                name='gateway',
                namespace='prod',
                creation_timestamp=None,
            ),
            spec=SimpleNamespace(
                type='LoadBalancer',
                cluster_ip='10.96.0.10',
                external_i_ps=['203.0.113.20'],
                ports=[SimpleNamespace(port=80, node_port=30080, protocol='TCP')],
            ),
        )

        payload = _serialize_service_item(svc)

        self.assertEqual(payload['external_ip'], '203.0.113.20')
        self.assertEqual(payload['ports'], '80->30080/TCP')

    @patch('ops.k8s_views._get_k8s_client')
    def test_k8s_connection_reports_certificate_hint_on_ssl_error(self, mock_get_client):
        cluster = K8sCluster.objects.create(
            name='broken-k8s',
            api_server='https://203.0.113.176:6443',
            kubeconfig='apiVersion: v1\nkind: Config\ncurrent-context: broken\nclusters: []\ncontexts: []\n',
        )
        mock_get_client.side_effect = ssl.SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed')

        response = self.client.post(f'/api/k8s/clusters/{cluster.id}/test_connection/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertIn('证书校验失败', payload['message'])
        self.assertEqual(K8sCluster.objects.get(id=cluster.id).status, 'error')

    def test_k8s_summary_returns_demo_cluster_metrics(self):
        cluster = K8sCluster.objects.create(
            name='demo-cluster',
            kubeconfig='demo',
            status='connected',
        )

        response = self.client.get(f'/api/k8s/clusters/{cluster.id}/summary/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['cluster_name'], 'demo-cluster')
        self.assertEqual(payload['nodes_total'], 4)
        self.assertEqual(payload['nodes_ready'], 4)
        self.assertEqual(payload['pods_total'], 15)
        self.assertEqual(payload['pods_abnormal'], 2)
        self.assertEqual(payload['total_restarts'], 8)
        self.assertEqual(payload['workloads_total'], 16)
        self.assertGreaterEqual(len(payload['alerts']), 1)

    @patch('ops.k8s_views._build_demo_summary')
    def test_k8s_summary_uses_short_cache(self, mock_build_demo_summary):
        cluster = K8sCluster.objects.create(
            name='demo-cluster-cache',
            kubeconfig='demo',
            status='connected',
        )
        mock_build_demo_summary.return_value = {
            'cluster_name': cluster.name,
            'status': 'connected',
            'nodes_total': 4,
            'nodes_ready': 4,
            'pods_total': 15,
            'pods_abnormal': 0,
            'pods_restarting': 0,
            'total_restarts': 0,
            'services_total': 0,
            'ingresses_total': 0,
            'workloads_total': 0,
            'workloads_degraded': 0,
            'pvcs_total': 0,
            'pvcs_pending': 0,
            'configmaps_total': 0,
            'secrets_total': 0,
            'alerts': [],
        }

        first = self.client.get(f'/api/k8s/clusters/{cluster.id}/summary/')
        second = self.client.get(f'/api/k8s/clusters/{cluster.id}/summary/')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(mock_build_demo_summary.call_count, 1)

    @patch('ops.k8s_views._get_k8s_client')
    def test_k8s_summary_marks_payload_degraded_when_live_queries_timeout(self, mock_get_client):
        cluster = K8sCluster.objects.create(
            name='timeout-k8s',
            kubeconfig='apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\n',
            status='connected',
        )

        class FailingCoreV1Api:
            def list_namespace(self):
                raise TimeoutError('connect timed out')

            def list_node(self):
                raise TimeoutError('connect timed out')

            def list_pod_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_service_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_persistent_volume_claim_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_config_map_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_secret_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

        class FailingAppsV1Api:
            def list_deployment_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_stateful_set_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_daemon_set_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

        class FailingBatchV1Api:
            def list_job_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

            def list_cron_job_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

        class FailingNetworkingV1Api:
            def list_ingress_for_all_namespaces(self):
                raise TimeoutError('connect timed out')

        mock_get_client.return_value = MagicMock(
            CoreV1Api=MagicMock(return_value=FailingCoreV1Api()),
            AppsV1Api=MagicMock(return_value=FailingAppsV1Api()),
            BatchV1Api=MagicMock(return_value=FailingBatchV1Api()),
            NetworkingV1Api=MagicMock(return_value=FailingNetworkingV1Api()),
        )

        response = self.client.get(f'/api/k8s/clusters/{cluster.id}/summary/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['degraded'])
        self.assertIn('pods', payload['unavailable_resources'])
        self.assertTrue(any(item['level'] == 'warning' for item in payload['alerts']))
        self.assertFalse(any(item['level'] == 'success' for item in payload['alerts']))

    @patch('ops.k8s_views._get_k8s_client')
    def test_k8s_pods_returns_stale_cache_when_cluster_times_out(self, mock_get_client):
        cluster = K8sCluster.objects.create(
            name='stale-cache-k8s',
            kubeconfig='apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\n',
            status='connected',
        )
        stale_items = [{'name': 'cached-pod', 'namespace': 'default', 'status': 'Running', 'node': 'node-01', 'ip': '10.0.0.5', 'containers': [], 'restarts': 0, 'created': ''}]
        cache.set(_resource_stale_cache_key(cluster.id, 'pods', 'default'), stale_items, 300)
        mock_get_client.side_effect = TimeoutError('connect timed out')

        response = self.client.get(f'/api/k8s/clusters/{cluster.id}/pods/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), stale_items)

    @patch('ops.k8s_views._get_k8s_client')
    def test_k8s_summary_returns_stale_snapshot_when_build_fails(self, mock_get_client):
        cluster = K8sCluster.objects.create(
            name='summary-stale-k8s',
            kubeconfig='apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\n',
            status='connected',
        )
        cached_summary = {
            'cluster_name': cluster.name,
            'status': 'connected',
            'nodes_total': 3,
            'nodes_ready': 3,
            'pods_total': 10,
            'pods_abnormal': 0,
            'pods_restarting': 0,
            'total_restarts': 0,
            'services_total': 4,
            'ingresses_total': 1,
            'workloads_total': 6,
            'workloads_degraded': 0,
            'pvcs_total': 2,
            'pvcs_pending': 0,
            'configmaps_total': 5,
            'secrets_total': 4,
            'alerts': [{'level': 'success', 'message': 'cached'}],
        }
        cache.set(_summary_stale_cache_key(cluster.id), cached_summary, 300)
        mock_get_client.side_effect = RuntimeError('cluster unavailable')

        response = self.client.get(f'/api/k8s/clusters/{cluster.id}/summary/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['degraded'])
        self.assertEqual(payload['pods_total'], 10)
        self.assertIn('cached snapshot', payload['alerts'][0]['message'])

    @patch('ops.k8s_views._build_live_summary')
    def test_k8s_summary_does_not_cache_unreliable_zero_snapshot(self, mock_build_live_summary):
        cluster = K8sCluster.objects.create(
            name='summary-zero-degraded-k8s',
            kubeconfig='apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\n',
            status='connected',
        )
        cached_summary = {
            'cluster_name': cluster.name,
            'status': 'connected',
            'nodes_total': 2,
            'nodes_ready': 2,
            'pods_total': 8,
            'pods_abnormal': 1,
            'pods_restarting': 1,
            'total_restarts': 3,
            'services_total': 4,
            'ingresses_total': 1,
            'workloads_total': 5,
            'workloads_degraded': 0,
            'pvcs_total': 2,
            'pvcs_pending': 0,
            'configmaps_total': 5,
            'secrets_total': 4,
            'alerts': [{'level': 'success', 'message': 'cached'}],
        }
        mock_build_live_summary.return_value = {
            'cluster_name': cluster.name,
            'status': 'connected',
            'namespaces_total': 0,
            'nodes_total': 0,
            'nodes_ready': 0,
            'pods_total': 0,
            'pods_abnormal': 0,
            'pods_restarting': 0,
            'total_restarts': 0,
            'services_total': 0,
            'ingresses_total': 0,
            'workloads_total': 0,
            'workloads_degraded': 0,
            'pvcs_total': 0,
            'pvcs_pending': 0,
            'configmaps_total': 0,
            'secrets_total': 0,
            'degraded': True,
            'unavailable_resources': ['pods', 'deployments'],
            'alerts': [{'level': 'warning', 'message': 'partial collection failed'}],
        }
        cache.set(_summary_stale_cache_key(cluster.id), cached_summary, 300)

        response = self.client.get(f'/api/k8s/clusters/{cluster.id}/summary/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['degraded'])
        self.assertEqual(payload['pods_total'], 8)
        self.assertEqual(payload['workloads_total'], 5)
        self.assertIn('cached snapshot', payload['alerts'][0]['message'])

    @patch('ops.k8s_views._get_k8s_client')
    def test_k8s_pod_logs_degrade_to_empty_payload_on_timeout(self, mock_get_client):
        cluster = K8sCluster.objects.create(
            name='pod-logs-timeout-k8s',
            kubeconfig='apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\n',
            status='connected',
        )
        mock_get_client.side_effect = TimeoutError('connect timed out')

        response = self.client.get(
            f'/api/k8s/clusters/{cluster.id}/pod_logs/',
            {'pod_name': 'api-server-1', 'namespace': 'default'},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['degraded'])
        self.assertEqual(payload['logs'], '')

    @patch('ops.docker_views._get_ssh_client_from_docker_host')
    @patch('ops.docker_views._ssh_exec')
    def test_list_containers_uses_json_line_format_for_broader_docker_compatibility(self, mock_ssh_exec, mock_get_client):
        host = DockerHost.objects.create(name='docker-host-01', ip_address='10.0.0.10')
        client = MagicMock()
        mock_get_client.return_value = client
        mock_ssh_exec.return_value = (0, '{"ID":"abc123","Names":"web","Image":"nginx:1.25","State":"running","Status":"Up 2h"}\n', '')

        response = self.client.get('/api/docker/containers/', {'host_id': host.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['name'], 'web')
        issued_command = mock_ssh_exec.call_args.args[1]
        self.assertIn("--format '{{json .}}'", issued_command)
        client.close.assert_called_once()

    @patch('ops.docker_views._get_ssh_client_from_docker_host')
    @patch('ops.docker_views._ssh_exec')
    def test_container_logs_quote_identifier_and_clamp_tail(self, mock_ssh_exec, mock_get_client):
        host = DockerHost.objects.create(name='docker-host-02', ip_address='10.0.0.11')
        client = MagicMock()
        mock_get_client.return_value = client
        mock_ssh_exec.return_value = (0, 'demo logs', '')
        container_id = 'demo; echo hacked'

        response = self.client.get(
            f"/api/docker/containers/{quote(container_id, safe='')}/logs/",
            {'host_id': host.id, 'tail': 99999},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['logs'], 'demo logs')
        issued_command = mock_ssh_exec.call_args.args[1]
        self.assertIn('docker logs --tail=2000', issued_command)
        self.assertIn("'demo; echo hacked'", issued_command)
        client.close.assert_called_once()

    def test_k8s_pod_exec_returns_demo_output(self):
        cluster = K8sCluster.objects.create(name='demo-cluster-exec', kubeconfig='demo', status='connected')

        response = self.client.post(
            f'/api/k8s/clusters/{cluster.id}/pod_exec/',
            {
                'pod_name': 'api-server-5f8b7c6d4-r9p2w',
                'namespace': 'production',
                'command': 'whoami && pwd',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertIn('whoami && pwd', payload['output'])

    def test_k8s_scale_workload_updates_demo_state(self):
        cluster = K8sCluster.objects.create(name='demo-cluster-scale', kubeconfig='demo', status='connected')

        scale_response = self.client.post(
            f'/api/k8s/clusters/{cluster.id}/scale_workload/',
            {
                'workload_type': 'deployment',
                'name': 'nginx-deployment',
                'namespace': 'production',
                'replicas': 4,
            },
            format='json',
        )
        list_response = self.client.get(f'/api/k8s/clusters/{cluster.id}/deployments/', {'namespace': 'production'})

        self.assertEqual(scale_response.status_code, 200)
        self.assertEqual(list_response.status_code, 200)
        deployment = next(item for item in list_response.json() if item['name'] == 'nginx-deployment')
        self.assertEqual(deployment['replicas'], 4)

    def test_k8s_config_resource_update_and_rollback_preview_use_demo_snapshot(self):
        cluster = K8sCluster.objects.create(name='demo-cluster-config', kubeconfig='demo', status='connected')

        detail_response = self.client.get(
            f'/api/k8s/clusters/{cluster.id}/config_resource_detail/',
            {'type': 'configmap', 'name': 'nginx-config', 'namespace': 'production'},
        )
        update_response = self.client.post(
            f'/api/k8s/clusters/{cluster.id}/config_resource_update/',
            {
                'type': 'configmap',
                'name': 'nginx-config',
                'namespace': 'production',
                'content': 'worker_processes: auto\nkeepalive_timeout: 65\n',
            },
            format='json',
        )
        rollback_preview = self.client.get(
            f'/api/k8s/clusters/{cluster.id}/config_resource_rollback_preview/',
            {'type': 'configmap', 'name': 'nginx-config', 'namespace': 'production'},
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(rollback_preview.status_code, 200)
        self.assertTrue(update_response.json()['resource']['rollback_available'])
        self.assertIn('worker_processes', update_response.json()['resource']['text'])
        self.assertIn('rollback', rollback_preview.json()['diff'])
        self.assertEqual(K8sConfigRevision.objects.filter(cluster=cluster).count(), 1)

    def test_k8s_config_resource_revisions_list_preview_and_targeted_rollback(self):
        cluster = K8sCluster.objects.create(name='demo-cluster-revisions', kubeconfig='demo', status='connected')

        first_update = self.client.post(
            f'/api/k8s/clusters/{cluster.id}/config_resource_update/',
            {
                'type': 'configmap',
                'name': 'nginx-config',
                'namespace': 'production',
                'content': 'worker_processes: auto\nkeepalive_timeout: 65\n',
            },
            format='json',
        )
        second_update = self.client.post(
            f'/api/k8s/clusters/{cluster.id}/config_resource_update/',
            {
                'type': 'configmap',
                'name': 'nginx-config',
                'namespace': 'production',
                'content': 'worker_processes: 4\nkeepalive_timeout: 75\n',
            },
            format='json',
        )
        revisions_response = self.client.get(
            f'/api/k8s/clusters/{cluster.id}/config_resource_revisions/',
            {'type': 'configmap', 'name': 'nginx-config', 'namespace': 'production'},
        )

        self.assertEqual(first_update.status_code, 200)
        self.assertEqual(second_update.status_code, 200)
        self.assertEqual(revisions_response.status_code, 200)
        items = revisions_response.json()['items']
        self.assertGreaterEqual(len(items), 2)
        target_revision = items[-1]
        self.assertEqual(target_revision['action'], 'update')

        preview_response = self.client.get(
            f'/api/k8s/clusters/{cluster.id}/config_resource_revision_preview/',
            {
                'type': 'configmap',
                'name': 'nginx-config',
                'namespace': 'production',
                'revision_id': target_revision['id'],
            },
        )
        rollback_response = self.client.post(
            f'/api/k8s/clusters/{cluster.id}/config_resource_rollback_to_revision/',
            {
                'type': 'configmap',
                'name': 'nginx-config',
                'namespace': 'production',
                'revision_id': target_revision['id'],
            },
            format='json',
        )
        detail_response = self.client.get(
            f'/api/k8s/clusters/{cluster.id}/config_resource_detail/',
            {'type': 'configmap', 'name': 'nginx-config', 'namespace': 'production'},
        )

        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(rollback_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn('revision-', preview_response.json()['diff'])
        self.assertIn('key1', detail_response.json()['text'])
        self.assertIn('key3', detail_response.json()['text'])
        self.assertGreaterEqual(K8sConfigRevision.objects.filter(cluster=cluster).count(), 3)

    @patch('ops.docker_views._get_ssh_client_from_docker_host')
    @patch('ops.docker_views._ssh_exec')
    def test_remove_images_quotes_each_identifier(self, mock_ssh_exec, mock_get_client):
        host = DockerHost.objects.create(name='docker-host-03', ip_address='10.0.0.12')
        client = MagicMock()
        mock_get_client.return_value = client
        mock_ssh_exec.return_value = (0, 'deleted', '')

        response = self.client.delete(
            '/api/docker/images/remove/',
            {'host_id': host.id, 'image_ids': ['sha256:abc', 'bad; echo hacked']},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        issued_command = mock_ssh_exec.call_args.args[1]
        self.assertIn("docker rmi", issued_command)
        self.assertIn("'bad; echo hacked'", issued_command)
        client.close.assert_called_once()

    @patch('ops.docker_views._get_ssh_client_from_docker_host')
    @patch('ops.docker_views._ssh_exec')
    def test_prune_dangling_images_uses_docker_image_prune(self, mock_ssh_exec, mock_get_client):
        host = DockerHost.objects.create(name='docker-host-04', ip_address='10.0.0.13')
        client = MagicMock()
        mock_get_client.return_value = client
        mock_ssh_exec.return_value = (0, 'Total reclaimed space: 0B', '')

        response = self.client.post('/api/docker/images/prune/', {'host_id': host.id}, format='json')

        self.assertEqual(response.status_code, 200)
        issued_command = mock_ssh_exec.call_args.args[1]
        self.assertEqual(issued_command, 'docker image prune -f 2>&1')
        client.close.assert_called_once()

    @patch('ops.docker_views._get_ssh_client_from_docker_host')
    def test_demo_docker_host_returns_cached_container_and_image_warehouse(self, mock_get_client):
        host = DockerHost.objects.create(name='app-release-test', ip_address='192.168.1.120', docker_api_version='24.0')

        container_response = self.client.get('/api/docker/containers/', {'host_id': host.id})
        image_response = self.client.get('/api/docker/images/', {'host_id': host.id})

        self.assertEqual(container_response.status_code, 200)
        self.assertEqual(image_response.status_code, 200)
        self.assertTrue(any(item['name'] == 'workorder-center-batch-1' for item in container_response.json()))
        self.assertTrue(any(item['repository'] == 'registry.demo.local/workorder-center' for item in image_response.json()))
        mock_get_client.assert_not_called()

    def test_demo_docker_container_action_logs_and_inspect_update_cached_state(self):
        host = DockerHost.objects.create(name='gateway-prod', ip_address='192.168.1.121', docker_api_version='24.0')

        container_response = self.client.get('/api/docker/containers/', {'host_id': host.id})
        self.assertEqual(container_response.status_code, 200)
        target = next(item for item in container_response.json() if item['name'] == 'member-center-failed')

        stop_response = self.client.post(
            f"/api/docker/containers/{quote(target['id'], safe='')}/action/",
            {'host_id': host.id, 'action': 'start'},
            format='json',
        )
        self.assertEqual(stop_response.status_code, 200)

        updated_list = self.client.get('/api/docker/containers/', {'host_id': host.id}).json()
        updated = next(item for item in updated_list if item['id'] == target['id'])
        self.assertEqual(updated['state'], 'running')

        logs_response = self.client.get(
            f"/api/docker/containers/{quote(target['id'], safe='')}/logs/",
            {'host_id': host.id, 'tail': 50},
        )
        inspect_response = self.client.get(
            f"/api/docker/containers/{quote(target['id'], safe='')}/inspect/",
            {'host_id': host.id},
        )

        self.assertEqual(logs_response.status_code, 200)
        self.assertEqual(inspect_response.status_code, 200)
        self.assertIn('member-center-failed', logs_response.json()['logs'])
        self.assertEqual(inspect_response.json()['State']['Status'], 'running')

    def test_demo_docker_image_remove_and_prune_update_cached_state(self):
        host = DockerHost.objects.create(name='member-prod', ip_address='192.168.1.122', docker_api_version='24.0')

        initial_images = self.client.get('/api/docker/images/', {'host_id': host.id}).json()
        dangling = next(item for item in initial_images if item['repository'] == '<none>')
        in_use = next(item for item in initial_images if item['repository'] == 'redis')

        remove_response = self.client.delete(
            '/api/docker/images/remove/',
            {'host_id': host.id, 'image_ids': [dangling['id'], in_use['id']]},
            format='json',
        )
        self.assertEqual(remove_response.status_code, 200)
        self.assertIn('跳过 1', remove_response.json()['message'])

        after_remove = self.client.get('/api/docker/images/', {'host_id': host.id}).json()
        self.assertFalse(any(item['id'] == dangling['id'] for item in after_remove))
        self.assertTrue(any(item['id'] == in_use['id'] for item in after_remove))

        prune_response = self.client.post('/api/docker/images/prune/', {'host_id': host.id}, format='json')
        self.assertEqual(prune_response.status_code, 200)
        after_prune = self.client.get('/api/docker/images/', {'host_id': host.id}).json()
        self.assertFalse(any(item['repository'] == '<none>' or item['tag'] == '<none>' for item in after_prune))


class MiddlewareViewsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('middleware-admin', 'middleware@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)
        self.asset_environment = TaskResourceGroup.objects.create(
            name='生产资产', code='prod', group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
        )

    def test_middleware_overview_is_empty_without_registered_assets(self):
        response = self.client.get('/api/middleware/overview/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['assets'], [])
        self.assertEqual(payload['summary']['total'], 0)
        self.assertEqual(payload['summary']['by_type']['redis'], 0)
        self.assertNotIn('database', payload)
        self.assertNotIn('monitoring', payload)

    def test_create_asset_persists_only_submitted_real_fields(self):
        response = self.client.post(
            '/api/middleware/action/',
            {
                'action': 'create_asset',
                'payload': {
                    'name': 'production-cache',
                    'asset_type': 'redis',
                    'business_group_ids': [self.asset_environment.id],
                    'endpoint': 'redis.example.internal:6379',
                    'version': '7.2',
                },
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        asset = MiddlewareAsset.objects.get()
        self.assertEqual(asset.name, 'production-cache')
        self.assertEqual(asset.status, MiddlewareAsset.STATUS_UNKNOWN)
        item = response.json()['asset']
        self.assertEqual(item['endpoint'], 'redis.example.internal:6379')
        self.assertEqual(item['business_group_ids'], [self.asset_environment.id])
        self.assertNotIn('qps', item)
        self.assertNotIn('memory_usage', item)

    def test_overview_filters_assets_by_business_context_environment(self):
        other_environment = TaskResourceGroup.objects.create(
            name='测试资产', code='test', group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
        )
        prod_asset = MiddlewareAsset.objects.create(
            name='prod-cache', asset_type='redis', environment='prod', endpoint='redis-prod:6379',
            task_resource_environment=self.asset_environment,
        )
        prod_asset.business_groups.add(self.asset_environment)
        test_asset = MiddlewareAsset.objects.create(
            name='test-cache', asset_type='redis', environment='test', endpoint='redis-test:6379',
            task_resource_environment=other_environment,
        )
        test_asset.business_groups.add(other_environment)

        response = self.client.get('/api/middleware/overview/', {
            'task_resource_environment_id': self.asset_environment.id,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['name'] for item in response.json()['assets']], ['prod-cache'])

    def test_middleware_asset_can_be_shared_by_multiple_business_groups(self):
        shared_group = TaskResourceGroup.objects.create(
            name='共享业务', code='shared-business', group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
        )
        response = self.client.post('/api/middleware/action/', {
            'action': 'create_asset',
            'payload': {
                'name': 'shared-redis',
                'asset_type': 'redis',
                'business_group_ids': [self.asset_environment.id, shared_group.id],
                'endpoint': 'shared-redis:6379',
            },
        }, format='json')

        self.assertEqual(response.status_code, 201, response.json())
        asset = MiddlewareAsset.objects.get()
        self.assertEqual(
            set(asset.business_groups.values_list('id', flat=True)),
            {self.asset_environment.id, shared_group.id},
        )

    def test_update_asset(self):
        asset = MiddlewareAsset.objects.create(
            name='orders-kafka', asset_type='kafka', environment='prod', endpoint='kafka:9092'
        )
        response = self.client.post(
            '/api/middleware/action/',
            {
                'target_id': asset.id,
                'action': 'update_asset',
                'payload': {'endpoint': 'kafka.internal:9092', 'description': '订单消息'},
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        asset.refresh_from_db()
        self.assertEqual(asset.endpoint, 'kafka.internal:9092')
        self.assertEqual(asset.description, '订单消息')

    def test_delete_asset(self):
        asset = MiddlewareAsset.objects.create(
            name='orders-db', asset_type='database', environment='test', endpoint='mysql://db:3306/orders'
        )
        response = self.client.post(
            '/api/middleware/action/',
            {'target_id': asset.id, 'action': 'delete_asset'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MiddlewareAsset.objects.exists())
        self.assertEqual(response.json()['data']['assets'], [])

    def test_asset_credentials_are_stored_but_never_returned(self):
        response = self.client.post(
            '/api/middleware/action/',
            {
                'action': 'create_asset',
                'payload': {
                    'name': 'orders-db',
                    'asset_type': 'database',
                    'business_group_ids': [self.asset_environment.id],
                    'endpoint': 'mysql://db.internal:3306/orders',
                    'username': 'ops_reader',
                    'password': 'secret-for-test',
                },
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        asset = MiddlewareAsset.objects.get()
        self.assertEqual(asset.username, 'ops_reader')
        self.assertEqual(asset.password, 'secret-for-test')
        item = response.json()['asset']
        self.assertTrue(item['password_configured'])
        self.assertNotIn('password', item)

    def test_validation_rejects_missing_endpoint_and_unsupported_type(self):
        missing_endpoint = self.client.post(
            '/api/middleware/action/',
            {
                'action': 'create_asset',
                'payload': {'name': 'cache', 'asset_type': 'redis', 'business_group_ids': [self.asset_environment.id]},
            },
            format='json',
        )
        unsupported = self.client.post(
            '/api/middleware/action/',
            {
                'action': 'create_asset',
                'payload': {
                    'name': 'rabbit',
                    'asset_type': 'rabbitmq',
                    'business_group_ids': [self.asset_environment.id],
                    'endpoint': 'rabbit:5672',
                },
            },
            format='json',
        )
        self.assertEqual(missing_endpoint.status_code, 400)
        self.assertEqual(unsupported.status_code, 400)
        self.assertFalse(MiddlewareAsset.objects.exists())


class K8sOnlyDeploymentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('deploy-admin', 'deploy@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)
        self.business = ResourceNode.objects.create(name='交易系统', node_type='biz')
        ResourceNode.objects.create(name='prod', node_type='env', parent=self.business)
        self.cluster = K8sCluster.objects.create(name='production-k8s', api_server='https://k8s.example:6443')

    def test_new_deployments_require_a_k8s_cluster(self):
        payload = {
            'app_name': 'orders-api',
            'business_line': self.business.name,
            'version': '1.0.0',
            'environment': 'prod',
            'deploy_mode': 'docker_compose',
        }
        response = self.client.post('/api/deployments/', payload, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('deploy_mode', response.json())

    def test_new_k8s_deployment_is_accepted(self):
        response = self.client.post(
            '/api/deployments/',
            {
                'app_name': 'orders-api',
                'business_line': self.business.name,
                'version': '1.0.0',
                'environment': 'prod',
                'deploy_mode': 'k8s',
                'cluster': self.cluster.id,
                'namespace': 'orders',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        deployment = Deployment.objects.get()
        self.assertEqual(deployment.deploy_mode, 'k8s')
        self.assertEqual(deployment.cluster_id, self.cluster.id)


class AlertViewSetFilterTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('alert-admin', 'alert@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)
        self.host = Host.objects.create(hostname='alert-host-01', ip_address='10.0.1.10', environment='prod', status='warning')
        Alert.objects.create(title='Critical alert', level='critical', source='monitor', message='critical issue', is_acknowledged=False, host=self.host)
        Alert.objects.create(title='Warning alert', level='warning', source='monitor', message='warning issue', is_acknowledged=True, host=self.host)

    def test_alert_list_supports_level_and_ack_filters(self):
        response = self.client.get('/api/alerts/', {'level': 'critical', 'is_acknowledged': False})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        results = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['level'], 'critical')
        self.assertFalse(results[0]['is_acknowledged'])


class AlertPlatformRuleTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('alert-config-admin', 'alert-config@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)

    def test_rule_template_can_be_created_and_listed(self):
        response = self.client.post(
            '/api/alert-rule-templates/',
            {
                'name': 'K8S Pod CrashLoopBackOff',
                'code': 'k8s-pod-crashloop-test',
                'source_type': 'k8s',
                'level': 'warning',
                'condition': {'resource': 'pod', 'reason': 'CrashLoopBackOff'},
                'query_config': {'resource': 'pods', 'field': 'container_statuses'},
                'default_labels': {'product': 'container-platform'},
                'is_builtin': False,
                'is_enabled': True,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(AlertRule.objects.filter(code='k8s-pod-crashloop-test', is_template=True).exists())

        list_response = self.client.get('/api/alert-rule-templates/')
        self.assertEqual(list_response.status_code, 200)
        payload = list_response.json()
        results = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        self.assertTrue(any(item['code'] == 'k8s-pod-crashloop-test' for item in results))

    def test_builtin_template_bundles_include_k8s_events_and_linux_server(self):
        from ops.alert_rule_presets import ensure_builtin_alert_rule_templates

        ensure_builtin_alert_rule_templates()

        k8s_codes = set(AlertRule.objects.filter(is_template=True, labels__integration='kubernetes').values_list('code', flat=True))
        linux_codes = set(AlertRule.objects.filter(is_template=True, labels__integration='linux').values_list('code', flat=True))
        self.assertTrue(
            {'k8s-node-not-ready', 'k8s-abnormal-pods', 'k8s-pod-restarts', 'k8s-events-warning'}.issubset(k8s_codes)
        )
        reference_templates = AlertRule.objects.filter(
            is_template=True,
            labels__template_source='xing-cloud-ops-agent',
        )
        self.assertTrue({
            'apiserver', 'workload', 'network', 'storage', 'system',
        }.issubset(set(reference_templates.values_list('labels__rule_group', flat=True))))
        self.assertTrue({
            'k8s-apiserver-latency',
            'k8s-pod-unschedulable',
            'k8s-node-network-flapping',
            'k8s-pv-full-in-four-days',
            'k8s-node-oom-kill',
        }.issubset(set(reference_templates.values_list('code', flat=True))))
        self.assertTrue(
            {'linux-node-down', 'linux-high-cpu', 'linux-high-memory', 'linux-high-disk'}.issubset(linux_codes)
        )
        k8s_events = AlertRule.objects.get(code='k8s-events-warning', is_template=True)
        self.assertEqual(k8s_events.source_type, 'clickhouse')
        self.assertEqual(k8s_events.query_config['collection'], 'k8s-events')

    def test_alert_rule_template_api_returns_full_builtin_catalog(self):
        from ops.alert_rule_presets import ensure_builtin_alert_rule_templates

        ensure_builtin_alert_rule_templates()

        response = self.client.get('/api/alert-rule-templates/?page_size=200')

        self.assertEqual(response.status_code, 200)
        rows = response.json()
        if isinstance(rows, dict) and 'results' in rows:
            rows = rows['results']
        codes = {item['code'] for item in rows}
        self.assertIn('k8s-events-warning', codes)
        self.assertIn('linux-node-down', codes)
        self.assertGreaterEqual(len(rows), AlertRule.objects.filter(is_template=True).count())

    def test_alert_rule_can_be_created_from_template(self):
        template = AlertRule.objects.create(
            name='ClickHouse ERROR 鏃ュ織绐佸',
            code='clickhouse-error-spike-test',
            source_type='clickhouse',
            source='custom',
            is_template=True,
            is_enabled=False,
            level='warning',
            query_config={'collection': 'container-logs'},
            condition={'level': 'ERROR', 'threshold': 20},
        )
        response = self.client.post(
            '/api/alert-rules/',
            {
                'template': template.id,
                'name': '生产容器 ERROR 日志突增',
                'code': 'prod-container-error-spike',
                'source_type': 'clickhouse',
                'level': 'warning',
                'query_config': {'collection': 'container-logs', 'window': '5m'},
                'condition': {'level': 'ERROR', 'threshold': 20},
                'labels': {'environment': 'prod', 'cluster': 'zhengzhou-prod'},
                'annotations': {'summary': '容器 ERROR 日志数量超过阈值'},
                'interval_seconds': 60,
                'notify_enabled': True,
                'auto_analyze': True,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        rule = AlertRule.objects.get(code='prod-container-error-spike')
        self.assertEqual(rule.template, template)
        self.assertEqual(rule.labels['cluster'], 'zhengzhou-prod')

    def test_trigger_rule_creates_platform_alert_and_reuses_fingerprint(self):
        rule = AlertRule.objects.create(
            name='K8S Pod CrashLoopBackOff',
            code='prod-pod-crashloop',
            source_type='k8s',
            level='critical',
            labels={'environment': 'prod', 'cluster': 'zhengzhou-prod'},
            annotations={'summary': 'Pod 进入 CrashLoopBackOff'},
            query_config={'resource': 'pods'},
            condition={'reason': 'CrashLoopBackOff'},
            notify_enabled=False,
            auto_analyze=True,
        )

        payload = {
            'title': 'Pod xing-cloud-app CrashLoopBackOff',
            'message': '容器连续重启 6 次',
            'resource_type': 'pod',
            'resource': 'xing-cloud-app-0',
            'labels': {'namespace': 'xing-cloud', 'pod': 'xing-cloud-app-0'},
            'evidence': {'restart_count': 6, 'reason': 'CrashLoopBackOff'},
        }
        first_response = self.client.post(f'/api/alert-rules/{rule.id}/trigger/', payload, format='json')
        second_response = self.client.post(f'/api/alert-rules/{rule.id}/trigger/', payload, format='json')

        self.assertEqual(first_response.status_code, 202)
        self.assertEqual(second_response.status_code, 202)
        self.assertEqual(Alert.objects.count(), 1)
        alert = Alert.objects.get()
        self.assertEqual(alert.source_type, 'platform')
        self.assertEqual(alert.level, 'critical')
        self.assertEqual(alert.labels['alert_rule_code'], 'prod-pod-crashloop')
        self.assertEqual(alert.labels['namespace'], 'xing-cloud')
        self.assertEqual(alert.raw_payload['ai_analysis']['status'], 'pending')
        self.assertEqual(alert.occurrence_count, 2)
        self.assertTrue(AlertAction.objects.filter(alert=alert, action='rule_evaluation').exists())
        rule.refresh_from_db()
        self.assertIsNotNone(rule.last_triggered_at)

    @patch('ops.alert_engine.evaluator.execute_promql_query')
    def test_evaluate_prometheus_rule_dry_run_does_not_create_alert(self, mock_promql):
        mock_promql.return_value = {
            'result': [
                {'metric': {'instance': 'api-01', 'job': 'api'}, 'value': [1710000000, '95']},
            ],
        }
        datasource = MetricDataSource.objects.create(
            name='API Prometheus',
            provider='prometheus',
            config={'query_url': 'http://prometheus.local:9090'},
            is_enabled=True,
        )
        rule = AlertRule.objects.create(
            name='API CPU high',
            code='api-cpu-high-dry-run',
            source_type='prometheus',
            metric_datasource=datasource,
            level='critical',
            query_config={'promql': 'node_cpu_usage_percent'},
            condition={'operator': '>', 'threshold': 90},
            labels={'environment': 'prod', 'cluster': 'prod-k8s'},
            annotations={'summary': 'CPU high'},
            notify_enabled=False,
        )

        response = self.client.post(f'/api/alert-rules/{rule.id}/evaluate/', {'dry_run': True}, format='json')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['dry_run'])
        self.assertEqual(payload['matched_count'], 1)
        self.assertEqual(payload['would_fire_count'], 1)
        self.assertEqual(Alert.objects.count(), 0)

    @patch('ops.alert_engine.evaluator._clickhouse_data_rows')
    @patch('ops.alert_engine.evaluator._clickhouse_request')
    def test_evaluate_clickhouse_rule_dry_run_counts_log_spike(self, mock_request, mock_rows):
        mock_request.return_value = {'data': [{'value': 8, 'name': 'api'}]}
        mock_rows.return_value = [{'value': 8, 'name': 'api'}]
        LogDataSource.objects.create(
            name='ClickHouse For Rule',
            provider='clickhouse',
            is_default=True,
            config={
                'endpoint': 'http://clickhouse.prod.local:8123',
                'collections': [
                    {'key': 'container-logs', 'database': 'container_logs', 'table': 'logs', 'time_field': 'timestamp'},
                ],
            },
        )
        rule = AlertRule.objects.create(
            name='Container ERROR spike',
            code='container-error-spike-dry-run',
            source_type='clickhouse',
            level='warning',
            query_config={'collection': 'container-logs', 'window_minutes': 5, 'group_by': 'pod_name'},
            condition={'level': 'ERROR', 'threshold': 5, 'keyword': 'Exception'},
            labels={'environment': 'prod', 'cluster': 'prod-k8s', 'namespace': 'xing-cloud'},
            notify_enabled=False,
        )

        response = self.client.post(f'/api/alert-rules/{rule.id}/evaluate/', {'dry_run': True}, format='json')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['matched_count'], 1)
        self.assertEqual(payload['results'][0]['value'], 8)
        self.assertEqual(Alert.objects.count(), 0)
        self.assertIn('container_logs', mock_request.call_args.args[1])

    @patch('ops.alert_engine.evaluator._clickhouse_data_rows')
    @patch('ops.alert_engine.evaluator._clickhouse_request')
    def test_clickhouse_rule_sql_applies_level_list_from_query_config(self, mock_request, mock_rows):
        mock_request.return_value = {'data': [{'value': 8}]}
        mock_rows.return_value = [{'value': 8}]
        LogDataSource.objects.create(
            name='ClickHouse Error Levels',
            provider='clickhouse',
            is_default=True,
            config={
                'endpoint': 'http://clickhouse.prod.local:8123',
                'collections': [
                    {
                        'key': 'container-logs',
                        'database': 'container_logs',
                        'table': 'logs',
                        'time_field': 'timestamp',
                        'level_field': 'log_level',
                    },
                ],
            },
        )
        rule = AlertRule.objects.create(
            name='Container ERROR spike',
            code='container-error-spike-level-list',
            source_type='clickhouse',
            level='warning',
            query_config={'collection': 'container-logs', 'window_minutes': 5, 'level': ['ERROR', 'FATAL', 'CRITICAL']},
            condition={'operator': '>', 'threshold': 5},
            notify_enabled=False,
        )

        response = self.client.post(f'/api/alert-rules/{rule.id}/evaluate/', {'dry_run': True}, format='json')

        self.assertEqual(response.status_code, 200)
        sql = mock_request.call_args.args[1]
        self.assertIn('upper(toString(`log_level`)) IN', sql)
        self.assertIn("'ERROR'", sql)
        self.assertIn("'FATAL'", sql)
        self.assertIn("'CRITICAL'", sql)

    @patch('ops.alert_engine.evaluator._clickhouse_data_rows')
    @patch('ops.alert_engine.evaluator._clickhouse_request')
    def test_clickhouse_rule_sql_applies_ingress_status_min(self, mock_request, mock_rows):
        mock_request.return_value = {'data': [{'value': 60}]}
        mock_rows.return_value = [{'value': 60}]
        LogDataSource.objects.create(
            name='ClickHouse Ingress',
            provider='clickhouse',
            is_default=True,
            config={
                'endpoint': 'http://clickhouse.prod.local:8123',
                'collections': [
                    {
                        'key': 'ingress-access',
                        'database': 'nginxlogs',
                        'table': 'nginx_access',
                        'time_field': 'timestamp',
                        'level_field': 'status',
                    },
                ],
            },
        )
        rule = AlertRule.objects.create(
            name='Ingress 5XX Spike',
            code='ingress-5xx-status-min',
            source_type='clickhouse',
            level='warning',
            query_config={'collection': 'ingress-access', 'window_minutes': 5, 'status_min': 500},
            condition={'operator': '>', 'threshold': 50},
            notify_enabled=False,
        )

        response = self.client.post(f'/api/alert-rules/{rule.id}/evaluate/', {'dry_run': True}, format='json')

        self.assertEqual(response.status_code, 200)
        sql = mock_request.call_args.args[1]
        self.assertIn('`status` >= 500', sql)

    @patch('ops.log_views.http_requests.request')
    def test_alert_log_evidence_returns_clickhouse_samples_for_rule_window(self, mock_request):
        mock_request.return_value = MockHttpResponse({
            'statistics': {'elapsed': 0.004},
            'rows_before_limit_at_least': 1,
            'data': [
                {
                    'timestamp': '2026-07-10 16:04:06.092',
                    'namespace': 'monitoring',
                    'pod_name': 'alertmanager-main-0',
                    'container_name': 'alertmanager',
                    'log_level': 'ERROR',
                    'message': 'Notify for alerts failed',
                    'log_message': 'Notify for alerts failed',
                },
            ],
        })
        LogDataSource.objects.create(
            name='ClickHouse Evidence',
            provider='clickhouse',
            is_default=True,
            is_enabled=True,
            config={
                'endpoint': 'http://clickhouse.prod.local:8123',
                'collections': [
                    {
                        'key': 'container-logs',
                        'database': 'container_logs',
                        'table': 'logs',
                        'time_field': 'timestamp',
                        'level_field': 'log_level',
                        'message_fields': 'message,log_message',
                        'source_fields': 'namespace,pod_name,container_name',
                        'search_fields': 'namespace,pod_name,container_name,log_level,message,log_message',
                    },
                ],
            },
        )
        alert = Alert.objects.create(
            title='Container ERROR Log Spike',
            level='warning',
            status=Alert.STATUS_ACTIVE,
            source='Xing-Cloud Alert Rule',
            source_type=Alert.SOURCE_PLATFORM,
            service='container-logs',
            labels={'collection': 'container-logs', 'alert_rule_source_type': 'clickhouse'},
            raw_payload={
                'rule': {
                    'source_type': 'clickhouse',
                    'query_config': {
                        'collection': 'container-logs',
                        'window_minutes': 5,
                        'level': ['ERROR', 'FATAL', 'CRITICAL'],
                    },
                },
            },
        )

        response = self.client.get(f'/api/alerts/{alert.id}/log-evidence/', {'limit': 5})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['summary']['collection'], 'container-logs')
        self.assertEqual(payload['summary']['count'], 1)
        self.assertEqual(payload['logs'][0]['message'], 'Notify for alerts failed')
        sql = mock_request.call_args.kwargs['data']
        self.assertIn('FROM `container_logs`.`logs`', sql)
        self.assertIn('upper(toString(`log_level`)) IN', sql)

    def test_alert_rule_engine_status_endpoint(self):
        AlertRule.objects.create(
            name='SLA monthly risk',
            code='sla-monthly-risk-test',
            source_type='sla',
            level='warning',
            query_config={'metric': 'month_sla'},
            condition={'operator': '<', 'threshold': 99.96},
            notify_enabled=False,
        )

        response = self.client.get('/api/alert-rules/engine-status/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['enabled_rules'], 1)
        self.assertIn('latest_scan_at', payload)


class AlertBatchNotificationTests(TestCase):
    def test_storm_batch_notifies_primary_alert_once(self):
        from ops.alerting import dispatch_alert_batch_notifications

        alerts = [
            Alert.objects.create(
                title=f'pod failure {index}',
                level='critical',
                status=Alert.STATUS_ACTIVE,
                source='platform',
                source_type=Alert.SOURCE_PLATFORM,
                message='pod crash',
                environment='prod',
                cluster='prod-k8s',
                namespace='xing-cloud',
                resource_type='pod',
                resource='api',
                fingerprint=f'storm-{index}',
            )
            for index in range(3)
        ]

        with patch('ops.alerting.dispatch_alert_notifications', return_value=['sent']) as mocked_dispatch:
            result = dispatch_alert_batch_notifications(alerts, action='fire')

        self.assertEqual(mocked_dispatch.call_count, 1)
        self.assertEqual(result['notified_count'], 1)
        self.assertEqual(result['storm_batches'][0]['count'], 3)
        for alert in alerts:
            alert.refresh_from_db()
            self.assertEqual(alert.raw_payload['notification_batch']['group_key'], 'prod|prod-k8s|xing-cloud|api')


class AlertWebhookRetirementTests(TestCase):
    def test_alert_webhook_route_is_not_exposed(self):
        response = self.client.post(
            '/api/alerts/webhooks/generic/',
            {'title': 'Generic alert', 'level': 'warning'},
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_alert_integration_model_is_removed(self):
        from ops import models as ops_models

        self.assertFalse(hasattr(ops_models, 'AlertIntegration'))

    def test_alert_sources_are_platform_owned(self):
        source_values = {value for value, _ in Alert.SOURCE_TYPE_CHOICES}

        self.assertEqual(Alert.SOURCE_PLATFORM, Alert._meta.get_field('source_type').default)
        self.assertEqual({'platform'}, source_values)


class AlertActionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('alert-operator', 'operator@example.com', 'Admin@123456')
        self.second_user = get_user_model().objects.create_superuser('backup-operator', 'backup@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)
        self.alert = Alert.objects.create(title='CPU high', level='warning', source='monitor', source_type=Alert.SOURCE_PLATFORM, message='cpu high')

    def test_claim_and_mute_alert(self):
        claim_response = self.client.post(f'/api/alerts/{self.alert.id}/claim/')
        self.assertEqual(claim_response.status_code, 200)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.claimed_by, 'alert-operator')
        self.assertEqual(self.alert.claim_records.count(), 1)

        mute_response = self.client.post(f'/api/alerts/{self.alert.id}/mute/', {'minutes': 30}, format='json')
        self.assertEqual(mute_response.status_code, 200)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, Alert.STATUS_MUTED)
        self.assertTrue(self.alert.is_suppressed)

    def test_card_action_get_only_previews_and_post_executes(self):
        token = AlertInteractionToken.objects.create(
            alert=self.alert,
            action=AlertAction.ACTION_CLAIM,
            provider='feishu',
            expires_at=timezone.now() + timedelta(days=7),
        )
        url = f'/api/alerts/card-actions/{token.token}/'

        preview = self.client.get(url)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()['action'], 'claim')
        self.assertEqual(self.alert.claim_records.count(), 0)

        confirmed = self.client.post(url)
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(self.alert.claim_records.count(), 1)
        self.assertEqual(self.alert.claim_records.first().claimant, self.user.username)

    def test_multiple_users_can_claim_same_alert(self):
        first_claim_response = self.client.post(f'/api/alerts/{self.alert.id}/claim/')
        self.assertEqual(first_claim_response.status_code, 200)

        self.client.force_authenticate(user=self.second_user)
        second_claim_response = self.client.post(f'/api/alerts/{self.alert.id}/claim/')
        self.assertEqual(second_claim_response.status_code, 200)

        detail_response = self.client.get(f'/api/alerts/{self.alert.id}/')
        self.assertEqual(detail_response.status_code, 200)
        payload = detail_response.json()
        self.assertEqual(payload['claimant_count'], 2)
        self.assertCountEqual([item['claimant'] for item in payload['claimants']], ['alert-operator', 'backup-operator'])
        self.assertTrue(payload['current_user_claimed'])

        unclaim_response = self.client.post(f'/api/alerts/{self.alert.id}/unclaim/')
        self.assertEqual(unclaim_response.status_code, 200)

        self.client.force_authenticate(user=self.user)
        detail_after_unclaim = self.client.get(f'/api/alerts/{self.alert.id}/')
        self.assertEqual(detail_after_unclaim.status_code, 200)
        payload_after_unclaim = detail_after_unclaim.json()
        self.assertEqual(payload_after_unclaim['claimant_count'], 1)
        self.assertEqual(payload_after_unclaim['claimants'][0]['claimant'], 'alert-operator')

    def test_notification_rule_can_be_configured(self):
        channel = AlertNotificationChannel.objects.create(name='email', channel_type='email', config={'to': ['ops@example.com']})
        recipient = AlertRecipient.objects.create(name='Ops', email='ops@example.com')
        group = AlertRecipientGroup.objects.create(name='oncall')
        group.recipients.add(recipient)
        response = self.client.post(
            '/api/alert-notification-rules/',
            {
                'name': 'critical notify',
                'min_level': 'warning',
                'matchers': [{'key': 'source_type', 'op': '==', 'value': Alert.SOURCE_PLATFORM}],
                'channel_ids': [channel.id],
                'recipient_group_ids': [group.id],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        policy = AlertNotificationPolicy.objects.get(name='critical notify')
        self.assertEqual(policy.channels.count(), 1)
        self.assertEqual(policy.recipient_groups.count(), 1)

    def test_recipient_group_reports_contact_health_and_policy_references(self):
        recipient = AlertRecipient.objects.create(
            name='Primary operator',
            email='primary@example.com',
            phone='13800000000',
            feishu_user_id='ou_primary',
        )
        group = AlertRecipientGroup.objects.create(name='primary-oncall')
        group.recipients.add(recipient)
        policy = AlertNotificationPolicy.objects.create(name='primary routing')
        policy.recipient_groups.add(group)

        response = self.client.get('/api/alert-recipient-groups/?page_size=200')

        self.assertEqual(response.status_code, 200)
        payload = response.json()['results'][0]
        self.assertEqual(payload['member_count'], 1)
        self.assertEqual(payload['active_member_count'], 1)
        self.assertEqual(payload['reachable_member_count'], 1)
        self.assertEqual(payload['health_status'], 'ready')
        self.assertEqual(payload['contact_coverage']['email'], 1)
        self.assertEqual(payload['contact_coverage']['phone'], 1)
        self.assertEqual(payload['contact_coverage']['feishu'], 1)
        self.assertEqual(payload['policy_count'], 1)
        self.assertEqual(payload['policy_refs'][0]['name'], 'primary routing')

    def test_enabled_recipient_group_requires_at_least_one_member(self):
        response = self.client.post(
            '/api/alert-recipient-groups/',
            {'name': 'empty-oncall', 'is_enabled': True, 'recipient_ids': [], 'user_ids': []},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('至少需要一个成员', str(response.data))

    def test_referenced_recipient_group_cannot_be_deleted(self):
        recipient = AlertRecipient.objects.create(name='Operator', email='operator@example.com')
        group = AlertRecipientGroup.objects.create(name='protected-oncall')
        group.recipients.add(recipient)
        policy = AlertNotificationPolicy.objects.create(name='protected routing')
        policy.recipient_groups.add(group)

        response = self.client.delete(f'/api/alert-recipient-groups/{group.id}/')

        self.assertEqual(response.status_code, 409)
        self.assertTrue(AlertRecipientGroup.objects.filter(pk=group.id).exists())
        self.assertEqual(response.json()['policy_refs'][0]['name'], 'protected routing')

    def test_group_member_cannot_be_deleted_until_removed_from_group(self):
        recipient = AlertRecipient.objects.create(name='Protected operator', email='protected@example.com')
        group = AlertRecipientGroup.objects.create(name='member-protection')
        group.recipients.add(recipient)

        response = self.client.delete(f'/api/alert-recipients/{recipient.id}/')

        self.assertEqual(response.status_code, 409)
        self.assertTrue(AlertRecipient.objects.filter(pk=recipient.id).exists())
        self.assertEqual(response.json()['group_refs'][0]['name'], 'member-protection')

    @patch('ops.alerting.requests.post')
    def test_feishu_business_error_is_logged_as_error(self, mock_post):
        mock_post.return_value = SimpleNamespace(status_code=200, text='{"code":19021,"msg":"sign match fail"}')
        channel = AlertNotificationChannel.objects.create(
            name='feishu',
            channel_type='feishu',
            config={'webhook_url': 'https://open.feishu.cn/open-apis/bot/v2/hook/test', 'secret': 'sign-secret'},
        )

        response = self.client.post(f'/api/alert-notification-channels/{channel.id}/test/')

        self.assertEqual(response.status_code, 200)
        log = AlertNotificationLog.objects.get(channel_id=channel.id)
        self.assertEqual(log.status, AlertNotificationLog.STATUS_ERROR)
        self.assertIn('19021', log.error_message)
        self.assertIn('sign match fail', log.error_message)
        self.assertIn('19021', log.response_body)

    @patch('ops.alerting.requests.post')
    def test_feishu_secret_adds_timestamp_and_signature(self, mock_post):
        mock_post.return_value = SimpleNamespace(status_code=200, text='{"code":0,"msg":"success"}')
        channel = AlertNotificationChannel.objects.create(
            name='feishu',
            channel_type='feishu',
            config={'webhook_url': 'https://open.feishu.cn/open-apis/bot/v2/hook/test', 'secret': 'sign-secret'},
        )

        response = self.client.post(f'/api/alert-notification-channels/{channel.id}/test/')

        self.assertEqual(response.status_code, 200)
        payload = mock_post.call_args.kwargs['json']
        self.assertIn('timestamp', payload)
        self.assertIn('sign', payload)
        self.assertRegex(str(payload['timestamp']), r'^\d{10}$')
        self.assertTrue(payload['sign'])

    @patch('ops.alerting.requests.post')
    def test_channel_test_uses_fixed_xing_cloud_test_alert(self, mock_post):
        mock_post.return_value = SimpleNamespace(status_code=200, text='{"code":0,"msg":"success"}')
        Alert.objects.create(title='Recent real alert', level='critical', source='monitor', source_type=Alert.SOURCE_PLATFORM, message='real')
        channel = AlertNotificationChannel.objects.create(
            name='feishu',
            channel_type='feishu',
            config={'webhook_url': 'https://open.feishu.cn/open-apis/bot/v2/hook/test', 'secret': 'sign-secret'},
        )

        response = self.client.post(f'/api/alert-notification-channels/{channel.id}/test/')

        self.assertEqual(response.status_code, 200)
        log = AlertNotificationLog.objects.get(channel_id=channel.id)
        self.assertEqual(log.alert.title, 'Xing-Cloud 通知渠道测试')
        self.assertEqual(log.alert.source, 'Xing-Cloud')

    @patch('ops.alerting.requests.post')
    def test_empty_notification_template_uses_semantic_alert_title(self, mock_post):
        mock_post.return_value = SimpleNamespace(status_code=200, text='{"code":0,"msg":"success"}')
        channel = AlertNotificationChannel.objects.create(
            name='feishu',
            channel_type='feishu',
            config={'webhook_url': 'https://open.feishu.cn/open-apis/bot/v2/hook/test', 'secret': 'sign-secret'},
        )
        from ops.alerting import send_alert_notification

        send_alert_notification(channel, self.alert, {'names': ['ops']}, action='fire')

        payload = mock_post.call_args.kwargs['json']
        self.assertEqual(payload['card']['header']['title']['content'], f'🔥 🟡 告警中: {self.alert.title}')

    def test_feishu_secret_is_masked_and_empty_update_keeps_existing_secret(self):
        channel = AlertNotificationChannel.objects.create(
            name='feishu',
            channel_type='feishu',
            config={'webhook_url': 'https://open.feishu.cn/open-apis/bot/v2/hook/test', 'secret': 'old-secret'},
        )

        detail = self.client.get(f'/api/alert-notification-channels/{channel.id}/')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['config']['secret'], '******')

        response = self.client.put(
            f'/api/alert-notification-channels/{channel.id}/',
            {
                'name': channel.name,
                'channel_type': channel.channel_type,
                'is_enabled': channel.is_enabled,
                'send_resolved': channel.send_resolved,
                'timeout_seconds': channel.timeout_seconds,
                'template_title': channel.template_title,
                'template_body': channel.template_body,
                'config': {'webhook_url': 'https://open.feishu.cn/open-apis/bot/v2/hook/test', 'secret': ''},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        channel.refresh_from_db()
        self.assertEqual(channel.config['secret'], 'old-secret')

    def test_feishu_channel_requires_a_signing_secret(self):
        response = self.client.post(
            '/api/alert-notification-channels/',
            {
                'name': 'unsigned-feishu',
                'channel_type': 'feishu',
                'config': {'webhook_url': 'https://open.feishu.cn/open-apis/bot/v2/hook/test'},
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('签名密钥', str(response.json()))
