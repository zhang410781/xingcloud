from django.test import TestCase

from ops.alert_engine.pipeline import _result_fingerprint, process_rule_results
from ops.models import Alert, AlertAction, AlertRule, AlertRuleState


class WaitingAlertStabilityTests(TestCase):
    def setUp(self):
        self.rule = AlertRule.objects.create(
            name='Pod 长时间 Waiting · test',
            code='pod-waiting-test',
            source_type='prometheus',
            level='critical',
            duration_seconds=0,
            notify_enabled=False,
            auto_analyze=False,
            query_config={'query': 'max_over_time(kube_pod_container_status_waiting_reason[5m])'},
        )

    def _result(self, reason='ImagePullBackOff', uid='uid-1'):
        return {
            'matched': True,
            'value': 1,
            'title': self.rule.name,
            'message': f'Waiting 原因为 {reason}',
            'labels': {
                'environment': 'prod',
                'metric_datasource_id': '1',
                'cluster': 'cluster-a',
                'namespace': 'kube-ai',
                'pod': 'alert-test-nginx',
                'container': 'nginx',
                'uid': uid,
                'reason': reason,
            },
        }

    def test_reason_change_reuses_same_alert_and_records_timeline(self):
        first = process_rule_results(self.rule, [self._result('ImagePullBackOff')])
        second = process_rule_results(self.rule, [self._result('ErrImagePull')])

        self.assertEqual(first['created_count'], 1)
        self.assertEqual(second['created_count'], 0)
        self.assertEqual(Alert.objects.count(), 1)
        alert = Alert.objects.get()
        self.assertEqual(alert.status, Alert.STATUS_ACTIVE)
        self.assertEqual(alert.labels['reason'], 'ErrImagePull')
        self.assertIsInstance(alert.raw_payload['event']['starts_at'], str)
        self.assertTrue(AlertAction.objects.filter(alert=alert, note__contains='原因变化').exists())

    def test_reason_is_excluded_but_pod_uid_is_part_of_fingerprint(self):
        first = _result_fingerprint(self.rule, self._result('ImagePullBackOff', 'uid-1'))
        changed_reason = _result_fingerprint(self.rule, self._result('ErrImagePull', 'uid-1'))
        replaced_pod = _result_fingerprint(self.rule, self._result('ErrImagePull', 'uid-2'))

        self.assertEqual(first, changed_reason)
        self.assertNotEqual(first, replaced_pod)

    def test_active_state_requires_two_missed_evaluations_to_recover(self):
        process_rule_results(self.rule, [self._result()])

        first_miss = process_rule_results(self.rule, [])
        state = AlertRuleState.objects.get(rule=self.rule)
        self.assertEqual(first_miss['resolved_count'], 0)
        self.assertEqual(state.status, AlertRuleState.STATUS_ACTIVE)
        self.assertEqual(state.consecutive_misses, 1)

        second_miss = process_rule_results(self.rule, [])
        state.refresh_from_db()
        self.assertEqual(second_miss['resolved_count'], 1)
        self.assertEqual(state.status, AlertRuleState.STATUS_RESOLVED)
        alert = Alert.objects.get()
        self.assertEqual(alert.status, Alert.STATUS_RESOLVED)
        self.assertEqual(alert.title, self.rule.name)
        self.assertNotIn('recovered', alert.title.lower())
