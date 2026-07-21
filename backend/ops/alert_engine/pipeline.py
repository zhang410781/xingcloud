from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ops.alert_rules import build_platform_alert_payload, build_rule_fingerprint
from ops.alerting import (
    apply_alert_suppression,
    apply_escalation_policy,
    dispatch_alert_batch_notifications,
    upsert_alert,
)
from ops.models import Alert, AlertAction, AlertRuleState


def _duration_seconds(rule):
    condition = rule.condition if isinstance(rule.condition, dict) else {}
    try:
        return int(condition.get('duration_seconds') if condition.get('duration_seconds') is not None else rule.duration_seconds)
    except (TypeError, ValueError):
        return int(rule.duration_seconds or 0)


def _result_fingerprint(rule, result):
    return build_rule_fingerprint(rule, result.get('labels') or {})


def _alert_payload_from_result(rule, result, status=Alert.STATUS_ACTIVE):
    labels = dict(result.get('labels') or {})
    payload = {
        'title': result.get('title') or rule.name,
        'message': result.get('message') or f"{rule.name}: value={result.get('value')}",
        'level': result.get('level') or rule.level,
        'status': status,
        'labels': labels,
        'annotations': result.get('annotations') or {},
        'environment': labels.get('environment') or result.get('environment') or '',
        'cluster': labels.get('cluster') or result.get('cluster') or '',
        'namespace': labels.get('namespace') or result.get('namespace') or '',
        'service': labels.get('service') or labels.get('job') or result.get('service') or '',
        'resource_type': result.get('resource_type') or labels.get('resource_type') or rule.source_type,
        'resource': result.get('resource') or labels.get('resource') or labels.get('pod') or labels.get('instance') or labels.get('name') or '',
        'metric_name': result.get('metric_name') or labels.get('__name__') or '',
        'evidence': result.get('evidence') or {},
    }
    return build_platform_alert_payload(rule, payload=payload, status=status)


def _emit_alert(rule, result, request=None, status=Alert.STATUS_ACTIVE):
    normalized = _alert_payload_from_result(rule, result, status=status)
    previous = Alert.objects.filter(fingerprint=normalized.get('fingerprint')).only('level').first()
    previous_level = previous.level if previous else ''
    # 参考 database-monitor-main 的根因分析设计
    try:
        from ops.alert_engine.evaluator import build_alert_with_root_cause
        root_cause_data = build_alert_with_root_cause(rule, result, status=status)
        normalized['root_cause'] = root_cause_data.get('root_cause', '')
        normalized['suggestion'] = root_cause_data.get('suggestion', '')
    except Exception:
        normalized['root_cause'] = ''
        normalized['suggestion'] = ''
    alert, created = upsert_alert(
        normalized,
        actor='alert-engine',
        action=AlertAction.ACTION_RULE_EVALUATION,
        action_note='alert engine evaluation',
    )
    apply_alert_suppression(alert)
    apply_escalation_policy(alert, request=request)
    return alert, created, previous_level


