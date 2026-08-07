import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'xing_cloud.settings')
django.setup()

from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from ops.alert_engine.detectors import (
    DETECTORS,
    detector_registry,
    normalize_detector,
    run_detector,
)
from ops.alert_engine.evaluator import _prometheus_results, _clickhouse_results
from ops.models import (
    AlertRule,
    AlertSource,
    LogDataSource,
    MetricDataSource,
)

TEST_DS_ENV = 'xing-cloud-test'


def _make_metric_datasource():
    ds, _ = MetricDataSource.objects.get_or_create(
        name='测试指标源',
        defaults={
            'provider': 'prometheus',
            'environment': TEST_DS_ENV,
            'config': {'base_url': 'http://prom.example.com'},
            'is_enabled': True,
        },
    )
    return ds


def _make_alert_source():
    src, _ = AlertSource.objects.get_or_create(
        code='test-detector-source',
        defaults={
            'name': '测试告警源',
            'provider': 'prometheus',
            'metric_datasource': _make_metric_datasource(),
            'is_enabled': True,
        },
    )
    return src


def _make_rule(**overrides):
    defaults = dict(
        name='测试规则',
        code='test-detector-rule',
        source_type='prometheus',
        alert_source=_make_alert_source(),
        is_template=False,
        is_enabled=True,
        query_config={'promql': 'up'},
        condition={'operator': '>', 'threshold': 50},
    )
    defaults.update(overrides)
    rule = AlertRule(**defaults)
    rule.save()
    return rule


class DetectorRegistryTests(TestCase):
    def test_registry_contains_threshold(self):
        self.assertIn('threshold', DETECTORS)
        self.assertTrue(DETECTORS['threshold']['implemented'])

    def test_registry_contains_planned_algorithms(self):
        for name in ('yoy', 'wow', 'sigma'):
            self.assertIn(name, DETECTORS)
            self.assertTrue(DETECTORS[name]['implemented'])

    def test_unimplemented_flagged(self):
        for name in ('ewma', 'iqr', 'isolation_forest'):
            self.assertIn(name, DETECTORS)
            self.assertFalse(DETECTORS[name]['implemented'])

    def test_registry_endpoint_payload(self):
        items = detector_registry()
        names = [item['name'] for item in items]
        self.assertIn('threshold', names)
        for item in items:
            self.assertIn('label', item)
            self.assertIn('implemented', item)

    def test_default_params_documented(self):
        self.assertEqual(DETECTORS['yoy']['params']['period'], 'day')
        self.assertEqual(DETECTORS['sigma']['params']['window_minutes'], 120)


class NormalizeDetectorTests(TestCase):
    def test_default_is_threshold(self):
        rule = _make_rule(detector={})
        name, params, fallback = normalize_detector(rule)
        self.assertEqual(name, 'threshold')
        self.assertEqual(fallback, '')

    def test_explicit_threshold(self):
        rule = _make_rule(detector={'name': 'threshold'})
        name, params, fallback = normalize_detector(rule)
        self.assertEqual(name, 'threshold')

    def test_unknown_falls_back_with_reason(self):
        rule = _make_rule(detector={'name': 'nope'})
        name, params, fallback = normalize_detector(rule)
        self.assertEqual(name, 'threshold')
        self.assertIn('nope', fallback)

    def test_unimplemented_falls_back(self):
        rule = _make_rule(detector={'name': 'iqr'})
        name, params, fallback = normalize_detector(rule)
        self.assertEqual(name, 'threshold')
        self.assertIn('iqr', fallback)

    def test_params_merged_with_defaults(self):
        rule = _make_rule(detector={'name': 'yoy', 'params': {'delta_pct': 50}})
        name, params, fallback = normalize_detector(rule)
        self.assertEqual(name, 'yoy')
        self.assertEqual(params['delta_pct'], 50)
        self.assertEqual(params['period'], 'day')
        self.assertEqual(params['operator'], '>')


