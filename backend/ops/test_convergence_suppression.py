import uuid
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from ops.alert_convergence import (
    convergence_group_key,
    converge_resolved_alert,
    find_window_group_root,
    promote_or_attach,
)
from ops.alert_engine.pipeline import process_rule_results
from ops.models import Alert, AlertAction, AlertRule, AlertRuleState, AlertSource
from resource_center.alert_matching import (
    ancestor_resource_ids,
    apply_topology_suppression,
    check_topology_suppression,
    descendant_resource_ids,
    release_topology_suppression,
)
from resource_center.models import Resource, ResourceRelation, ResourceType


def _rule(**overrides):
    values = dict(
        name='收敛测试规则',
        code=f'converge-test-{uuid.uuid4().hex[:8]}',
        source_type='prometheus',
        level='warning',
        duration_seconds=0,
        notify_enabled=False,
        auto_analyze=False,
        query_config={'query': 'up'},
    )
    values.update(overrides)
    return AlertRule.objects.create(**values)


def _result(rule, pod, value=1.0, level=None, namespace='kube-ai'):
    return {
        'matched': True,
        'value': value,
        'title': rule.name,
        'message': f'{pod} 指标异常 value={value}',
        'level': level,
        'labels': {
            'environment': 'prod',
            'metric_datasource_id': '1',
            'cluster': 'cluster-a',
            'namespace': namespace,
            'pod': pod,
            'container': 'app',
        },
    }


class ConvergenceBasicsTests(TestCase):
    def setUp(self):
        self.rule = _rule(converge_enabled=True, group_fields=['environment', 'namespace'])

    def test_second_instance_attaches_to_root(self):
        first = process_rule_results(self.rule, [_result(self.rule, 'pod-a')])
        second = process_rule_results(self.rule, [_result(self.rule, 'pod-b')])
        self.assertEqual(first['created_count'], 1)
        self.assertEqual(second['created_count'], 1)
        roots = Alert.objects.filter(is_group_root=True)
        self.assertEqual(roots.count(), 1)
        root = roots.get()
        self.assertEqual(root.occurrence_count, 2)
        self.assertEqual(root.group_children.exclude(is_group_root=True).count(), 1)

    def test_group_fields_partition_instances(self):
        process_rule_results(self.rule, [_result(self.rule, 'pod-a')])
        process_rule_results(self.rule, [_result(self.rule, 'pod-b', namespace='kube-system')])
        self.assertEqual(Alert.objects.filter(is_group_root=True).count(), 2)

    def test_root_takes_max_level_and_latest_labels(self):
        process_rule_results(self.rule, [_result(self.rule, 'pod-a', level='warning')])
        process_rule_results(self.rule, [_result(self.rule, 'pod-b', level='critical')])
        root = Alert.objects.get(is_group_root=True)
        self.assertEqual(root.level, 'critical')

    def test_window_boundary_creates_new_root(self):
        process_rule_results(self.rule, [_result(self.rule, 'pod-a')])
        root = Alert.objects.get(is_group_root=True)
        Alert.objects.filter(pk=root.pk).update(
            created_at=timezone.now() - timezone.timedelta(minutes=10),
        )
        process_rule_results(self.rule, [_result(self.rule, 'pod-c')])
        self.assertEqual(Alert.objects.filter(is_group_root=True).count(), 2)

    def test_repeat_same_fingerprint_does_not_inflate_occurrence(self):
        process_rule_results(self.rule, [_result(self.rule, 'pod-a')])
        process_rule_results(self.rule, [_result(self.rule, 'pod-a')])
        process_rule_results(self.rule, [_result(self.rule, 'pod-b')])
        root = Alert.objects.get(is_group_root=True)
        self.assertEqual(root.occurrence_count, 2)

    def test_disabled_convergence_keeps_legacy_behavior(self):
        rule = _rule(converge_enabled=False)
        process_rule_results(rule, [_result(rule, 'pod-a')])
        process_rule_results(rule, [_result(rule, 'pod-b')])
        self.assertEqual(Alert.objects.filter(is_group_root=True).count(), 0)
        self.assertEqual(Alert.objects.count(), 2)