def process_rule_results(rule, results, *, dry_run=False, request=None):
    now = timezone.now()
    results = [dict(item) for item in results or [] if item.get('matched')]
    default_duration = _duration_seconds(rule)
    seen_fingerprints = []
    would_fire = []

    if dry_run:
        for item in results:
            item['fingerprint'] = _result_fingerprint(rule, item)
            item['would_fire'] = True
            labels = item.get('labels') or {}
            annotations = item.get('annotations') or {}
            target = item.get('resource') or labels.get('pod') or labels.get('node') or labels.get('instance') or '-'
            item['rendered_notification'] = {
                'title': item.get('title') or rule.name,
                'summary': item.get('message') or annotations.get('message') or rule.name,
                'description': annotations.get('description') or '无描述',
                'impact_scope': f'{labels.get("namespace") or "-"}/{target}',
            }
            would_fire.append(item)
        return {
            'dry_run': True,
            'matched_count': len(results),
            'would_fire_count': len(would_fire),
            'created_count': 0,
            'updated_count': 0,
            'resolved_count': 0,
            'notification_log_count': 0,
            'results': would_fire,
            'alerts': [],
            'storm_batches': [],
        }

    alerts_to_notify = []
    resolved_to_notify = []
    created_count = 0
    updated_count = 0
    resolved_count = 0
    analysis_candidates = []

    with transaction.atomic():
        for item in results:
            fingerprint = _result_fingerprint(rule, item)
            item['fingerprint'] = fingerprint
            seen_fingerprints.append(fingerprint)
            state, _ = AlertRuleState.objects.get_or_create(
                rule=rule,
                fingerprint=fingerprint,
                defaults={
                    'labels': item.get('labels') or {},
                    'status': AlertRuleState.STATUS_PENDING,
                    'first_seen_at': now,
                },
            )
            if not state.first_seen_at or state.status == AlertRuleState.STATUS_RESOLVED:
                state.first_seen_at = now
            state.labels = item.get('labels') or {}
            state.last_seen_at = now
            state.last_value = item.get('value') if isinstance(item.get('value'), (int, float)) else None
            state.last_error = ''
            try:
                duration = int(item.get('duration_seconds', default_duration))
            except (TypeError, ValueError):
                duration = default_duration
            fire_at = state.first_seen_at + timedelta(seconds=duration)
            item['would_fire'] = now >= fire_at
            if item['would_fire']:
                previous_status = state.status
                state.status = AlertRuleState.STATUS_ACTIVE
                alert, created, previous_level = _emit_alert(rule, item, request=request, status=Alert.STATUS_ACTIVE)
                alerts_to_notify.append(alert)
                analysis_candidates.append((alert, created, previous_level))
                created_count += 1 if created else 0
                updated_count += 0 if created else 1
                if previous_status != AlertRuleState.STATUS_ACTIVE:
                    item['state_changed'] = True
            else:
                state.status = AlertRuleState.STATUS_PENDING
            state.save(update_fields=['labels', 'status', 'first_seen_at', 'last_seen_at', 'last_value', 'last_error', 'updated_at'])

        stale_states = AlertRuleState.objects.filter(rule=rule, status__in=[AlertRuleState.STATUS_ACTIVE, AlertRuleState.STATUS_PENDING]).exclude(fingerprint__in=seen_fingerprints)
        for state in stale_states:
            if state.status == AlertRuleState.STATUS_ACTIVE:
                result = {
                    'labels': state.labels or {},
                    'value': state.last_value,
                    'matched': False,
                    'title': f'{rule.name} recovered',
                    'message': f'{rule.name} recovered',
                    'evidence': {'state': 'resolved', 'last_value': state.last_value},
                }
                alert, _, _ = _emit_alert(rule, result, request=request, status=Alert.STATUS_RESOLVED)
                resolved_to_notify.append(alert)
                resolved_count += 1
            state.status = AlertRuleState.STATUS_RESOLVED
            state.last_seen_at = now
            state.save(update_fields=['status', 'last_seen_at', 'updated_at'])

        rule.last_evaluated_at = now
        if alerts_to_notify:
            rule.last_triggered_at = now
        rule.save(update_fields=['last_evaluated_at', 'last_triggered_at', 'updated_at'])

    notification_result = {'notification_logs': [], 'storm_batches': []}
    if rule.notify_enabled and alerts_to_notify:
        notification_result = dispatch_alert_batch_notifications(alerts_to_notify, action='fire', request=request)
    if analysis_candidates:
        from ops.alert_analysis import enqueue_for_rule_alert
        for alert, created, previous_level in analysis_candidates:
            enqueue_for_rule_alert(alert, rule, created=created, previous_level=previous_level)
    resolved_notification_result = {'notification_logs': [], 'storm_batches': []}
    if rule.notify_enabled and resolved_to_notify:
        resolved_notification_result = dispatch_alert_batch_notifications(resolved_to_notify, action='resolved', request=request)

    notification_logs = list(notification_result.get('notification_logs') or []) + list(resolved_notification_result.get('notification_logs') or [])
    return {
        'dry_run': False,
        'matched_count': len(results),
        'would_fire_count': len([item for item in results if item.get('would_fire')]),
        'created_count': created_count,
        'updated_count': updated_count,
        'resolved_count': resolved_count,
        'notification_log_count': len(notification_logs),
        'results': results,
        'alerts': alerts_to_notify + resolved_to_notify,
        'storm_batches': notification_result.get('storm_batches') or [],
    }


def mark_rule_error(rule, error):
    now = timezone.now()
    rule.last_evaluated_at = now
    rule.save(update_fields=['last_evaluated_at', 'updated_at'])
    AlertRuleState.objects.update_or_create(
        rule=rule,
        fingerprint=f'error:{rule.id}',
        defaults={
            'labels': {},
            'status': AlertRuleState.STATUS_ERROR,
            'first_seen_at': now,
            'last_seen_at': now,
            'last_error': str(error),
        },
    )
