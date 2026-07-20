from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from rbac.models import PermissionDefinition
from rbac.services import ensure_builtin_rbac

from ops.host_tasks import resolve_host_source_refs
from ops.models import TaskResource, TaskResourceGroup


class TaskResourceGroupApiTests(APITestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.user = get_user_model().objects.create_superuser(
            username='asset-admin',
            email='asset-admin@example.com',
            password='test-password',
        )
        self.client.force_authenticate(self.user)

    def test_tree_accepts_legacy_integer_event_environment(self):
        environment = TaskResourceGroup.objects.create(
            name='生产容器环境',
            code='prod-k8s',
            group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
            event_environment=12,
        )
        TaskResourceGroup.objects.create(
            name='容器平台',
            code='container-platform',
            group_type=TaskResourceGroup.GROUP_SYSTEM,
            parent=environment,
        )

        response = self.client.get('/api/task-resource-groups/tree/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['event_environment'], 12)
        self.assertEqual(response.data[0]['event_environment_code'], '12')
        self.assertEqual(response.data[0]['children'][0]['name'], '容器平台')

    def test_middleware_permissions_are_registered(self):
        self.assertTrue(PermissionDefinition.objects.filter(code='ops.middleware.view').exists())
        self.assertTrue(PermissionDefinition.objects.filter(code='ops.middleware.manage').exists())

        response = self.client.get('/api/middleware/overview/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['summary']['by_type']['redis'], 0)

    def test_host_resource_resolution_supports_integer_environment_reference(self):
        environment = TaskResourceGroup.objects.create(
            name='生产主机环境',
            code='prod-host',
            group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
            event_environment=18,
        )
        resource = TaskResource.objects.create(
            name='server-01',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=environment,
            ip_address='10.0.0.10',
        )

        targets = resolve_host_source_refs([{'source': 'task_resource', 'id': resource.id}])

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].event_environment, '18')

    def test_asset_can_bind_multiple_first_level_business_groups(self):
        first = TaskResourceGroup.objects.create(
            name='智能平台', code='smart-platform', group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
        )
        second = TaskResourceGroup.objects.create(
            name='共享中间件', code='shared-middleware', group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
        )

        response = self.client.post('/api/task-resources/', {
            'name': 'shared-server',
            'resource_type': 'host',
            'business_groups': [first.id, second.id],
            'ip_address': '10.0.0.20',
            'status': 'active',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        resource = TaskResource.objects.get(pk=response.data['id'])
        self.assertEqual(set(resource.business_groups.values_list('id', flat=True)), {first.id, second.id})
        self.assertEqual(resource.environment_id, first.id)