class DetectorExecutionTests(TestCase):

    def setUp(self):
        cache.clear()

    def _payload(self, values, start='2026-01-01T00:00:00', end='2026-01-01T01:00:00'):
        series = [{'t': int(i * 60), 'v': value} for i, value in enumerate(values)]
        return {
            'result': [{'metric': {}, 'values': [(point['t'], str(point['v'])) for point in series]}],
        }

    def test_threshold_matches(self):
        rule = _make_rule()
        outcome = run_detector(rule, 80, context={'source_type': 'prometheus'})
        self.assertTrue(outcome['matched'])
        self.assertEqual(outcome['algorithm'], 'threshold')

    def test_threshold_not_matches(self):
        rule = _make_rule()
        outcome = run_detector(rule, 20, context={'source_type': 'prometheus'})
        self.assertFalse(outcome['matched'])

    def test_yoy_matches_when_baseline_low(self):
        rule = _make_rule(detector={'name': 'yoy'})
        payload = self._payload([10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10])
        with mock.patch('ops.observability_views.execute_promql_query', return_value=payload):
            outcome = run_detector(
                rule,
                20,
                context={
                    'rule': rule,
                    'source_type': 'prometheus',
                    'query': 'up',
                    'datasource_id': rule.alert_source.metric_datasource_id,
                    'environment': TEST_DS_ENV,
                },
            )
        self.assertTrue(outcome['matched'])
        self.assertEqual(outcome['baseline'], 10)
        self.assertEqual(outcome['delta'], 1.0)

    def test_yoy_not_matches_when_delta_small(self):
        rule = _make_rule(detector={'name': 'yoy', 'params': {'delta_pct': 30}})
        payload = self._payload([10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10])
        with mock.patch('ops.observability_views.execute_promql_query', return_value=payload):
            outcome = run_detector(
                rule,
                11,
                context={
                    'rule': rule,
                    'source_type': 'prometheus',
                    'query': 'up',
                    'datasource_id': rule.alert_source.metric_datasource_id,
                    'environment': TEST_DS_ENV,
                },
            )
        self.assertFalse(outcome['matched'])
        self.assertEqual(outcome['baseline'], 10)

    def test_yoy_empty_baseline_no_false_positive(self):
        rule = _make_rule(detector={'name': 'yoy'})
        payload = {'result': []}
        with mock.patch('ops.observability_views.execute_promql_query', return_value=payload):
            outcome = run_detector(
                rule,
                500,
                context={
                    'rule': rule,
                    'source_type': 'prometheus',
                    'query': 'up',
                    'datasource_id': rule.alert_source.metric_datasource_id,
                    'environment': TEST_DS_ENV,
                },
            )
        self.assertFalse(outcome['matched'])
        self.assertIsNone(outcome['baseline'])

    def test_yoy_operator_downward(self):
        rule = _make_rule(detector={'name': 'yoy', 'params': {'operator': '<', 'delta_pct': 20}})
        payload = self._payload([100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100])
        with mock.patch('ops.observability_views.execute_promql_query', return_value=payload):
            outcome = run_detector(
                rule,
                50,
                context={
                    'rule': rule,
                    'source_type': 'prometheus',
                    'query': 'up',
                    'datasource_id': rule.alert_source.metric_datasource_id,
                    'environment': TEST_DS_ENV,
                },
            )
        self.assertTrue(outcome['matched'])
        self.assertEqual(outcome['delta'], -0.5)

    def test_wow_matches(self):
        rule = _make_rule(detector={'name': 'wow'})
        payload = self._payload([20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20])
        with mock.patch('ops.observability_views.execute_promql_query', return_value=payload):
            outcome = run_detector(
                rule,
                30,
                context={
                    'rule': rule,
                    'source_type': 'prometheus',
                    'query': 'up',
                    'datasource_id': rule.alert_source.metric_datasource_id,
                    'environment': TEST_DS_ENV,
                },
            )
        self.assertTrue(outcome['matched'])
        self.assertEqual(outcome['baseline'], 20)
        self.assertEqual(outcome['delta'], 0.5)

    def test_sigma_matches_when_outlier(self):
        rule = _make_rule(detector={'name': 'sigma'})
        samples = [10, 12, 11, 13, 10, 12, 11, 13, 10, 12, 11, 13, 10, 12, 11, 13, 10, 12]
        payload = {'result': [{'metric': {}, 'values': [(i, str(v)) for i, v in enumerate(samples)]}]}
        with mock.patch('ops.observability_views.execute_promql_query', return_value=payload):
            outcome = run_detector(
                rule,
                1000,
                context={
                    'rule': rule,
                    'source_type': 'prometheus',
                    'query': 'up',
                    'datasource_id': rule.alert_source.metric_datasource_id,
                    'environment': TEST_DS_ENV,
                },
            )
        self.assertTrue(outcome['matched'])

    def test_sigma_insufficient_samples_no_false_positive(self):
        rule = _make_rule(detector={'name': 'sigma'})
        payload = {'result': [{'metric': {}, 'values': [(i, '10') for i in range(5)]}]}
        with mock.patch('ops.observability_views.execute_promql_query', return_value=payload):
            outcome = run_detector(
                rule,
                1000,
                context={
                    'rule': rule,
                    'source_type': 'prometheus',
                    'query': 'up',
                    'datasource_id': rule.alert_source.metric_datasource_id,
                    'environment': TEST_DS_ENV,
                },
            )
        self.assertFalse(outcome['matched'])
        self.assertIn('样本不足', outcome['detail'])

    def test_non_prometheus_falls_back_to_threshold(self):
        rule = _make_rule(detector={'name': 'yoy'})
        outcome = run_detector(
            rule,
            80,
            context={'source_type': 'clickhouse', 'rule': rule, 'query': '', 'datasource_id': '', 'environment': ''},
        )
        self.assertEqual(outcome['algorithm'], 'threshold')
        self.assertIn('非 Prometheus', outcome['detail'])
        self.assertTrue(outcome['matched'])

    def test_query_error_falls_back_without_false_positive(self):
        rule = _make_rule(detector={'name': 'yoy'})
        with mock.patch('ops.observability_views.execute_promql_query', side_effect=RuntimeError('boom')):
            outcome = run_detector(
                rule,
                20,
                context={
                    'rule': rule,
                    'source_type': 'prometheus',
                    'query': 'up',
                    'datasource_id': rule.alert_source.metric_datasource_id,
                    'environment': TEST_DS_ENV,
                },
            )
        self.assertEqual(outcome['algorithm'], 'threshold')
        self.assertIn('boom', outcome['detail'])
        self.assertFalse(outcome['matched'])


