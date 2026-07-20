from unittest.mock import patch

from django.test import TestCase

from ops.alert_engine.evaluator import evaluate_rule
from ops.inspection_reports import _inspection_change_summary
from ops.models import AlertRule


class AlertRuleQualityTests(TestCase):
    @patch('ops.alert_engine.evaluator.process_rule_results')
    @patch('ops.alert_engine.evaluator._prometheus_results')
    def test_successful_evaluation_records_runtime_quality(self, results, process):
        rule = AlertRule.objects.create(
            name='quality rule', code='quality-rule', source_type='prometheus',
            is_enabled=True, notify_enabled=False,
        )
        results.return_value = [{'matched': True, 'labels': {'pod': 'api-1'}, 'value': 91}]
        process.return_value = {
            'matched_count': 1, 'would_fire_count': 1, 'resolved_count': 0,
            'results': [{'matched': True, 'labels': {'pod': 'api-1'}}],
        }

        response = evaluate_rule(rule)

        self.assertTrue(response['success'])
        rule.refresh_from_db()
        self.assertEqual(rule.last_matched_count, 1)
        self.assertEqual(rule.trigger_count, 1)
        self.assertEqual(rule.last_matched_resource, 'api-1')
        self.assertEqual(rule.consecutive_error_count, 0)

    @patch('ops.alert_engine.evaluator._prometheus_results', side_effect=RuntimeError('query failed'))
    def test_failed_evaluation_records_error_quality(self, results):
        rule = AlertRule.objects.create(
            name='failed quality rule', code='failed-quality-rule', source_type='prometheus',
            is_enabled=True,
        )

        response = evaluate_rule(rule)

        self.assertFalse(response['success'])
        rule.refresh_from_db()
        self.assertEqual(rule.evaluation_error_count, 1)
        self.assertEqual(rule.consecutive_error_count, 1)
        self.assertIn('query failed', rule.last_evaluation_error)


class InspectionChangeSummaryTests(TestCase):
    def test_identifies_added_resolved_and_worsened_findings(self):
        previous = {'findings': [
            {'code': 'pod-restart', 'target': 'api-1', 'severity': 'warning'},
            {'code': 'disk', 'target': 'node-1', 'severity': 'warning'},
        ]}
        current = {'findings': [
            {'code': 'pod-restart', 'target': 'api-1', 'severity': 'critical'},
            {'code': 'node-ready', 'target': 'node-2', 'severity': 'warning'},
        ]}

        change = _inspection_change_summary(previous, current)

        self.assertTrue(change['has_changes'])
        self.assertEqual(change['summary'], {'added': 1, 'resolved': 1, 'worsened': 1})
