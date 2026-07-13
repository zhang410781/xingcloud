import hashlib
import json

from django.db import transaction
from django.utils import timezone

from .alerting import (
    apply_alert_suppression,
    apply_escalation_policy,
    dispatch_alert_notifications,
    upsert_alert,
)
from .models import Alert, AlertAction


def _text(value, default=''):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _dict(value):
    return value if isinstance(value, dict) else {}


def _first(*values):
    for value in values:
        text = _text(value)
        if text:
            return text
    return ''


def build_rule_fingerprint(rule, labels=None):
    stable = {
        'rule_id': rule.id,
        'rule_code': rule.code,
        'labels': labels or {},
    }
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def build_platform_alert_payload(rule, payload=None, status=None):
    payload = _dict(payload)
    template = getattr(rule, 'template', None)
    labels = {
        **(_dict(getattr(template, 'default_labels', None)) if template else {}),
        **_dict(rule.labels),
        **_dict(payload.get('labels')),
    }
    labels.update({
        'alert_rule_id': str(rule.id),
        'alert_rule_code': rule.code,
        'alert_rule_source_type': rule.source_type,
    })
    annotations = {
        **(_dict(getattr(template, 'annotations', None)) if template else {}),
        **_dict(rule.annotations),
        **_dict(payload.get('annotations')),
    }
    ai_status = 'pending' if rule.auto_analyze else 'disabled'
    evidence = _dict(payload.get('evidence'))
    title = _first(payload.get('title'), annotations.get('summary'), rule.name)
    resource = _first(
        payload.get('resource'),
        labels.get('resource'),
        labels.get('pod'),
        labels.get('node'),
        labels.get('service'),
        labels.get('instance'),
    )
    source_type = Alert.SOURCE_PLATFORM
    return {
        'title': title,
        'level': _first(payload.get('level'), rule.level, 'warning'),
        'status': status or payload.get('status') or Alert.STATUS_ACTIVE,
        'source': 'Xing-Cloud 告警规则',
        'source_type': source_type,
        'external_id': f'alert-rule:{rule.id}',
        'fingerprint': build_rule_fingerprint(rule, labels),
        'group_key': _first(payload.get('group_key')),
        'message': _first(payload.get('message'), annotations.get('description'), rule.description, title),
        'service': _first(payload.get('service'), labels.get('service'), labels.get('app'), labels.get('job_name')),
        'environment': _first(payload.get('environment'), labels.get('environment'), labels.get('env')),
        'cluster': _first(payload.get('cluster'), labels.get('cluster')),
        'namespace': _first(payload.get('namespace'), labels.get('namespace')),
        'region': _first(payload.get('region'), labels.get('region')),
        'business_line': _first(payload.get('business_line'), labels.get('business_line'), labels.get('system'), labels.get('team')),
        'resource_type': _first(payload.get('resource_type'), labels.get('resource_type'), rule.source_type),
        'resource_category': _first(payload.get('resource_category'), labels.get('resource_category'), rule.category),
        'resource': resource,
        'metric_name': _first(payload.get('metric_name'), labels.get('__name__'), rule.query_config.get('metric'), rule.query_config.get('promql')),
        'runbook_url': _first(payload.get('runbook_url'), annotations.get('runbook_url'), annotations.get('runbook')),
        'root_cause': payload.get('root_cause') or '',
        'suggestion': payload.get('suggestion') or '',
        'labels': labels,
        'annotations': annotations,
        'starts_at': timezone.now(),
        'raw_payload': {
            'source': 'alert_rule',
            'rule': {
                'id': rule.id,
                'code': rule.code,
                'name': rule.name,
                'category': rule.category,
                'source_type': rule.source_type,
                'query_config': rule.query_config,
                'condition': rule.condition,
            },
            'event': payload,
            'evidence': evidence,
            'ai_analysis': {
                'status': ai_status,
                'strategy': 'builtin-adaptive',
                'summary': '',
                'confidence': None,
                'suggested_actions': [],
            },
        },
    }


def trigger_alert_rule(rule, payload=None, status=None, request=None):
    if not rule.is_enabled:
        raise ValueError('告警规则未启用')
    normalized = build_platform_alert_payload(rule, payload=payload, status=status)
    notification_action = None
    with transaction.atomic():
        now = timezone.now()
        rule.last_evaluated_at = now
        if normalized['status'] == Alert.STATUS_ACTIVE:
            rule.last_triggered_at = now
        rule.save(update_fields=['last_evaluated_at', 'last_triggered_at', 'updated_at'])

        alert, created = upsert_alert(
            normalized,
            actor='alert-rule',
            action=AlertAction.ACTION_RULE_EVALUATION,
            action_note='平台告警规则触发',
        )
        apply_alert_suppression(alert)
        apply_escalation_policy(alert, request=request)
        notification_action = 'resolved' if alert.status == Alert.STATUS_RESOLVED else 'fire'

    logs = []
    if rule.notify_enabled:
        logs = dispatch_alert_notifications(alert, action=notification_action, request=request)
    return {'alert': alert, 'created': created, 'notification_logs': logs}