class EvaluatorIntegrationTests(TestCase):

    def setUp(self):
        cache.clear()

    def test_prometheus_results_carry_detector_evidence(self):
        rule = _make_rule()
        datasource = rule.alert_source.metric_datasource
        vector_payload = {
            'result': [{'metric': {'__name__': 'up', 'instance': '10.0.0.1'}, 'value': (1735689600, '80')}],
        }
        with mock.patch(
            'ops.alert_engine.evaluator.execute_promql_query',
            return_value=vector_payload,
        ):
            results = _prometheus_results(rule)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertTrue(result['matched'])
        self.assertEqual(result['evidence']['detector']['algorithm'], 'threshold')
        self.assertEqual(result['evidence']['detector']['matched'], True)

    def test_prometheus_yoy_detector_routes(self):
        rule = _make_rule(detector={'name': 'yoy', 'params': {'delta_pct': 20}})
        datasource = rule.alert_source.metric_datasource

        def fake_query(query, **kwargs):
            if kwargs.get('range_query'):
                return {'result': [{'metric': {}, 'values': [(i, '10') for i in range(12)]}]}
            return {'result': [{'metric': {'__name__': 'up', 'instance': '10.0.0.1'}, 'value': (1735689600, '30')}]}

        with mock.patch('ops.observability_views.execute_promql_query', side_effect=fake_query), \
             mock.patch('ops.alert_engine.evaluator.execute_promql_query', side_effect=fake_query):
            results = _prometheus_results(rule)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertTrue(result['matched'])
        self.assertEqual(result['evidence']['detector']['algorithm'], 'yoy')
        self.assertEqual(result['evidence']['detector']['baseline'], 10)

    def test_clickhouse_results_fallback_detector(self):
        rule = _make_rule(
            source_type='clickhouse',
            detector={'name': 'yoy'},
            query_config={'collection': 'container-logs', 'log_datasource_id': None},
        )
        LogDataSource.objects.get_or_create(
            name='测试日志源',
            defaults={
                'provider': 'clickhouse',
                'is_enabled': True,
                'config': {'endpoint': 'http://ch.example.com', 'database': 'logs', 'tables': {'container-logs': {}}},
            },
        )
        with mock.patch('ops.alert_engine.evaluator._clickhouse_request', return_value={'data': [{'value': '80'}]}):
            results = _clickhouse_results(rule, collection_key='container-logs')
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertTrue(result['matched'])
        self.assertEqual(result['evidence']['detector']['algorithm'], 'threshold')
        self.assertIn('非 Prometheus', result['evidence']['detector']['detail'])
