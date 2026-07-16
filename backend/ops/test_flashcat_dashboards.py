from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from ops.dashboard_presets import BUILTIN_DASHBOARDS
from ops.log_views import _query_elk
from ops.observability_views import (
    _dashboard_prometheus_panel,
    _native_apply_node_filter,
    _native_metric_label,
)


class FlashcatDashboardTests(TestCase):
    def test_k8s_preset_matches_grafana_grid(self):
        dashboard = next(item for item in BUILTIN_DASHBOARDS if item['title'] == 'K8S Cluster Health')
        self.assertEqual(dashboard['layout']['columns'], 24)
        self.assertEqual(len(dashboard['panels']), 25)
        self.assertTrue(all(panel['options']['grid'].get('w') for panel in dashboard['panels']))

    def test_grafana_legend_template_is_rendered(self):
        self.assertEqual(_native_metric_label({'instance': 'node-1:9100'}, '{{instance}} 接收'), 'node-1:9100 接收')

    def test_kube_node_filter_uses_node_label(self):
        query = _native_apply_node_filter('sum(kube_node_status_allocatable{resource="cpu"})', ['worker-1'])
        self.assertIn('node=~"worker-1"', query)

    @patch('ops.observability_views._native_prometheus_panel')
    def test_prometheus_panel_combines_multiple_targets(self, execute):
        execute.side_effect = [
            {'series': [{'name': 'read', 'points': [[1, 2]], 'value': 2}]},
            {'series': [{'name': 'write', 'points': [[1, 3]], 'value': 3}]},
        ]
        panel = SimpleNamespace(
            key='io', title='I/O', chart_type='timeseries',
            options={'unit': 'Bps', 'grid': {'x': 0, 'y': 0, 'w': 12, 'h': 8}},
            targets=[{'ref_id': 'A', 'query': 'read'}, {'ref_id': 'B', 'query': 'write'}],
        )
        response = _dashboard_prometheus_panel(panel, {}, 1, 2)
        self.assertEqual([item['name'] for item in response['data']['series']], ['read', 'write'])
        self.assertEqual([item['ref_id'] for item in response['data']['targets']], ['A', 'B'])

    @patch('ops.log_views._elk_request')
    def test_elk_logs_expose_canonical_kubernetes_fields(self, request):
        request.return_value = {
            'took': 3,
            'hits': {
                'total': {'value': 1},
                'hits': [{
                    '_index': 'k8s-2026.07.15',
                    '_source': {
                        '@timestamp': '2026-07-15T07:00:00Z',
                        'message': 'request failed',
                        'kubernetes': {
                            'namespace_name': 'prod', 'pod_name': 'api-1',
                            'container_name': 'api', 'host': 'worker-1',
                        },
                    },
                }],
            },
        }
        result = _query_elk(
            {'endpoint': 'http://elasticsearch', 'index_pattern': 'k8s-*'},
            {'source': 'k8s-*', 'start_ms': 1, 'end_ms': 2, 'limit': 10},
        )
        log = result['logs'][0]
        self.assertEqual((log['namespace'], log['pod'], log['host']), ('prod', 'api-1', 'worker-1'))
