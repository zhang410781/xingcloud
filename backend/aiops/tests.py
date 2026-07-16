from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from ops.models import K8sCluster, LogDataSource, MetricDataSource

from .knowledge_graph import _collapse_unassigned_system_nodes, resolve_knowledge_environment
from .models import (
    AIOpsAgentConfig,
    AIOpsChatMessage,
    AIOpsChatSession,
    AIOpsKnowledgeEnvironment,
    AIOpsModelInvocation,
    AIOpsModelProvider,
)
from .serializers import AIOpsKnowledgeEnvironmentSerializer
from .services import (
    _build_k8s_resource_count_answer,
    _content_conflicts_with_tool_facts,
    _detect_k8s_resource_type,
    _ensure_builtin_model_provider,
    _is_direct_k8s_resource_lookup_question,
    _is_k8s_analysis_question,
    _is_k8s_resource_count_question,
    _k8s_cluster_search_context,
    _select_k8s_cluster,
    list_model_provider_presets,
    query_k8s_resources,
)


User = get_user_model()


class AIOpsConfigurationTests(TestCase):
    def test_k8s_node_count_question_uses_direct_resource_lookup(self):
        question = '当前集群有几个节点'

        self.assertEqual(_detect_k8s_resource_type(question), 'nodes')
        self.assertTrue(_is_k8s_resource_count_question(question))
        self.assertTrue(_is_direct_k8s_resource_lookup_question(question))
        self.assertTrue(_is_direct_k8s_resource_lookup_question('有几个节点'))

    def test_k8s_cluster_inspection_uses_deterministic_analysis_route(self):
        self.assertTrue(_is_k8s_analysis_question('巡检集群'))

    def test_k8s_cluster_inspection_uses_single_environment_cluster_without_name_matching(self):
        scoped_query, cluster_query, tokens = _k8s_cluster_search_context(
            '数智管理平台 巡检集群',
            {'name': '数智管理平台', 'k8s_cluster_ids': [12]},
            cluster_name='数智管理平台',
        )

        self.assertEqual(scoped_query, '巡检集群')
        self.assertEqual(cluster_query, '数智管理平台')
        self.assertEqual(tokens, [])

    def test_k8s_cluster_selection_requires_name_when_environment_has_multiple_clusters(self):
        first = K8sCluster.objects.create(name='production-k8s', kubeconfig='')
        second = K8sCluster.objects.create(name='staging-k8s', kubeconfig='')
        cluster, candidates, selection_required = _select_k8s_cluster(
            K8sCluster.objects.filter(id__in=[first.id, second.id]),
            tokens=[],
        )

        self.assertIsNone(cluster)
        self.assertTrue(selection_required)
        self.assertEqual({item.name for item in candidates}, {'production-k8s', 'staging-k8s'})

    def test_k8s_cluster_selection_uses_explicit_cluster_name(self):
        first = K8sCluster.objects.create(name='production-k8s', kubeconfig='')
        second = K8sCluster.objects.create(name='staging-k8s', kubeconfig='')
        cluster, _, selection_required = _select_k8s_cluster(
            K8sCluster.objects.filter(id__in=[first.id, second.id]),
            cluster_name='staging',
        )

        self.assertEqual(cluster, second)
        self.assertFalse(selection_required)

    @patch('aiops.services._load_k8s_nodes')
    @patch('aiops.services._resolve_knowledge_environment_for_query')
    def test_k8s_resource_query_prefers_single_bound_cluster_over_wrong_model_cluster_name(self, resolve_environment, load_nodes):
        user = User.objects.create_superuser(username='k8s-query-admin', password='Admin@123456')
        cluster = K8sCluster.objects.create(name='数智平台', kubeconfig='')
        session = AIOpsChatSession.objects.create(user=user)
        message = AIOpsChatMessage.objects.create(
            session=session,
            role=AIOpsChatMessage.ROLE_USER,
            content='集群有几个节点',
        )
        resolve_environment.return_value = {
            'name': '数智管理平台',
            'k8s_cluster_ids': [cluster.id],
        }
        load_nodes.return_value = [
            {'name': 'node-1', 'status': 'Ready'},
            {'name': 'node-2', 'status': 'Ready'},
        ]

        result = query_k8s_resources(
            session,
            message,
            user,
            query='数智管理平台 集群有几个节点',
            resource_type='nodes',
            cluster_name='数智管理平台',
        )

        self.assertEqual(result['summary']['cluster_name'], '数智平台')
        self.assertEqual(result['summary']['count'], 2)
        self.assertEqual(result['summary']['ready_count'], 2)

    def test_k8s_node_count_answer_is_deterministic(self):
        content = _build_k8s_resource_count_answer({
            'summary': {
                'count': 4,
                'cluster_name': 'production-k8s',
                'resource_type': 'nodes',
                'ready_count': 3,
                'not_ready_count': 1,
                'error': '',
            },
        })

        self.assertIn('production-k8s 当前共有 4 个节点', content)
        self.assertIn('Ready：3 个；NotReady：1 个', content)

    def test_k8s_formatter_cannot_discard_returned_cluster_summary(self):
        conflicts = _content_conflicts_with_tool_facts(
            '结论：当前工具未返回摘要数据，无法进行集群巡检。',
            [{
                'tool_name': 'query_k8s_cluster_summary',
                'tool_output': {
                    'summary': {
                        'cluster_name': 'production-k8s',
                        'nodes_total': 4,
                        'nodes_ready': 4,
                        'pods_total': 20,
                        'pods_abnormal': 0,
                    },
                },
            }],
        )

        self.assertTrue(conflicts)

    def test_knowledge_graph_collapses_unassigned_system_into_environment_service_edge(self):
        nodes = {
            'environment:production': {
                'id': 'environment:production',
                'kind': 'environment',
                'label': 'production',
                'environment': 'production',
            },
            'system:production:未归属系统': {
                'id': 'system:production:未归属系统',
                'kind': 'system',
                'label': '未归属系统',
                'system_name': '未归属系统',
                'environment': 'production',
            },
            'service:production:未归属系统:api': {
                'id': 'service:production:未归属系统:api',
                'kind': 'service',
                'label': 'api',
                'service': 'api',
                'system_name': '未归属系统',
                'business_line': '未归属系统',
                'environment': 'production',
            },
        }
        edges = {
            'environment-system': {
                'id': 'environment-system',
                'source': 'environment:production',
                'target': 'system:production:未归属系统',
                'label': '包含系统',
                'relation': 'environment_system',
                'weight': 1,
            },
            'system-service': {
                'id': 'system-service',
                'source': 'system:production:未归属系统',
                'target': 'service:production:未归属系统:api',
                'label': '承载服务',
                'relation': 'system_service',
                'weight': 2,
            },
        }

        collapsed_nodes, collapsed_edges = _collapse_unassigned_system_nodes(nodes, edges)

        self.assertNotIn('system:production:未归属系统', collapsed_nodes)
        self.assertEqual(collapsed_nodes['service:production:未归属系统:api']['system_name'], '')
        self.assertTrue(any(
            edge['source'] == 'environment:production'
            and edge['target'] == 'service:production:未归属系统:api'
            and edge['relation'] == 'environment_service'
            for edge in collapsed_edges.values()
        ))

    def test_knowledge_environment_catalog_works_without_event_wall_models(self):
        user = User.objects.create_superuser(username='catalog-admin', password='Admin@123456')
        self.client.force_login(user)

        response = self.client.get('/api/aiops/knowledge-environments/catalog/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('metric_datasources', response.json())
        self.assertNotIn('event_environments', response.json())
        self.assertNotIn('docker_hosts', response.json())

    def test_knowledge_graph_works_after_event_wall_retirement(self):
        cache.clear()
        user = User.objects.create_superuser(username='graph-admin', password='Admin@123456')
        self.client.force_login(user)

        response = self.client.get('/api/aiops/knowledge-graph/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('nodes', payload)
        self.assertIn('edges', payload)
        capability_ids = {
            item.get('id') for item in payload['nodes'] if item.get('kind') == 'capability'
        }
        self.assertNotIn('capability:internal_events', capability_ids)
        self.assertNotIn('capability:external_events', capability_ids)

    def test_knowledge_graph_environment_works_after_marketplace_retirement(self):
        cache.clear()
        user = User.objects.create_superuser(username='environment-graph-admin', password='Admin@123456')
        self.client.force_login(user)
        cluster = K8sCluster.objects.create(name='production-k8s', kubeconfig='')
        AIOpsKnowledgeEnvironment.objects.create(
            name='production',
            k8s_cluster_ids=[cluster.id],
            is_enabled=True,
            is_default=True,
        )

        response = self.client.get('/api/aiops/knowledge-graph/', {'environment': 'production'})

        self.assertEqual(response.status_code, 200)
        self.assertIn('nodes', response.json())

    def test_alert_analysis_invocation_purpose_has_chinese_label(self):
        invocation = AIOpsModelInvocation(purpose=AIOpsModelInvocation.PURPOSE_ALERT_ANALYSIS)

        self.assertEqual(invocation.get_purpose_display(), '告警研判')

    def test_agnes_provider_preset_is_available_without_credentials(self):
        presets = {item['key']: item for item in list_model_provider_presets()}

        self.assertIn('sail_cloud', presets)
        self.assertEqual(presets['agnes_ai']['name'], 'Agnes AI')
        self.assertEqual(presets['agnes_ai']['base_url'], 'https://apihub.agnes-ai.com/v1')
        self.assertEqual(presets['agnes_ai']['default_model'], 'agnes-2.0-flash')
        self.assertNotIn('api_key', presets['agnes_ai'])

    def test_builtin_provider_bootstrap_preserves_existing_default(self):
        provider = AIOpsModelProvider.objects.create(
            name='Existing Provider',
            base_url='https://model.example/v1',
            default_model='existing-model',
            is_enabled=True,
        )
        config = AIOpsAgentConfig.objects.create(name='default', default_provider=provider)

        _ensure_builtin_model_provider(config)
        config.refresh_from_db()

        self.assertEqual(config.default_provider_id, provider.id)
        self.assertTrue(AIOpsModelProvider.objects.filter(name='智能助手体验版').exists())

    def test_builtin_provider_bootstrap_repairs_matching_garbled_record_in_place(self):
        provider = AIOpsModelProvider.objects.create(
            name='�������������',
            provider_preset='sail_cloud',
            base_url='https://api.sail-cloud.com/v1',
            default_model='Qwen2.5-72B-Instruct',
            is_enabled=True,
        )
        config = AIOpsAgentConfig.objects.create(name='default', default_provider=provider)

        repaired = _ensure_builtin_model_provider(config)
        provider.refresh_from_db()
        config.refresh_from_db()

        self.assertEqual(repaired.id, provider.id)
        self.assertEqual(provider.name, '智能助手体验版')
        self.assertEqual(config.default_provider_id, provider.id)
        self.assertEqual(
            AIOpsModelProvider.objects.filter(
                base_url='https://api.sail-cloud.com/v1',
                default_model='Qwen2.5-72B-Instruct',
            ).count(),
            1,
        )

    def test_skill_marketplace_collection_action(self):
        user = User.objects.create_superuser(username='aiops-admin', password='Admin@123456')
        self.client.force_login(user)
        payload = {'summary': {'total': 1}, 'items': [{'slug': 'diagnose'}]}

        with patch('aiops.views.build_skill_marketplace_catalog', return_value=payload) as catalog:
            response = self.client.get('/api/aiops/admin/skills/marketplace/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)
        catalog.assert_called_once_with(user=user)

    def test_knowledge_environment_rejects_multiple_datasources(self):
        first = MetricDataSource.objects.create(name='prometheus-a', config={})
        second = MetricDataSource.objects.create(name='prometheus-b', config={})
        serializer = AIOpsKnowledgeEnvironmentSerializer(data={
            'name': 'production',
            'metric_datasource_ids': [first.id, second.id],
        })

        self.assertFalse(serializer.is_valid())
        self.assertIn('metric_datasource_ids', serializer.errors)

    def test_knowledge_environment_single_fields_drive_legacy_lists_and_resolution(self):
        metric = MetricDataSource.objects.create(name='prometheus-prod', config={})
        logs = LogDataSource.objects.create(name='elasticsearch-prod', provider='elk', config={})
        serializer = AIOpsKnowledgeEnvironmentSerializer(data={
            'name': 'production',
            'metric_datasource': metric.id,
            'log_datasource': logs.id,
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        environment = serializer.save()
        self.assertEqual(environment.metric_datasource_ids, [metric.id])
        self.assertEqual(environment.log_datasource_ids, [logs.id])

        resolved = resolve_knowledge_environment('production')
        self.assertEqual(resolved['metric_datasource_id'], metric.id)
        self.assertEqual(resolved['log_datasource_id'], logs.id)
        self.assertEqual(resolved['metric_datasource_ids'], [metric.id])
        self.assertEqual(resolved['log_datasource_ids'], [logs.id])