class ConvergenceResolveTests(TestCase):
    def setUp(self):
        self.rule = _rule(converge_enabled=True, group_fields=['environment', 'namespace'])

    def test_partial_resolve_keeps_root_active(self):
        process_rule_results(self.rule, [_result(self.rule, 'pod-a'), _result(self.rule, 'pod-b')])
        root = Alert.objects.get(is_group_root=True)
        process_rule_results(self.rule, [_result(self.rule, 'pod-a')])
        process_rule_results(self.rule, [])
        root.refresh_from_db()
        self.assertEqual(root.status, Alert.STATUS_ACTIVE)

    def test_all_resolved_after_two_misses(self):
        process_rule_results(self.rule, [_result(self.rule, 'pod-a'), _result(self.rule, 'pod-b')])
        root = Alert.objects.get(is_group_root=True)
        process_rule_results(self.rule, [])
        process_rule_results(self.rule, [])
        root.refresh_from_db()
        self.assertEqual(root.status, Alert.STATUS_RESOLVED)
        self.assertIsNotNone(root.ends_at)

    def test_root_resolved_notifies_once(self):
        self.rule.notify_enabled = True
        self.rule.save(update_fields=['notify_enabled'])
        with patch('ops.alert_engine.pipeline.dispatch_alert_batch_notifications', return_value={'notification_logs': [], 'storm_batches': []}) as dispatch:
            process_rule_results(self.rule, [_result(self.rule, 'pod-a'), _result(self.rule, 'pod-b')])
            process_rule_results(self.rule, [])
            process_rule_results(self.rule, [])
        fire_calls = [
            call for call in dispatch.call_args_list
            if call.kwargs.get('action') == 'fire'
        ]
        resolved_calls = [
            call for call in dispatch.call_args_list
            if call.kwargs.get('action') == 'resolved'
        ]
        self.assertEqual(len(fire_calls), 1)
        self.assertEqual(len(resolved_calls), 1)


class TopologySuppressionTests(TestCase):
    def setUp(self):
        node_type = ResourceType.objects.create(code='node', name='节点')
        pod_type = ResourceType.objects.create(code='pod', name='Pod')
        self.node = Resource.objects.create(resource_type=node_type, name='node-1')
        self.pod = Resource.objects.create(resource_type=pod_type, name='pod-1')
        ResourceRelation.objects.create(
            source=self.node, target=self.pod, relation_type='contains',
        )
        self.rule = _rule(suppress_by_topology=True, suppress_ancestor_hops=3)
        self.pod_alert = Alert.objects.create(
            title='pod 异常', level='warning', status=Alert.STATUS_ACTIVE,
            source='test', source_type=Alert.SOURCE_PLATFORM,
            resource='pod-1', resource_type='pod',
            matched_resource=self.pod, resource_match_status='matched',
        )
        self.node_alert = Alert.objects.create(
            title='node 异常', level='warning', status=Alert.STATUS_ACTIVE,
            source='test', source_type=Alert.SOURCE_PLATFORM,
            resource='node-1', resource_type='node',
            matched_resource=self.node, resource_match_status='matched',
        )

    def test_ancestor_ids_traversal(self):
        self.assertEqual(ancestor_resource_ids(self.pod), {self.node.id})
        self.assertEqual(descendant_resource_ids(self.node), {self.pod.id})

    def test_child_suppressed_when_parent_active(self):
        reason = check_topology_suppression(self.pod_alert)
        self.assertTrue(reason)
        self.assertIn('node-1', reason)

    def test_apply_and_release_suppression(self):
        self.assertTrue(apply_topology_suppression(self.pod_alert))
        self.pod_alert.refresh_from_db()
        self.assertTrue(self.pod_alert.is_suppressed)
        self.assertEqual(self.pod_alert.suppressed_by, 'topology')
        updated = release_topology_suppression(self.node)
        self.assertEqual(updated, 1)
        self.pod_alert.refresh_from_db()
        self.assertFalse(self.pod_alert.is_suppressed)

    def test_no_suppression_without_matched_resource(self):
        orphan = Alert.objects.create(
            title='孤儿告警', level='warning', status=Alert.STATUS_ACTIVE,
            source='test', source_type=Alert.SOURCE_PLATFORM,
            resource='x', resource_type='node',
        )
        self.assertEqual(check_topology_suppression(orphan), '')

    def test_suppression_off_by_default(self):
        rule = _rule(suppress_by_topology=False)
        self.assertFalse(rule.suppress_by_topology)

    def test_suppressed_parent_does_not_suppress_child(self):
        self.node_alert.is_suppressed = True
        self.node_alert.suppressed_by = 'topology'
        self.node_alert.save()
        self.assertEqual(check_topology_suppression(self.pod_alert), '')


