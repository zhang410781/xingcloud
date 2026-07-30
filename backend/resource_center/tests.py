from io import StringIO
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from ops.models import (
    Alert,
    AlertNotificationChannel,
    AlertNotificationPolicy,
    AlertNotificationRoute,
    AlertRecipient,
    AlertSource,
    K8sCluster,
)
from ops.alerting import _recipient_contacts
from aiops.models import AIOpsKnowledgeEnvironment

from .discovery import collect_k8s_inventory, ensure_builtin_resource_types, execute_discovery_run, reconcile_k8s_inventory
from .models import DiscoveryRun, DiscoverySource, Resource, ResourceContact, ResourceIdentifier, ResourceRelation, ResourceSourceBinding, RuntimeResource
from .alert_matching import resource_contact_recipients


def inventory(node_name='worker-01', include_node=True):
    now = timezone.now()
    return {
        'cluster': {
            'external_id': 'cluster-uid-1', 'name': '生产集群', 'display_name': '生产集群',
            'status': 'active', 'attributes': {'kubernetes_version': 'v1.30.0'},
            'identifiers': [('k8s_uid', 'cluster-uid-1', True)],
        },
        'nodes': ([{
            'external_id': 'node-uid-1', 'name': node_name, 'display_name': node_name,
            'primary_ip': '10.0.0.10', 'status': 'active',
            'attributes': {'roles': ['worker'], 'cpu_capacity': '8'},
            'identifiers': [('k8s_uid', 'node-uid-1', True), ('ip', '10.0.0.10', False)],
        }] if include_node else []),
        'runtime': [{
            'kind': 'Pod', 'uid': 'pod-uid-1', 'namespace': 'default', 'name': 'web-1',
            'status': 'Running', 'owner_kind': 'ReplicaSet', 'owner_name': 'web-abc',
            'node_name': 'worker-01', 'attributes': {'restarts': 0},
            'expires_at': now + timedelta(minutes=30),
        }],
    }


