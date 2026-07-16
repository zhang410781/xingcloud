from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from cmdb.models import CIRelation, ConfigItem, ResourceNode
from ops import deployer
from ops.models import (
    Deployment,
    DeploymentApprovalFlow,
    DeploymentApprovalNode,
    DeploymentApprovalStep,
    K8sCluster,
)


class DeploymentTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('ops-admin', 'ops@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)
        self.business_line = 'retail'
        self.environment = 'test'
        self.biz_node = ResourceNode.objects.create(name=self.business_line, node_type='biz')
        ResourceNode.objects.create(name='prod', node_type='env', parent=self.biz_node)
        ResourceNode.objects.create(name='test', node_type='env', parent=self.biz_node)
        ResourceNode.objects.create(name='dev', node_type='env', parent=self.biz_node)
        self.cluster = K8sCluster.objects.create(name='demo-cluster', kubeconfig='demo')

    def release_payload(self, **overrides):
        payload = {
            'app_name': 'workorder-service',
            'business_line': self.business_line,
            'version': '2.3.1',
            'image': 'registry.internal/workorder-service:2.3.1',
            'environment': self.environment,
            'deploy_mode': 'k8s',
            'cluster': self.cluster.id,
            'namespace': 'default',
            'change_summary': 'release service',
        }
        payload.update(overrides)
        return payload


class AppReleaseApiTests(DeploymentTestCase):
    def test_docker_release_is_rejected(self):
        response = self.client.post(
            '/api/deployments/',
            self.release_payload(deploy_mode='docker_compose', cluster=None),
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_create_k8s_release_starts_as_pending_approval(self):
        response = self.client.post('/api/deployments/', self.release_payload(), format='json')
        self.assertEqual(response.status_code, 201)
        deployment = Deployment.objects.get()
        self.assertEqual(deployment.approval_status, 'pending')
        self.assertEqual(deployment.status, 'pending')
        self.assertEqual(deployment.submitter, self.user.username)
        self.assertEqual(deployment.cluster_id, self.cluster.id)
        self.assertEqual(deployment.namespace, 'default')

    @patch('ops.views.deployer.start_deployment_thread')
    def test_approve_release_starts_execution_thread(self, mock_start_thread):
        deployment = Deployment.objects.create(
            app_name='gateway', business_line=self.business_line, version='1.0.0',
            image='registry.internal/gateway:1.0.0', environment='prod', deploy_mode='k8s',
            cluster=self.cluster, namespace='gateway', submitter='dev-a',
        )
        response = self.client.post(f'/api/deployments/{deployment.id}/approve/', {'comment': 'approved'}, format='json')
        self.assertEqual(response.status_code, 200)
        deployment.refresh_from_db()
        self.assertEqual(deployment.approval_status, 'approved')
        self.assertEqual(deployment.approver, self.user.username)
        mock_start_thread.assert_called_once_with(deployment.id)

    def test_rollback_creates_new_pending_k8s_release(self):
        previous = Deployment.objects.create(
            app_name='billing-service', business_line=self.business_line, version='1.9.0',
            image='registry.internal/billing-service:1.9.0', environment='prod', deploy_mode='k8s',
            cluster=self.cluster, namespace='billing', approval_status='approved', approver='ops-a',
            status='running', execution_count=1, is_current=False,
        )
        current = Deployment.objects.create(
            app_name='billing-service', business_line=self.business_line, version='2.0.0',
            image='registry.internal/billing-service:2.0.0', environment='prod', deploy_mode='k8s',
            cluster=self.cluster, namespace='billing', approval_status='approved', approver='ops-a',
            status='running', execution_count=1, is_current=True, previous_success=previous,
        )
        response = self.client.post(f'/api/deployments/{current.id}/rollback/', {'change_summary': 'rollback'}, format='json')
        self.assertEqual(response.status_code, 201)
        rollback_release = Deployment.objects.exclude(pk__in=[previous.id, current.id]).get()
        self.assertEqual(rollback_release.action_type, 'rollback')
        self.assertEqual(rollback_release.version, '1.9.0')
        self.assertEqual(rollback_release.rollback_source_id, current.id)
        self.assertEqual(rollback_release.approval_status, 'pending')
        self.assertEqual(rollback_release.cluster_id, self.cluster.id)

    def test_create_batch_release_keeps_strategy_fields(self):
        response = self.client.post(
            '/api/deployments/',
            self.release_payload(app_name='user-center', version='3.1.0', release_strategy='batch', batch_total=3, batch_size=2),
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        deployment = Deployment.objects.get(app_name='user-center')
        self.assertEqual(deployment.release_strategy, 'batch')
        self.assertEqual(deployment.batch_total, 3)
        self.assertEqual(deployment.batch_size, 2)


class AppReleaseApprovalFlowTests(DeploymentTestCase):
    def test_create_approval_flow_via_api(self):
        response = self.client.post(
            '/api/deployment-approval-flows/',
            {
                'name': 'production two-step approval', 'environment': 'prod', 'is_active': True,
                'description': 'production release approval',
                'nodes': [
                    {'name': 'developer', 'order': 1, 'approver_type': 'user', 'approver_value': 'ops-admin'},
                    {'name': 'operator', 'order': 2, 'approver_type': 'user', 'approver_value': 'ops-admin'},
                ],
            }, format='json',
        )
        self.assertEqual(response.status_code, 201)
        flow = DeploymentApprovalFlow.objects.get()
        self.assertEqual(flow.nodes.count(), 2)
        self.assertEqual(flow.created_by, self.user.username)

    @patch('ops.views.deployer.start_deployment_thread')
    def test_multi_node_approval_progression(self, mock_start_thread):
        flow = DeploymentApprovalFlow.objects.create(name='test approval', environment='test', created_by=self.user.username, is_active=True)
        DeploymentApprovalNode.objects.create(flow=flow, name='developer', order=1, approver_type='user', approver_value='ops-admin')
        DeploymentApprovalNode.objects.create(flow=flow, name='operator', order=2, approver_type='user', approver_value='ops-admin')
        create_res = self.client.post('/api/deployments/', self.release_payload(), format='json')
        self.assertEqual(create_res.status_code, 201)
        deployment = Deployment.objects.get(app_name='workorder-service')
        self.assertEqual(deployment.approval_steps.count(), 2)
        self.assertEqual(deployment.current_approval_step.node_name, 'developer')
        first_res = self.client.post(f'/api/deployments/{deployment.id}/approve/', {'comment': 'first approved'}, format='json')
        self.assertEqual(first_res.status_code, 200)
        deployment.refresh_from_db()
        self.assertEqual(deployment.approval_status, 'pending')
        self.assertEqual(deployment.current_approval_step.node_name, 'operator')
        mock_start_thread.assert_not_called()
        second_res = self.client.post(f'/api/deployments/{deployment.id}/approve/', {'comment': 'final approved'}, format='json')
        self.assertEqual(second_res.status_code, 200)
        deployment.refresh_from_db()
        self.assertEqual(deployment.approval_status, 'approved')
        mock_start_thread.assert_called_once_with(deployment.id)

    def test_reject_on_intermediate_step_marks_release_rejected(self):
        flow = DeploymentApprovalFlow.objects.create(name='production approval', environment='prod', created_by=self.user.username, is_active=True)
        DeploymentApprovalNode.objects.create(flow=flow, name='operator', order=1, approver_type='user', approver_value='ops-admin')
        deployment = Deployment.objects.create(
            app_name='erp', business_line=self.business_line, version='5.0.0', image='registry.internal/erp:5.0.0',
            environment='prod', deploy_mode='k8s', cluster=self.cluster, namespace='erp', submitter='dev-a', approval_flow=flow,
        )
        DeploymentApprovalStep.objects.create(
            deployment=deployment, flow=flow, node_name='operator', node_order=1, approver_type='user',
            approver_value='ops-admin', is_current=True,
        )
        response = self.client.post(f'/api/deployments/{deployment.id}/reject/', {'comment': 'risk remains'}, format='json')
        self.assertEqual(response.status_code, 200)
        deployment.refresh_from_db()
        self.assertEqual(deployment.approval_status, 'rejected')
        self.assertEqual(deployment.status, 'rejected')
        self.assertEqual(deployment.approval_steps.first().status, 'rejected')


class AppReleaseRuntimeTests(DeploymentTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    @patch('ops.deployer._k8s_runtime_status')
    def test_get_service_status_returns_stale_cache_when_k8s_runtime_times_out(self, mock_k8s_runtime_status):
        deployment = Deployment.objects.create(
            app_name='workorder', business_line=self.business_line, version='2.8.0', image='registry.internal/workorder:2.8.0',
            environment='prod', deploy_mode='k8s', cluster=self.cluster, namespace='production',
            approval_status='approved', status='running', is_current=True,
        )
        mock_k8s_runtime_status.return_value = {
            'mode': 'k8s', 'summary': 'workloads: 2',
            'items': [{'kind': 'Deployment', 'name': 'workorder', 'state': 'Available', 'ready': '2/2'}],
        }
        first_payload = deployer.get_service_status(deployment)
        self.assertEqual(first_payload['summary'], 'workloads: 2')
        mock_k8s_runtime_status.side_effect = TimeoutError('connect timed out')
        cache.delete(deployer._service_status_cache_key(deployment))
        second_payload = deployer.get_service_status(deployment)
        self.assertTrue(second_payload['degraded'])
        self.assertEqual(second_payload['summary'], 'workloads: 2')

    def test_advance_batch_updates_progress(self):
        deployment = Deployment.objects.create(
            app_name='crm', business_line=self.business_line, version='1.2.0', image='registry.internal/crm:1.2.0',
            environment='prod', deploy_mode='k8s', cluster=self.cluster, namespace='crm', approval_status='approved',
            status='running', is_current=True, release_strategy='batch', batch_total=3, batch_current=1, batch_size=2,
        )
        deployer.advance_batch(deployment, actor='ops-admin', change_summary='advance second batch')
        deployment.refresh_from_db()
        self.assertEqual(deployment.batch_current, 2)
        self.assertIn('2/3', deployment.deploy_log)

    def test_sync_deployment_to_cmdb_creates_cluster_relation(self):
        deployment = Deployment.objects.create(
            app_name='member-center', business_line=self.business_line, version='2.1.0', image='registry.internal/member-center:2.1.0',
            environment='prod', deploy_mode='k8s', cluster=self.cluster, namespace='members', approval_status='approved',
            status='running', is_current=True, submitter='dev-a', deployer='ops-admin',
        )
        deployer.sync_deployment_to_cmdb(deployment)
        ci = ConfigItem.objects.get(name='member-center-prod')
        self.assertEqual(ci.business_line, self.business_line)
        self.assertEqual(ci.environment, 'prod')
        self.assertEqual(ci.status, 'active')
        self.assertEqual(ci.attributes['deployment_id'], deployment.id)
        relation = CIRelation.objects.get(source=ci, relation_type='runs_on')
        self.assertEqual(relation.target.name, self.cluster.name)
