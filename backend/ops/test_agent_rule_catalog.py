from django.test import SimpleTestCase

from .alert_annotation_templates import notification_preview, render_annotation_template
from .alert_rule_catalog import (
    K8S_AGENT_RULE_TEMPLATES,
    NORMALIZED_RULE_COUNT,
    REFERENCE_RULE_COUNT,
    REFERENCE_RULE_NAMES,
)


class AgentRuleCatalogTests(SimpleTestCase):
    def test_all_reference_rules_are_mapped_once(self):
        self.assertEqual(len(K8S_AGENT_RULE_TEMPLATES), NORMALIZED_RULE_COUNT)
        self.assertEqual(len(REFERENCE_RULE_NAMES), REFERENCE_RULE_COUNT)
        self.assertEqual(len(set(REFERENCE_RULE_NAMES)), REFERENCE_RULE_COUNT)

    def test_catalog_has_required_agent_contract_fields(self):
        for item in K8S_AGENT_RULE_TEMPLATES:
            self.assertTrue(item['code'])
            self.assertTrue(item['query_config']['query'])
            self.assertIn(item['query_config']['evidence_profile'], {'light', 'targeted', 'full'})
            self.assertTrue(item['annotations']['summary'])
            self.assertTrue(item['annotations']['message'])
            self.assertTrue(item['source_rule_names'])

    def test_agent1_node_thresholds(self):
        by_code = {item['code']: item for item in K8S_AGENT_RULE_TEMPLATES}
        cpu = by_code['k8s-node-high-cpu']['condition']['levels']
        memory = by_code['k8s-node-high-memory']['condition']['levels']
        self.assertEqual([(item['level'], item['threshold']) for item in cpu], [('warning', 80), ('critical', 95)])
        self.assertEqual([(item['level'], item['threshold']) for item in memory], [('warning', 85), ('critical', 95)])

    def test_normalized_catalog_does_not_reuse_legacy_template_codes(self):
        from .alert_rule_presets import BUILTIN_ALERT_RULE_TEMPLATES, LEGACY_K8S_TEMPLATE_CODES

        codes = {item['code'] for item in K8S_AGENT_RULE_TEMPLATES}
        self.assertFalse(codes & LEGACY_K8S_TEMPLATE_CODES)
        self.assertFalse({item['code'] for item in BUILTIN_ALERT_RULE_TEMPLATES} & LEGACY_K8S_TEMPLATE_CODES)


class AlertAnnotationTemplateTests(SimpleTestCase):
    def test_labels_printf_and_percentage(self):
        text, diagnostics = render_annotation_template(
            '{{ $labels.cluster }} {{ $labels.pod }} {{ printf "%.2f" $value }} {{ $value | humanizePercentage }}',
            labels={'cluster': 'prod', 'pod': 'api-1'},
            value=0.125,
        )
        self.assertEqual(text, 'prod api-1 0.12 12.50%')
        self.assertEqual(diagnostics, [])

    def test_missing_and_unknown_variables_do_not_fail(self):
        text, diagnostics = render_annotation_template(
            '{{ $labels.namespace }}/{{ $labels.pod }} {{ unsafe }}', labels={}, value=1,
        )
        self.assertEqual(text, '-/- -')
        self.assertTrue(diagnostics)

    def test_preview_returns_impact_scope(self):
        result = notification_preview(
            name='Pod Waiting',
            annotations={'message': '{{ $labels.namespace }}/{{ $labels.pod }} {{ $labels.reason }}'},
            labels={'namespace': 'ops', 'pod': 'api-1', 'reason': 'CrashLoopBackOff'},
            value=1,
        )
        self.assertEqual(result['impact_scope'], 'ops/api-1')
        self.assertIn('CrashLoopBackOff', result['summary'])
