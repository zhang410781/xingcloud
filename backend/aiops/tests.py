from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from ops.models import LogDataSource, MetricDataSource

from .knowledge_graph import resolve_knowledge_environment
from .models import AIOpsAgentConfig, AIOpsKnowledgeEnvironment, AIOpsModelInvocation, AIOpsModelProvider
from .serializers import AIOpsKnowledgeEnvironmentSerializer
from .services import _ensure_builtin_model_provider, list_model_provider_presets


User = get_user_model()


class AIOpsConfigurationTests(TestCase):
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