class ExternalConvergenceTests(TestCase):
    def setUp(self):
        self.source = AlertSource.objects.create(
            name='外部收敛源', code='ext-converge',
            provider=AlertSource.PROVIDER_ALERTMANAGER,
            converge_enabled=True,
            converge_group_fields=['alertname'],
            converge_window_minutes=5,
        )

    def _payload(self, alertname, pod):
        return {
            'status': 'firing',
            'alerts': [{
                'status': 'firing',
                'labels': {
                    'alertname': alertname,
                    'severity': 'critical',
                    'pod': pod,
                    'namespace': 'kube-ai',
                    'cluster': 'cluster-a',
                },
                'annotations': {'summary': f'{pod} down'},
                'startsAt': '2026-08-06T02:00:00Z',
            }],
        }

    def test_external_alerts_converge_by_alertname(self):
        from ops.alert_ingest import ingest_external_alert_payload
        with patch('ops.alert_ingest.dispatch_alert_batch_notifications', return_value={'notification_logs': [], 'storm_batches': []}), \
                patch('ops.alert_ingest.apply_escalation_policy', return_value=False), \
                patch('ops.alert_analysis.enqueue_lightweight_analysis', return_value=(None, False)):
            ingest_external_alert_payload(self._payload('PodDown', 'pod-1'), ingress_source=self.source)
            ingest_external_alert_payload(self._payload('PodDown', 'pod-2'), ingress_source=self.source)
        roots = Alert.objects.filter(is_group_root=True)
        self.assertEqual(roots.count(), 1)
        root = roots.get()
        self.assertEqual(root.occurrence_count, 2)
        self.assertEqual(root.group_children.exclude(is_group_root=True).count(), 1)

    def test_external_converge_partition_by_alertname(self):
        from ops.alert_ingest import ingest_external_alert_payload
        with patch('ops.alert_ingest.dispatch_alert_batch_notifications', return_value={'notification_logs': [], 'storm_batches': []}), \
                patch('ops.alert_ingest.apply_escalation_policy', return_value=False), \
                patch('ops.alert_analysis.enqueue_lightweight_analysis', return_value=(None, False)):
            ingest_external_alert_payload(self._payload('PodDown', 'pod-1'), ingress_source=self.source)
            ingest_external_alert_payload(self._payload('NodeDown', 'node-1'), ingress_source=self.source)
        self.assertEqual(Alert.objects.filter(is_group_root=True).count(), 2)

    def test_external_disabled_source_keeps_legacy_behavior(self):
        source = AlertSource.objects.create(
            name='普通源', code='ext-plain',
            provider=AlertSource.PROVIDER_ALERTMANAGER,
            converge_enabled=False,
        )
        from ops.alert_ingest import ingest_external_alert_payload
        with patch('ops.alert_ingest.dispatch_alert_batch_notifications', return_value={'notification_logs': [], 'storm_batches': []}), \
                patch('ops.alert_ingest.apply_escalation_policy', return_value=False), \
                patch('ops.alert_analysis.enqueue_lightweight_analysis', return_value=(None, False)):
            ingest_external_alert_payload(self._payload('PodDown', 'pod-1'), ingress_source=source)
            ingest_external_alert_payload(self._payload('PodDown', 'pod-2'), ingress_source=source)
        self.assertEqual(Alert.objects.filter(is_group_root=True).count(), 0)
        self.assertEqual(Alert.objects.count(), 2)


class ConvergenceHelpersTests(TestCase):
    def setUp(self):
        self.rule = _rule(converge_enabled=True, group_fields=['environment', 'namespace', 'pod'])
        self.alert = Alert.objects.create(
            title='t', level='warning', status=Alert.STATUS_ACTIVE,
            source='test', source_type=Alert.SOURCE_PLATFORM,
            resource='pod-a', resource_type='pod',
            labels={'environment': 'prod', 'namespace': 'kube-ai', 'pod': 'pod-a'},
        )

    def test_convergence_group_key_contains_rule_prefix(self):
        key = convergence_group_key(self.alert, self.rule.group_fields, f'r{self.rule.id}')
        self.assertTrue(key.startswith(f'r{self.rule.id}:'))
        self.assertIn('pod-a', key)

    def test_find_window_root(self):
        self.alert.is_group_root = True
        self.alert.converge_key = f'r{self.rule.id}:x'
        self.alert.save()
        root = find_window_group_root(f'r{self.rule.id}:x', 5)
        self.assertEqual(root.id, self.alert.id)

    def test_promote_or_attach_creates_root_then_child(self):
        role1 = promote_or_attach(self.alert, 'k:1', 5)
        self.assertEqual(role1, 'root')
        self.assertTrue(Alert.objects.get(pk=self.alert.pk).is_group_root)
        child = Alert.objects.create(
            title='c', level='critical', status=Alert.STATUS_ACTIVE,
            source='test', source_type=Alert.SOURCE_PLATFORM,
            resource='pod-b', resource_type='pod',
        )
        role2 = promote_or_attach(child, 'k:1', 5)
        self.assertEqual(role2, 'child')
        root = Alert.objects.get(pk=self.alert.pk)
        self.assertEqual(root.occurrence_count, 2)
        self.assertEqual(root.level, 'critical')

    def test_converge_resolved_alert_resolves_root_when_children_gone(self):
        promote_or_attach(self.alert, 'k:1', 5)
        child = Alert.objects.create(
            title='c', level='warning', status=Alert.STATUS_ACTIVE,
            source='test', source_type=Alert.SOURCE_PLATFORM,
            resource='pod-b', resource_type='pod',
        )
        promote_or_attach(child, 'k:1', 5)
        child.status = Alert.STATUS_RESOLVED
        child.save()
        self.alert.status = Alert.STATUS_RESOLVED
        self.alert.save()
        resolved = converge_resolved_alert(self.alert)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].id, self.alert.id)