class ResourceDiscoveryTests(TestCase):
    def setUp(self):
        ensure_builtin_resource_types()
        self.cluster = K8sCluster.objects.create(
            name='生产集群', api_server='https://k8s.example:6443', kubeconfig='apiVersion: v1', status='connected',
        )
        self.source = DiscoverySource.objects.get(k8s_cluster=self.cluster)

    def new_run(self):
        return DiscoveryRun.objects.create(source=self.source, status='reconciling')

    def test_cluster_registration_creates_discovery_source(self):
        self.assertEqual(self.source.source_type, 'k8s')
        self.assertIsNotNone(self.source.next_run_at)

    def test_reconcile_is_idempotent_and_keeps_runtime_out_of_assets(self):
        reconcile_k8s_inventory(self.new_run(), inventory())
        reconcile_k8s_inventory(self.new_run(), inventory())

        self.assertEqual(Resource.objects.filter(resource_type__code='k8s_cluster').count(), 1)
        self.assertEqual(Resource.objects.filter(resource_type__code='k8s_node').count(), 1)
        self.assertEqual(ResourceSourceBinding.objects.filter(source=self.source).count(), 2)
        self.assertEqual(ResourceRelation.objects.filter(relation_type='contains').count(), 1)
        self.assertEqual(RuntimeResource.objects.filter(kind='Pod').count(), 1)
        self.assertFalse(Resource.objects.filter(name='web-1').exists())

    def test_discovery_does_not_overwrite_manual_fields(self):
        reconcile_k8s_inventory(self.new_run(), inventory())
        node = Resource.objects.get(resource_type__code='k8s_node')
        node.display_name = '人工节点名称'
        node.product = '制品仓'
        node.manual_fields = ['display_name', 'product']
        node.save()

        reconcile_k8s_inventory(self.new_run(), inventory(node_name='worker-renamed'))
        node.refresh_from_db()
        self.assertEqual(node.display_name, '人工节点名称')
        self.assertEqual(node.product, '制品仓')
        self.assertEqual(node.name, 'worker-renamed')

    def test_node_requires_three_misses_before_missing(self):
        reconcile_k8s_inventory(self.new_run(), inventory())
        node = Resource.objects.get(resource_type__code='k8s_node')
        for expected in (1, 2):
            reconcile_k8s_inventory(self.new_run(), inventory(include_node=False))
            node.refresh_from_db()
            self.assertEqual(node.consecutive_misses, expected)
            self.assertEqual(node.status, 'active')
        reconcile_k8s_inventory(self.new_run(), inventory(include_node=False))
        node.refresh_from_db()
        self.assertEqual(node.consecutive_misses, 3)
        self.assertEqual(node.status, 'missing')

    @patch('ops.k8s_views._get_k8s_client')
    def test_runtime_api_failure_keeps_partial_inventory(self, get_k8s_client):
        metadata = lambda **kwargs: SimpleNamespace(owner_references=[], namespace='', **kwargs)
        node = SimpleNamespace(
            metadata=metadata(uid='node-uid-1', name='worker-01', labels={}),
            status=SimpleNamespace(conditions=[], addresses=[], node_info=None, capacity={}),
            spec=SimpleNamespace(provider_id='', taints=[]),
        )
        namespace = SimpleNamespace(
            metadata=metadata(uid='namespace-uid-1', name='default'),
            status=SimpleNamespace(phase='Active'),
        )
        core = MagicMock()
        core.read_namespace.return_value = SimpleNamespace(metadata=SimpleNamespace(uid='cluster-uid-1'))
        core.list_node.return_value = SimpleNamespace(items=[node])
        core.list_namespace.return_value = SimpleNamespace(items=[namespace])
        core.list_service_for_all_namespaces.side_effect = RuntimeError('service api unavailable')
        core.list_pod_for_all_namespaces.return_value = SimpleNamespace(items=[])
        apps = MagicMock()
        apps.list_deployment_for_all_namespaces.return_value = SimpleNamespace(items=[])
        apps.list_stateful_set_for_all_namespaces.return_value = SimpleNamespace(items=[])
        apps.list_daemon_set_for_all_namespaces.return_value = SimpleNamespace(items=[])
        client = MagicMock()
        client.CoreV1Api.return_value = core
        client.AppsV1Api.return_value = apps
        client.VersionApi.return_value.get_code.return_value = SimpleNamespace(git_version='v1.30.0')
        get_k8s_client.return_value = client

        direct_inventory = collect_k8s_inventory(self.source)
        self.assertEqual([item['kind'] for item in direct_inventory['runtime']], ['Namespace'])
        self.assertEqual(direct_inventory['runtime_errors'][0]['kind'], 'Service')

        run = DiscoveryRun.objects.create(source=self.source)
        execute_discovery_run(run)
        run.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(run.status, 'partial')
        self.assertEqual(self.source.status, 'degraded')
        self.assertEqual(run.summary['runtime_errors'][0]['kind'], 'Service')
        self.assertTrue(RuntimeResource.objects.filter(kind='Namespace', name='default').exists())


class ResourceApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('resource-admin', 'resource@example.com', 'Admin@123456')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.types = ensure_builtin_resource_types()
        Resource.objects.create(
            resource_type=self.types['physical_server'], name='server-01', display_name='生产主机',
            environment='prod', primary_ip='10.20.0.1', product='制品仓', source='manual',
        )

    def test_resource_list_search_and_summary(self):
        response = self.client.get('/api/resource-center/resources/', {'search': '10.20.0.1'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        summary = self.client.get('/api/resource-center/resources/summary/')
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.data['total'], 1)

    def test_k8s_cluster_api_exposes_discovery_state(self):
        cluster = K8sCluster.objects.create(
            name='独立管理集群', api_server='https://cluster.example:6443',
            kubeconfig='apiVersion: v1', status='connected',
        )
        source = DiscoverySource.objects.get(k8s_cluster=cluster)
        response = self.client.get('/api/k8s/clusters/')
        self.assertEqual(response.status_code, 200)
        rows = response.data.get('results', []) if isinstance(response.data, dict) else response.data
        row = next(item for item in rows if item['id'] == cluster.id)
        self.assertEqual(row['discovery_status'], source.status)
        self.assertEqual(row['discovered_node_count'], 0)

    def test_manual_resource_create_locks_governance_fields_on_update(self):
        resource = Resource.objects.get(name='server-01')
        response = self.client.patch(
            f'/api/resource-center/resources/{resource.id}/', {'product': '新产品', 'display_name': '新名称'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        resource.refresh_from_db()
        self.assertIn('product', resource.manual_fields)
        self.assertIn('display_name', resource.manual_fields)
        history = self.client.get(f'/api/resource-center/resources/{resource.id}/changes/')
        self.assertEqual(history.status_code, 200)
        changed_fields = {item['field'] for item in history.data if item['action'] == 'manual_update'}
        self.assertTrue({'product', 'display_name'}.issubset(changed_fields))

    def test_alert_matches_resource_by_ip_and_resolves_contacts(self):
        resource = Resource.objects.get(name='server-01')
        ResourceIdentifier.objects.create(resource=resource, kind='ip', value='10.20.0.1', scope='manual', is_primary=True)
        recipient = AlertRecipient.objects.create(name='主机运维', phone='13800000000', preferred_channels=['voice'])
        ResourceContact.objects.create(resource=resource, role='ops_owner', recipient=recipient, is_primary=True)
        alert_source = AlertSource.objects.create(
            name='统一 Zabbix', code='resource-zabbix', provider=AlertSource.PROVIDER_ZABBIX,
        )
        alert = Alert.objects.create(
            title='Redis 内存风险', level='critical', source='Zabbix', source_type=Alert.SOURCE_ZABBIX,
            message='Redis memory usage high', resource='10.20.0.1:6379', labels={'instance': '10.20.0.1:6379'},
            alert_source=alert_source,
        )
        alert.refresh_from_db()
        self.assertEqual(alert.matched_resource_id, resource.id)
        self.assertEqual(alert.resource_match_status, 'matched')
        self.assertEqual(resource_contact_recipients(resource, level='critical'), [recipient.id])
        policy = AlertNotificationPolicy.objects.create(name='按资源负责人通知', alert_source=alert_source)
        channel = AlertNotificationChannel.objects.create(name='严重告警语音', channel_type='voice')
        route = AlertNotificationRoute.objects.create(
            policy=policy,
            level='critical',
            channel=channel,
            target_type=AlertNotificationRoute.TARGET_RESOURCE_CONTACTS,
        )
        contacts = _recipient_contacts(policy=policy, route=route, alert=alert)
        self.assertEqual(contacts['phones'], ['13800000000'])

    def test_resource_contacts_follow_relation_direction_and_inheritance(self):
        resource = Resource.objects.get(name='server-01')
        product = Resource.objects.create(
            resource_type=self.types['product'], name='artifact-product', display_name='制品仓产品',
            environment='prod', source='manual',
        )
        ResourceRelation.objects.create(
            source=resource, target=product, relation_type='belongs_to', origin='manual',
        )
        inherited = AlertRecipient.objects.create(name='产品负责人', phone='13800000001')
        ResourceContact.objects.create(
            resource=product, role='product_owner', recipient=inherited, inherit_to_children=False,
        )
        self.assertNotIn(inherited.id, resource_contact_recipients(resource, level='critical'))
        ResourceContact.objects.filter(resource=product, recipient=inherited).update(inherit_to_children=True)
        self.assertIn(inherited.id, resource_contact_recipients(resource, level='critical'))
        child_contact = AlertRecipient.objects.create(name='主机运维负责人', phone='13800000002')
        ResourceContact.objects.create(
            resource=resource, role='ops_owner', recipient=child_contact, inherit_to_children=True,
        )
        self.assertNotIn(child_contact.id, resource_contact_recipients(product, level='warning'))

    def test_resource_can_bind_business_context_without_legacy_asset_group(self):
        context = AIOpsKnowledgeEnvironment.objects.create(name='支付生产', code='payment-prod')
        resource = Resource.objects.get(name='server-01')
        response = self.client.patch(
            f'/api/resource-center/resources/{resource.id}/',
            {'business_contexts': [context.id]},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['business_contexts'], [context.id])
        self.assertEqual(response.data['business_context_names'], ['支付生产'])
        options = self.client.get('/api/resource-center/resources/business-context-options/')
        self.assertEqual(options.status_code, 200)
        self.assertEqual(options.data[0]['code'], 'payment-prod')

    def test_platform_endpoint_creates_ip_identifier_for_alert_matching(self):
        response = self.client.post('/api/resource-center/resources/', {
            'resource_type': self.types['redis'].id,
            'name': 'redis-prod',
            'environment': 'prod',
            'attributes': {'endpoint': '10.20.0.9', 'port': 6379},
        }, format='json')
        self.assertEqual(response.status_code, 201)
        resource = Resource.objects.get(pk=response.data['id'])
        self.assertTrue(resource.identifiers.filter(kind='ip', value='10.20.0.9').exists())
        alert = Alert.objects.create(
            title='Redis 内存风险', level='warning', source='Zabbix', source_type=Alert.SOURCE_ZABBIX,
            resource='10.20.0.9:6379', labels={'instance': '10.20.0.9:6379'},
        )
        alert.refresh_from_db()
        self.assertEqual(alert.matched_resource_id, resource.id)

    def test_shared_endpoint_ip_is_reported_as_conflict_instead_of_reassigned(self):
        for name, port in [('redis-a', 6379), ('redis-b', 6380)]:
            response = self.client.post('/api/resource-center/resources/', {
                'resource_type': self.types['redis'].id,
                'name': name,
                'environment': 'prod',
                'attributes': {'endpoint': '10.20.0.50', 'port': port},
            }, format='json')
            self.assertEqual(response.status_code, 201)
        self.assertEqual(ResourceIdentifier.objects.filter(kind='ip', value='10.20.0.50').count(), 2)
        endpoint_alert = Alert.objects.create(
            title='Redis A 告警', level='warning', source='Zabbix', source_type=Alert.SOURCE_ZABBIX,
            resource='10.20.0.50:6379', labels={'instance': '10.20.0.50:6379'},
        )
        endpoint_alert.refresh_from_db()
        self.assertEqual(endpoint_alert.resource_match_status, 'matched')
        self.assertEqual(endpoint_alert.matched_resource.name, 'redis-a')
        alert = Alert.objects.create(
            title='共享主机 Redis 告警', level='warning', source='Zabbix', source_type=Alert.SOURCE_ZABBIX,
            resource='10.20.0.50', labels={'host_ip': '10.20.0.50'},
        )
        alert.refresh_from_db()
        self.assertEqual(alert.resource_match_status, 'conflict')
        self.assertIsNone(alert.matched_resource_id)

    def test_alert_can_be_rematched_after_resource_identifier_is_added(self):
        alert = Alert.objects.create(
            title='新增主机告警', level='warning', source='Zabbix', source_type=Alert.SOURCE_ZABBIX,
            resource='10.20.0.99', labels={'host_ip': '10.20.0.99'},
        )
        alert.refresh_from_db()
        self.assertEqual(alert.resource_match_status, 'unmatched')
        resource = Resource.objects.get(name='server-01')
        ResourceIdentifier.objects.create(
            resource=resource, kind='ip', value='10.20.0.99', scope='manual-extra', source='manual',
        )

        response = self.client.post(f'/api/alerts/{alert.id}/rematch-resource/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['resource_match_status'], 'matched')
        self.assertEqual(response.data['matched_resource'], resource.id)

    def test_contact_partial_update_uses_existing_contact_identity(self):
        resource = Resource.objects.get(name='server-01')
        contact = ResourceContact.objects.create(resource=resource, role='ops_owner', contact_name='张三')
        response = self.client.patch(
            f'/api/resource-center/contacts/{contact.id}/', {'is_primary': True}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['is_primary'])

    def test_legacy_cleanup_command_is_preview_only_without_confirm(self):
        output = StringIO()
        call_command('clear_legacy_asset_data', stdout=output)
        self.assertIn('未执行删除', output.getvalue())
