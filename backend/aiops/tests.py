from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from ops.models import K8sCluster, LogDataSource, MetricDataSource, TaskResource, TaskResourceGroup

from .knowledge_graph import (
    _collapse_unassigned_system_nodes,
    _configmap_runtime_links,
    resolve_knowledge_environment,
)
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
    BUILTIN_ACTION_REGISTRY,
    BUILTIN_SKILLS,
    _action_question_matches,
    _build_k8s_resource_count_answer,
    _content_conflicts_with_tool_facts,
    _detect_k8s_inspection_profile,
    _detect_k8s_resource_type,
    _ensure_builtin_model_provider,
    _is_direct_k8s_resource_lookup_question,
    _is_k8s_analysis_question,
    _is_k8s_resource_count_question,
    _json_safe_value,
    _k8s_cluster_search_context,
    _select_k8s_cluster,
    list_model_provider_presets,
    query_k8s_resources,
)


User = get_user_model()


class AIOpsConfigurationTests(TestCase):
    def test_chat_metadata_normalization_replaces_non_finite_numbers(self):
        normalized = _json_safe_value({
            'latest': float('nan'),
            'series': [float('inf'), float('-inf'), 1.5],
        })

        self.assertEqual(normalized, {'latest': None, 'series': [None, None, 1.5]})

    def test_k8s_node_count_question_uses_direct_resource_lookup(self):
        question = '当前集群有几个节点'

        self.assertEqual(_detect_k8s_resource_type(question), 'nodes')
        self.assertTrue(_is_k8s_resource_count_question(question))
        self.assertTrue(_is_direct_k8s_resource_lookup_question(question))
        self.assertTrue(_is_direct_k8s_resource_lookup_question('有几个节点'))

    def test_k8s_cluster_inspection_uses_deterministic_analysis_route(self):
        self.assertTrue(_is_k8s_analysis_question('巡检集群'))

    def test_k8s_fixed_inspection_has_separate_action_and_profiles(self):
        self.assertTrue(_action_question_matches('k8s.inspect', '巡检当前K8S集群'))
        self.assertFalse(_action_question_matches('k8s.diagnose', '巡检当前K8S集群'))
        self.assertTrue(_action_question_matches('k8s.diagnose', '排查K8S异常Pod为什么重启'))
        self.assertEqual(_detect_k8s_inspection_profile('检查 API Server 和 ETCD'), 'control_plane')
        self.assertEqual(_detect_k8s_inspection_profile('巡检 node worker-01'), 'node')
        self.assertEqual(_detect_k8s_inspection_profile('巡检 payment deployment'), 'workload')

    def test_builtin_skills_are_consolidated_and_alert_action_can_collect_k8s_evidence(self):
        skill_slugs = {item['slug'] for item in BUILTIN_SKILLS}
        self.assertIn('xing-cloud-k8s-alert-troubleshooting', skill_slugs)
        self.assertNotIn('xing-cloud-k8s-troubleshooting', skill_slugs)
        alert_action = next(item for item in BUILTIN_ACTION_REGISTRY if item['code'] == 'alert.root_cause')
        self.assertIn('query_metric_promql', alert_action['allowed_tools'])
        self.assertIn('query_k8s_cluster_summary', alert_action['allowed_tools'])
        self.assertIn('query_k8s_resources', alert_action['allowed_tools'])

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
        metric = MetricDataSource.objects.create(name='disabled-prometheus', is_enabled=False, config={})
        context = AIOpsKnowledgeEnvironment.objects.create(
            name='catalog-context', code='catalog-context', business_line='catalog', metric_datasource=metric,
        )

        response = self.client.get('/api/aiops/knowledge-environments/catalog/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('metric_datasources', response.json())
        self.assertNotIn('event_environments', response.json())
        self.assertNotIn('docker_hosts', response.json())
        item = next(row for row in response.json()['metric_datasources'] if row['id'] == metric.id)
        self.assertFalse(item['is_enabled'])
        self.assertEqual(item['bound_context']['id'], context.id)

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
            code='production',
            business_line='production',
            k8s_cluster=cluster,
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
        self.assertTrue(AIOpsModelProvider.objects.filter(name='Agnes AI').exists())

    def test_builtin_provider_bootstrap_replaces_legacy_sail_default_with_ready_agnes(self):
        legacy = AIOpsModelProvider.objects.create(
            name='智能助手体验版',
            provider_preset='sail_cloud',
            base_url='https://api.sail-cloud.com/v1',
            default_model='Qwen2.5-72B-Instruct',
            is_enabled=True,
        )
        agnes = AIOpsModelProvider.objects.create(
            name='Agnes AI',
            provider_preset='agnes_ai',
            base_url='https://apihub.agnes-ai.com/v1',
            default_model='agnes-2.0-flash',
            is_enabled=True,
        )
        agnes.set_api_key('agnes-test-key')
        agnes.save(update_fields=['api_key_encrypted'])
        config = AIOpsAgentConfig.objects.create(name='default', default_provider=legacy)

        _ensure_builtin_model_provider(config)
        config.refresh_from_db()
        legacy.refresh_from_db()

        self.assertEqual(config.default_provider_id, agnes.id)
        self.assertFalse(legacy.is_enabled)

    def test_builtin_provider_bootstrap_repairs_matching_garbled_record_in_place(self):
        provider = AIOpsModelProvider.objects.create(
            name='�������������',
            provider_preset='agnes_ai',
            base_url='https://apihub.agnes-ai.com/v1',
            default_model='agnes-2.0-flash',
            is_enabled=True,
        )
        config = AIOpsAgentConfig.objects.create(name='default', default_provider=provider)

        repaired = _ensure_builtin_model_provider(config)
        provider.refresh_from_db()
        config.refresh_from_db()

        self.assertEqual(repaired.id, provider.id)
        self.assertEqual(provider.name, 'Agnes AI')
        self.assertEqual(config.default_provider_id, provider.id)
        self.assertEqual(
            AIOpsModelProvider.objects.filter(
                base_url='https://apihub.agnes-ai.com/v1',
                default_model='agnes-2.0-flash',
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

    def test_knowledge_environment_does_not_rewrite_reusable_metric_environment(self):
        first = MetricDataSource.objects.create(name='prometheus-a', config={})
        first.environment = 'other'
        first.save(update_fields=['environment'])
        logs = LogDataSource.objects.create(name='logs-a', provider='elk', config={})
        asset_group = TaskResourceGroup.objects.create(
            name='智能平台', code='smart-platform', group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
        )
        serializer = AIOpsKnowledgeEnvironmentSerializer(data={
            'name': 'production',
            'code': 'prod',
            'business_line': 'xing-cloud',
            'metric_datasource': first.id,
            'log_datasource': logs.id,
            'task_resource_environment': asset_group.id,
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        first.refresh_from_db()
        self.assertEqual(first.environment, 'other')

    def test_knowledge_environment_can_reuse_registered_datasources(self):
        metric = MetricDataSource.objects.create(name='shared-prometheus', environment='old', config={})
        logs = LogDataSource.objects.create(name='shared-logs', provider='elk', config={})
        first_group = TaskResourceGroup.objects.create(
            name='业务一', code='business-one', group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
        )
        second_group = TaskResourceGroup.objects.create(
            name='业务二', code='business-two', group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
        )
        previous = AIOpsKnowledgeEnvironment.objects.create(
            name='previous', code='previous', business_line='xing-cloud', metric_datasource=metric,
            log_datasource=logs, task_resource_environment=first_group,
        )
        serializer = AIOpsKnowledgeEnvironmentSerializer(data={
            'name': 'next',
            'code': 'next',
            'business_line': 'xing-cloud',
            'metric_datasource': metric.id,
            'log_datasource': logs.id,
            'task_resource_environment': second_group.id,
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        current = serializer.save()
        previous.refresh_from_db()
        metric.refresh_from_db()
        self.assertEqual(previous.metric_datasource_id, metric.id)
        self.assertEqual(current.metric_datasource_id, metric.id)
        self.assertEqual(metric.environment, 'old')

    def test_knowledge_environment_single_fields_drive_legacy_lists_and_resolution(self):
        metric = MetricDataSource.objects.create(name='prometheus-prod', config={})
        logs = LogDataSource.objects.create(name='elasticsearch-prod', provider='elk', config={})
        asset_group = TaskResourceGroup.objects.create(
            name='生产业务', code='prod-business', group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
        )
        cluster = K8sCluster.objects.create(name='production-k8s', kubeconfig='')
        cluster_asset = TaskResource.objects.create(
            name='production-k8s', resource_type=TaskResource.RESOURCE_K8S,
            environment=asset_group, cluster=cluster,
        )
        cluster_asset.business_groups.add(asset_group)
        serializer = AIOpsKnowledgeEnvironmentSerializer(data={
            'name': 'production',
            'code': 'prod',
            'business_line': 'xing-cloud',
            'metric_datasource': metric.id,
            'log_datasource': logs.id,
            'task_resource_environment': asset_group.id,
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        environment = serializer.save()
        self.assertEqual(environment.metric_datasource_id, metric.id)
        self.assertEqual(environment.log_datasource_id, logs.id)
        self.assertEqual(environment.k8s_cluster_id, cluster.id)

        resolved = resolve_knowledge_environment('production')
        self.assertEqual(resolved['metric_datasource_id'], metric.id)
        self.assertEqual(resolved['log_datasource_id'], logs.id)
        self.assertEqual(resolved['metric_datasource_ids'], [metric.id])
        self.assertEqual(resolved['log_datasource_ids'], [logs.id])
        self.assertEqual(resolved['k8s_cluster_ids'], [cluster.id])

    def test_configmap_runtime_matching_is_bounded_for_large_values(self):
        component = {
            'id': 'runtime:redis',
            'name': 'Redis',
            'technology': 'Redis',
            'details': [],
        }
        configmap = {
            'name': 'orders-api-config',
            'namespace': 'production',
            'labels': {'app': 'orders-api'},
            'data': {'application.yml': ('redis:\n  host: cache\n' * 20000)},
        }

        links = _configmap_runtime_links([configmap], {'orders-api'}, {'runtime:redis': component})

        self.assertEqual(links[0]['service_name'], 'orders-api')
        self.assertEqual(links[0]['component_id'], 'runtime:redis')
