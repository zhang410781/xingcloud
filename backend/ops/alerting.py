import base64
import hashlib
import hmac
import json
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import timedelta

import requests
from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models import Q
from django.utils import timezone

from .models import (
    Alert,
    AlertAnalysis,
    AlertAction,
    AlertClaim,
    AlertInteractionToken,
    AlertNotificationChannel,
    AlertNotificationLog,
    AlertNotificationPolicy,
    AlertRecipient,
    AlertRecipientGroup,
    AlertRule,
    AlertSilence,
    Host,
)


logger = logging.getLogger(__name__)


LEVEL_RANK = {'info': 1, 'warning': 2, 'critical': 3}
DEFAULT_GROUP_BY = ['source_type', 'environment', 'service', 'cluster', 'namespace', 'resource']
CARD_ACTIONS = ['claim', 'mute']


class SafeFormatDict(dict):
    def __missing__(self, key):
        return ''


class NotificationDeliveryError(RuntimeError):
    def __init__(self, message, response_body=''):
        super().__init__(message)
        self.response_body = response_body


def _text(value, default=''):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _claim_records(alert):
    records = getattr(alert, '_prefetched_objects_cache', {}).get('claim_records')
    if records is not None:
        return list(records)
    return list(alert.claim_records.all())


def _claimant_names(alert):
    return [item.claimant for item in _claim_records(alert)]


def _has_claimants(alert):
    return bool(_claim_records(alert))


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    if value is None or value == '':
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return ''


def _host_for(resource, labels):
    candidates = [
        resource,
        labels.get('instance'),
        labels.get('host'),
        labels.get('hostname'),
        labels.get('node'),
        labels.get('ident'),
        labels.get('ip'),
    ]
    for candidate in candidates:
        text = _text(candidate)
        if not text:
            continue
        host = Host.objects.filter(Q(hostname=text) | Q(ip_address=text)).first()
        if host:
            return host
        if ':' in text:
            short = text.split(':', 1)[0]
            host = Host.objects.filter(Q(hostname=short) | Q(ip_address=short)).first()
            if host:
                return host
    return None


def _fingerprint(provider, fields):
    base = _first(fields.get('fingerprint'), fields.get('external_id'))
    if base:
        return hashlib.sha256(f'{provider}:{base}'.encode('utf-8')).hexdigest()
    stable = {
        'provider': provider,
        'title': fields.get('title'),
        'resource': fields.get('resource'),
        'metric_name': fields.get('metric_name'),
        'labels': fields.get('labels') or {},
    }
    payload = json.dumps(stable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def alert_dimension_value(alert, key):
    key = str(key or '').strip()
    if not key:
        return ''
    if hasattr(alert, key):
        return _text(getattr(alert, key))
    labels = alert.labels or {}
    annotations = alert.annotations or {}
    if key.startswith('label.'):
        return _text(labels.get(key.split('.', 1)[1]))
    if key.startswith('annotation.'):
        return _text(annotations.get(key.split('.', 1)[1]))
    return _text(labels.get(key) or annotations.get(key))


def compute_group_key(alert, group_by=None):
    dims = group_by or DEFAULT_GROUP_BY
    values = [f'{key}={alert_dimension_value(alert, key) or "-"}' for key in dims]
    return ' | '.join(values)


def _save_action(alert, action, actor='', note='', metadata=None):
    return AlertAction.objects.create(
        alert=alert,
        action=action,
        actor=actor or '',
        note=note or '',
        metadata=metadata or {},
    )


def upsert_alert(normalized, actor='system', action=None, action_note=None):
    now = timezone.now()
    status_value = normalized.get('status') or Alert.STATUS_ACTIVE
    source_type = normalized.get('source_type') or Alert.SOURCE_PLATFORM
    fingerprint = normalized.get('fingerprint') or _fingerprint(source_type, normalized)
    existing = Alert.objects.filter(fingerprint=fingerprint).exclude(status=Alert.STATUS_CLOSED).order_by('-created_at').first()

    defaults = {
        'title': normalized.get('title') or '告警事件',
        'level': normalized.get('level') or 'info',
        'status': status_value,
        'source': normalized.get('source') or source_type,
        'source_type': source_type,
        'external_id': normalized.get('external_id') or '',
        'fingerprint': fingerprint,
        'group_key': normalized.get('group_key') or '',
        'message': normalized.get('message') or '',
        'service': normalized.get('service') or '',
        'environment': normalized.get('environment') or '',
        'cluster': normalized.get('cluster') or '',
        'namespace': normalized.get('namespace') or '',
        'region': normalized.get('region') or '',
        'business_line': normalized.get('business_line') or '',
        'resource_type': normalized.get('resource_type') or '',
        'resource': normalized.get('resource') or '',
        'metric_name': normalized.get('metric_name') or '',
        'runbook_url': normalized.get('runbook_url') or '',
        'root_cause': normalized.get('root_cause') or '',
        'suggestion': normalized.get('suggestion') or '',
        'labels': normalized.get('labels') or {},
        'annotations': normalized.get('annotations') or {},
        'raw_payload': normalized.get('raw_payload') or {},
        'starts_at': normalized.get('starts_at'),
        'ends_at': normalized.get('ends_at') if status_value == Alert.STATUS_RESOLVED else None,
        'last_received_at': now,
    }
    defaults['host'] = _host_for(defaults['resource'], defaults['labels'])
    from aiops.business_context import resolve_business_context
    defaults['knowledge_environment'] = resolve_business_context(defaults['environment'])

    created = existing is None
    if created:
        alert = Alert.objects.create(**defaults)
    else:
        alert = existing
        was_resolved = alert.status == Alert.STATUS_RESOLVED
        for field, value in defaults.items():
            if field == 'starts_at' and alert.starts_at and not (
                status_value == Alert.STATUS_ACTIVE and was_resolved
            ):
                continue
            setattr(alert, field, value)
        alert.occurrence_count = alert.occurrence_count + 1
        if status_value == Alert.STATUS_ACTIVE and was_resolved:
            alert.starts_at = defaults.get('starts_at') or now
            alert.is_acknowledged = False
            alert.acknowledged_by = ''
            alert.acknowledged_at = None
            alert.ends_at = None
        alert.save()

    if not alert.group_key:
        alert.group_key = compute_group_key(alert)
        alert.save(update_fields=['group_key'])

    action_value = action or AlertAction.ACTION_RULE_EVALUATION
    note = action_note or ('告警规则触发' if created else '告警规则更新')

    _save_action(
        alert,
        action_value,
        actor=actor,
        note=note,
        metadata={'created': created, 'source_type': alert.source_type},
    )
    return alert, created


def _alert_value_map(alert):
    values = {
        'title': alert.title,
        'level': alert.level,
        'status': alert.status,
        'source': alert.source,
        'source_type': alert.source_type,
        'service': alert.service,
        'environment': alert.environment,
        'cluster': alert.cluster,
        'namespace': alert.namespace,
        'region': alert.region,
        'business_line': alert.business_line,
        'resource_type': alert.resource_type,
        'resource': alert.resource,
        'metric_name': alert.metric_name,
        'claimed_by': alert.claimed_by,
    }
    values.update({f'label.{key}': value for key, value in (alert.labels or {}).items()})
    values.update({f'annotation.{key}': value for key, value in (alert.annotations or {}).items()})
    for key, value in (alert.labels or {}).items():
        values.setdefault(key, value)
    return {key: _text(value) for key, value in values.items()}


def match_matchers(alert, matchers):
    if not matchers:
        return True
    values = _alert_value_map(alert)
    if isinstance(matchers, dict):
        matchers = [{'key': key, 'op': '==', 'value': value} for key, value in matchers.items()]
    for matcher in _list(matchers):
        if not isinstance(matcher, dict):
            continue
        key = _text(matcher.get('key') or matcher.get('label'))
        op = _text(matcher.get('operator') or matcher.get('op') or matcher.get('func') or '==')
        expected = matcher.get('value')
        actual = values.get(key, '')
        if op in {'==', '='} and actual != _text(expected):
            return False
        if op == '!=' and actual == _text(expected):
            return False
        if op in {'=~', 'regex'} and not re.search(_text(expected), actual):
            return False
        if op == '!~' and re.search(_text(expected), actual):
            return False
        if op == 'contains' and _text(expected) not in actual:
            return False
        if op in {'in', 'not in'}:
            expected_values = [_text(item) for item in _list(expected)]
            hit = actual in expected_values
            if op == 'in' and not hit:
                return False
            if op == 'not in' and hit:
                return False
    return True


def _policy_inhibits_alert(policy, alert):
    definitions = [
        item for item in _list(policy.inhibition_matchers)
        if isinstance(item, dict) and item.get('source_level') and item.get('target_levels')
    ]
    if not definitions:
        return bool(policy.inhibition_matchers) and match_matchers(alert, policy.inhibition_matchers)
    target_values = _alert_value_map(alert)
    for definition in definitions:
        if alert.level not in {_text(item) for item in _list(definition.get('target_levels'))}:
            continue
        source_level = _text(definition.get('source_level'))
        equal_keys = [_text(item) for item in _list(definition.get('equal')) if _text(item)]
        candidates = Alert.objects.filter(
            status=Alert.STATUS_ACTIVE,
            level=source_level,
            environment=alert.environment,
        ).exclude(pk=alert.pk).order_by('-starts_at')[:200]
        for candidate in candidates:
            source_values = _alert_value_map(candidate)
            if all(source_values.get(key, '') == target_values.get(key, '') for key in equal_keys):
                return True
    return False


def apply_alert_suppression(alert):
    now = timezone.now()
    matched_silence = None
    for silence in AlertSilence.objects.filter(
        is_enabled=True,
        starts_at__lte=now,
        ends_at__gte=now,
    ):
        if match_matchers(alert, silence.matchers):
            matched_silence = silence
            break

    if matched_silence:
        alert.status = Alert.STATUS_MUTED
        alert.is_suppressed = True
        alert.suppressed_by = f'silence:{matched_silence.name}'
        alert.suppressed_until = matched_silence.ends_at
        alert.mute_until = matched_silence.ends_at
        alert.muted_reason = matched_silence.reason
    elif alert.mute_until and alert.mute_until > now:
        alert.status = Alert.STATUS_MUTED
        alert.is_suppressed = True
        alert.suppressed_by = 'manual_mute'
        alert.suppressed_until = alert.mute_until
    else:
        alert.is_suppressed = False
        alert.suppressed_by = ''
        alert.suppressed_until = None

    alert.save(update_fields=[
        'status', 'is_suppressed', 'suppressed_by', 'suppressed_until',
        'mute_until', 'muted_reason', 'updated_at',
    ])
    return alert


def _base_url(request=None):
    if request:
        return request.build_absolute_uri('/').rstrip('/')
    return str(
        getattr(settings, 'XING_CLOUD_PUBLIC_BASE_URL', '')
        or getattr(settings, 'AGDEVOPS_PUBLIC_BASE_URL', '')
        or ''
    ).rstrip('/')


def _interaction_url(alert, action, provider='', request=None):
    base = _base_url(request)
    if not base:
        return ''
    token = AlertInteractionToken.objects.create(
        alert=alert,
        action=action,
        provider=provider or '',
        expires_at=timezone.now() + timedelta(days=7),
    )
    return f'{base}/alert-actions/{token.token}'


def _alert_context(alert, action='fire'):
    return {
        'id': alert.id,
        'title': alert.title,
        'level': alert.level,
        'status': alert.status,
        'source': alert.source,
        'source_type': alert.source_type,
        'service': alert.service,
        'environment': alert.environment,
        'cluster': alert.cluster,
        'namespace': alert.namespace,
        'resource': alert.resource,
        'metric_name': alert.metric_name,
        'message': alert.message,
        'claimants': '、'.join(_claimant_names(alert)),
        'runbook_url': alert.runbook_url,
        'root_cause': alert.root_cause,
        'suggestion': alert.suggestion,
        'starts_at': alert.starts_at.isoformat() if alert.starts_at else '',
        'last_received_at': alert.last_received_at.isoformat() if alert.last_received_at else '',
        'action': action,
        'group_key': alert.group_key,
        'occurrence_count': alert.occurrence_count,
    }


def _render(value, alert, action='fire'):
    template = _text(value)
    context = SafeFormatDict(_alert_context(alert, action))
    if not template:
        return ''
    try:
        return template.format_map(context)
    except Exception:
        return template


def _default_title(alert, action='fire'):
    if action == 'resolved':
        return f'✅ 🟢 已恢复: {alert.title}'
    if action == 'analysis':
        return f'🎯 智能告警研判: {alert.title}'
    level = {'critical': '🔴', 'warning': '🟡', 'info': '🔵'}.get(alert.level, '🟡')
    return f'🔥 {level} 告警中: {alert.title}'


def _notification_payload(alert):
    raw = _dict(alert.raw_payload)
    event = _dict(raw.get('event'))
    rule = _dict(raw.get('rule'))
    evidence = _dict(raw.get('evidence')) or _dict(event.get('evidence'))
    return raw, event, rule, evidence


def _first_number(*values):
    for value in values:
        if isinstance(value, bool) or value in (None, ''):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _format_number(value):
    if value is None:
        return '-'
    if abs(value) >= 1000:
        return f'{value:,.2f}'.rstrip('0').rstrip('.')
    return f'{value:.2f}'.rstrip('0').rstrip('.')


def _metric_unit(alert, rule):
    labels = _dict(alert.labels)
    annotations = _dict(alert.annotations)
    query_config = _dict(rule.get('query_config'))
    explicit = _first(
        annotations.get('unit'),
        labels.get('unit'),
        query_config.get('unit'),
    )
    if explicit:
        return explicit
    metric_text = f'{alert.metric_name} {alert.title}'.lower()
    if any(token in metric_text for token in ('percent', 'ratio', 'usage', '利用率', '使用率')):
        return '%'
    if any(token in metric_text for token in ('restart', '重启', 'count', '数量', '次数')):
        return '次'
    if any(token in metric_text for token in ('bytes', 'byte', '字节')):
        return 'B'
    if any(token in metric_text for token in ('seconds', 'latency', 'duration', '时延', '耗时')):
        return '秒'
    return ''


def _window_text(rule):
    query_config = _dict(rule.get('query_config'))
    condition = _dict(rule.get('condition'))
    raw_window = _first(
        query_config.get('window'),
        query_config.get('window_minutes'),
        condition.get('window'),
        condition.get('window_minutes'),
    )
    if raw_window:
        text = str(raw_window).strip()
        if text.isdigit():
            return f'{text}分钟'
        return text.replace('m', '分钟').replace('h', '小时')
    query = _first(query_config.get('promql'), query_config.get('query'))
    match = re.search(r'\[(\d+(?:\.\d+)?)([smhd])\]', query)
    if not match:
        return ''
    suffix = {'s': '秒', 'm': '分钟', 'h': '小时', 'd': '天'}[match.group(2)]
    return f'{match.group(1)}{suffix}'


def _condition_text(alert, rule, unit):
    condition = _dict(rule.get('condition'))
    levels = condition.get('levels') if isinstance(condition.get('levels'), list) else []
    level_condition = next(
        (item for item in levels if isinstance(item, dict) and item.get('level') == alert.level),
        next((item for item in levels if isinstance(item, dict)), condition),
    )
    operator = _first(level_condition.get('operator'), level_condition.get('op'), condition.get('operator'), '>')
    threshold = _first_number(
        level_condition.get('threshold'),
        level_condition.get('value'),
        condition.get('threshold'),
        condition.get('value'),
        condition.get(alert.level),
    )
    if threshold is None:
        return '-'
    operator = {
        'gt': '>',
        'gte': '>=',
        'lt': '<',
        'lte': '<=',
        'eq': '=',
        'ne': '!=',
    }.get(str(operator).strip().lower(), operator)
    return f'{operator} {_format_number(threshold)}{unit}'


def _human_description(alert, event):
    annotations = _dict(alert.annotations)
    event_annotations = _dict(event.get('annotations'))
    description = _first(
        annotations.get('description'),
        event_annotations.get('description'),
        annotations.get('summary'),
        event_annotations.get('summary'),
    )
    if description:
        return description
    message = _text(alert.message)
    technical = (
        re.search(r'\b(?:sum|avg|min|max|rate|increase|count)\s*(?:by\s*)?\(', message, re.I)
        or re.search(r'\{[^}]*\}|\[[0-9.]+[smhd]\]', message)
        or re.search(r'\b(?:select|from|where)\b', message, re.I)
        or re.search(r'\svalue\s[-+0-9.]', message, re.I)
    )
    return alert.title if technical or not message else message


def _format_datetime(value):
    if not value:
        return '-'
    try:
        return timezone.localtime(value).strftime('%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return str(value)


def _format_duration(start, end):
    if not start or not end:
        return '-'
    seconds = max(int((end - start).total_seconds()), 0)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f'{days}天')
    if hours:
        parts.append(f'{hours}小时')
    if minutes:
        parts.append(f'{minutes}分钟')
    if seconds or not parts:
        parts.append(f'{seconds}秒')
    return ''.join(parts[:2])


def _analysis_key_evidence(evidence, result=None, limit=3):
    result = _dict(result)
    lines = []

    def append(value):
        text = _text(value)
        if text and text not in lines:
            lines.append(text[:300])

    for event in evidence.get('event_findings') or []:
        if isinstance(event, dict):
            append(f'{event.get("reason") or "Warning Event"}：{event.get("message") or "-"}')
        if len(lines) >= limit:
            return lines

    for sample in evidence.get('k8s_samples') or []:
        if not isinstance(sample, dict):
            continue
        target = '/'.join(item for item in [sample.get('namespace'), sample.get('pod')] if item) or '目标 Pod'
        for container in sample.get('containers') or []:
            if not isinstance(container, dict):
                continue
            state = _dict(container.get('waiting')) or _dict(container.get('terminated'))
            if state.get('reason') or state.get('message'):
                append(
                    f'{target}/{container.get("name") or "-"}：'
                    f'{state.get("reason") or "异常"} {state.get("message") or ""}'.strip()
                )
            if len(lines) >= limit:
                return lines

    for finding in evidence.get('log_findings') or []:
        if isinstance(finding, dict):
            append(f'{finding.get("target") or "异常日志"}：{finding.get("message") or "-"}')
        if len(lines) >= limit:
            return lines

    for note in result.get('evidence_notes') or []:
        append(note.get('message') if isinstance(note, dict) else note)
        if len(lines) >= limit:
            return lines

    for item in _dict(evidence.get('targeted_metrics')).get('items') or []:
        if isinstance(item, dict) and item.get('health') in {'warning', 'critical'}:
            append(f'{item.get("title") or item.get("code") or "指标"}：峰值 {item.get("peak")}, 当前值 {item.get("latest")}')
        if len(lines) >= limit:
            return lines
    return lines


def _analysis_content(alert, raw):
    analysis = _dict(raw.get('ai_analysis'))
    analysis_manager = getattr(alert, 'analyses', None)
    latest = analysis_manager.order_by('-created_at').first() if analysis_manager is not None else None
    if latest is not None:
        result = _dict(latest.result)
        analysis = {
            **analysis,
            'status': latest.status,
            'confidence': latest.confidence,
            'summary': result.get('summary') or analysis.get('summary'),
            'root_cause': latest.root_cause or analysis.get('root_cause'),
            'evidence': latest.evidence or analysis.get('evidence'),
            'evidence_notes': result.get('evidence_notes') or analysis.get('evidence_notes'),
            'suggestions': result.get('suggestions') or latest.suggestion or analysis.get('suggestions'),
        }
    confidence = analysis.get('confidence')
    if isinstance(confidence, (int, float)):
        confidence_text = f'{confidence * 100:.0f}%' if confidence <= 1 else f'{confidence:.0f}%'
    else:
        confidence_text = _text(confidence, '未评估') or '未评估'
    root_cause = _first(analysis.get('root_cause'), analysis.get('summary'), alert.root_cause, '尚未形成明确结论')
    evidence = analysis.get('evidence') or analysis.get('evidence_notes')
    if isinstance(evidence, dict):
        key_evidence = _analysis_key_evidence(evidence, result if latest is not None else analysis)
        if key_evidence:
            evidence = key_evidence
        else:
            diagnostics = evidence.get('diagnostics') if isinstance(evidence.get('diagnostics'), list) else []
            diagnostic_lines = [
                _first(item.get('message'), item.get('summary'))
                for item in diagnostics if isinstance(item, dict)
            ]
            logs = _dict(evidence.get('logs'))
            log_summary = ''
            if logs:
                sample_count = logs.get('sample_count') or logs.get('count') or 0
                status = logs.get('status') or 'unknown'
                log_summary = f'关联日志状态 {status}，命中 {sample_count} 条样本'
            metrics = _dict(evidence.get('metrics'))
            metric_summary = _first(metrics.get('summary'), metrics.get('message'))
            summarized = [item for item in [metric_summary, log_summary, *diagnostic_lines] if item]
            evidence = evidence.get('summary') or evidence.get('items') or evidence.get('key_evidence') or summarized or evidence
    if isinstance(evidence, list):
        evidence_lines = []
        for item in evidence[:3]:
            if isinstance(item, dict):
                evidence_lines.append(_first(item.get('summary'), item.get('message'), item.get('content'), item.get('fact')))
            else:
                evidence_lines.append(_text(item))
        evidence_text = '；'.join(item for item in evidence_lines if item) or '暂无关键证据摘要'
    elif isinstance(evidence, dict):
        evidence_text = '；'.join(f'{key}: {_text(value)}' for key, value in list(evidence.items())[:3])
    else:
        evidence_text = _text(evidence, '暂无关键证据摘要') or '暂无关键证据摘要'
    suggestions = analysis.get('suggestions') or analysis.get('suggested_actions') or alert.suggestion
    if isinstance(suggestions, list):
        suggestion_text = '；'.join(_text(item.get('content') if isinstance(item, dict) else item) for item in suggestions[:3])
    else:
        suggestion_text = _text(suggestions, '请结合证据进一步确认') or '请结合证据进一步确认'
    return confidence_text, root_cause, evidence_text, suggestion_text


def _analysis_markdown(alert, raw):
    confidence, root_cause, _evidence_text, suggestion = _analysis_content(alert, raw)
    latest = alert.analyses.order_by('-created_at').first()
    evidence = _dict(latest.evidence) if latest else {}
    result = _dict(latest.result) if latest else {}
    target = _dict(_dict(evidence.get('targeted_metrics')).get('target'))
    target_metrics = _dict(evidence.get('targeted_metrics')).get('items') or []
    k8s_sample = (evidence.get('k8s_samples') or [{}])[0]
    events = k8s_sample.get('events') or []
    log_findings = evidence.get('log_findings') or []
    changes = evidence.get('change_findings') or []
    missing = [str(item.get('message') or '') for item in evidence.get('diagnostics') or [] if item.get('message')]
    candidates = latest.candidates if latest and isinstance(latest.candidates, list) else []
    suggestions = result.get('suggestions') if isinstance(result.get('suggestions'), list) else []
    status_text = alert.get_status_display()
    lines = [
        '## 告警精准研判报告',
        '',
        '### 告警概览',
        '| 告警 | 级别 | 状态 | 命名空间 | Pod | 容器 |',
        '| :--- | :--- | :--- | :--- | :--- | :--- |',
        f'| {alert.title} | {alert.get_level_display()} | {status_text} | {target.get("namespace") or alert.namespace or "-"} | {target.get("pod") or alert.resource or "-"} | {target.get("container") or "-"} |',
        '',
        f'**告警状态：** {status_text}',
        f'**结论：** {root_cause}',
        f'**置信度：** {confidence}',
    ]
    metric_rows = [item for item in target_metrics if item.get('status') == 'ok']
    if metric_rows:
        lines.extend(['', '### 指标证据', '| 指标 | 峰值 | 当前值 | 采样数 |', '| :--- | ---: | ---: | ---: |'])
        for item in metric_rows[:10]:
            lines.append(f'| {item.get("title") or item.get("code")} | {_format_number(item.get("peak"))} | {_format_number(item.get("latest"))} | {item.get("sample_count") or 0} |')
    if k8s_sample:
        lines.extend(['', '### K8s Describe', f'- Pod 阶段：{k8s_sample.get("phase") or "未获取"}', f'- 所在节点：{k8s_sample.get("node") or "未获取"}'])
        for container in (k8s_sample.get('containers') or [])[:5]:
            state = _dict(container.get('waiting')).get('reason') or _dict(container.get('terminated')).get('reason') or ('Ready' if container.get('ready') else 'NotReady')
            lines.append(f'- 容器 {container.get("name") or "-"}：{state}，重启 {container.get("restart_count") or 0} 次，镜像 {container.get("image") or "-"}')
    lines.extend(['', '### 日志与事件'])
    if events:
        for item in events[:8]:
            lines.append(f'- Warning Event / {item.get("reason") or "-"}：{str(item.get("message") or "")[:240]}')
    if log_findings:
        for item in log_findings[:8]:
            lines.append(f'- 异常日志 / {item.get("target") or "-"}：{str(item.get("message") or "")[:240]}')
    if not events and not log_findings:
        lines.append('- 未发现可作为关键证据的 Warning Event 或异常日志；普通访问日志已排除。')
    lines.extend(['', '### 候选根因'])
    if candidates:
        for item in candidates[:5]:
            lines.append(f'- {item.get("title") or item.get("code")}（{float(item.get("score") or 0) * 100:.0f}%）')
    else:
        lines.append(f'- {"告警仍活跃但无法确诊" if alert.status == Alert.STATUS_ACTIVE else "已恢复但无法确诊"}')
    lines.extend(['', '### 反向证据'])
    if not events:
        lines.append('- 未获取到目标 Pod 的 Warning Event。')
    if not log_findings:
        lines.append('- 告警窗口内未命中异常日志模式。')
    if changes:
        lines.append(f'- 告警窗口附近发现 {len(changes)} 项发布或配置变更，需人工核对相关性。')
    else:
        lines.append('- 未发现与目标匹配的近期发布或配置变更。')
    lines.extend(['', '### 处置建议'])
    action_items = suggestions or [suggestion]
    for index, item in enumerate(action_items[:6]):
        priority = 'P0' if index == 0 else ('P1' if index < 3 else 'P2')
        lines.append(f'- **{priority}** {item}')
    if missing:
        lines.extend(['', '### 缺失证据'])
        lines.extend(f'- {item}' for item in missing[:8])
    lines.extend(['', '### 总结', f'- {result.get("summary") or root_cause}', '- 报告仅基于 Prometheus、K8s API、日志和变更证据，不包含模型思维链。'])
    return '\n'.join(lines)


def _default_body(alert, action='fire'):
    raw, event, _rule, _evidence = _notification_payload(alert)
    if action == 'analysis':
        confidence, root_cause, evidence_text, suggestion = _analysis_content(alert, raw)
        status_text = '告警仍活跃' if alert.status == Alert.STATUS_ACTIVE else '研判期间已恢复'
        return '\n'.join([
            f'**研判状态：** {status_text}',
            f'**研判结论：** {root_cause}',
            f'**置信度：** {confidence}',
            f'**关键证据：** {evidence_text}',
            f'**优先建议：** {suggestion}',
            '',
            '完整指标、K8S状态、事件、日志、反向证据和处置建议请点击“查看详情”。',
        ])

    object_name = alert.resource or (alert.host.hostname if alert.host else '') or '-'
    level_icon = {'critical': '🔴', 'warning': '🟡', 'info': '🔵'}.get(alert.level, '🟡')
    status_text = '🟢 已恢复' if action == 'resolved' else '🔥 告警中'
    description = _text(_dict(alert.annotations).get('description')) or '无描述'
    lines = [
        f'📛 **告警名称：** {alert.title}',
        f'⚡ **严重程度：** {level_icon} {str(alert.level or "warning").upper()}',
        f'📍 **当前状态：** {status_text}',
        f'🎯 **影响范围：** {alert.namespace or "-"}/{object_name}',
        f'📝 **告警摘要：** {alert.message or _human_description(alert, event)}',
        f'📋 **详细描述：** {description}',
    ]
    if action == 'resolved':
        resolved_at = alert.ends_at or alert.last_received_at or timezone.now()
        lines.extend([
            f'**恢复时间：** {_format_datetime(resolved_at)}',
            f'**持续时间：** {_format_duration(alert.starts_at, resolved_at)}',
        ])
    else:
        lines.append(f'🕐 **发生时间：** {_format_datetime(alert.starts_at)}')
        latest_analysis = alert.analyses.order_by('-created_at', '-id').first()
        ai_status = latest_analysis.status if latest_analysis else _dict(raw.get('ai_analysis')).get('status')
        if ai_status in {'pending', 'running'}:
            lines.append('⏳ **智能研判：** 正在执行精准研判，完成后将发送独立结果通知。')
        elif latest_analysis and latest_analysis.status in {'completed', 'partial'}:
            result = _dict(latest_analysis.result)
            conclusion = _first(latest_analysis.root_cause, result.get('summary'), '尚未形成明确结论')
            completed_at = _format_datetime(latest_analysis.completed_at)
            confidence = latest_analysis.confidence
            confidence_text = f'{confidence * 100:.0f}%' if isinstance(confidence, (int, float)) else '未评估'
            lines.append(f'🎯 **最近研判：** {conclusion}（置信度 {confidence_text}，{completed_at}）')
        title_text = f'{alert.title} {alert.message}'.lower()
        if any(token in title_text for token in ('重启', 'crashloop', 'pod', '容器')):
            lines.append('**简要建议：** 优先查看目标 Pod 的状态、Warning Event、当前日志和上次崩溃日志。')
    if alert.runbook_url:
        lines.append(f'**处理手册：** {alert.runbook_url}')
    return '\n'.join(lines)


def build_recipient_contacts(*, groups=None, recipients=None):
    result = defaultdict(set)
    names = set()
    selected_recipients = set(recipients or [])
    for group in groups or []:
        selected_recipients.update(group.recipients.filter(is_enabled=True))
        for user in group.users.filter(is_active=True):
            names.add(user.get_full_name() or user.username)
            if user.email:
                result['emails'].add(user.email)
    for recipient in selected_recipients:
        if not recipient.is_enabled:
            continue
        names.add(recipient.name)
        preferred = set(recipient.preferred_channels or [])
        legacy_mode = not preferred
        if recipient.email and (legacy_mode or 'email' in preferred):
            result['emails'].add(recipient.email)
        if recipient.phone and (legacy_mode or {'sms', 'voice'} & preferred):
            result['phones'].add(recipient.phone)
        if recipient.phone and (legacy_mode or 'sms' in preferred):
            result['sms_phones'].add(recipient.phone)
        if recipient.phone and (legacy_mode or 'voice' in preferred):
            result['voice_phones'].add(recipient.phone)
        if recipient.dingtalk_user_id:
            result['dingtalk_user_ids'].add(recipient.dingtalk_user_id)
        if recipient.feishu_user_id:
            result['feishu_user_ids'].add(recipient.feishu_user_id)
        if recipient.wecom_user_id:
            result['wecom_user_ids'].add(recipient.wecom_user_id)
        if recipient.user and recipient.user.email and (legacy_mode or 'email' in preferred):
            result['emails'].add(recipient.user.email)
    result['names'] = names
    return {key: sorted(value) for key, value in result.items()}


def _recipient_contacts(rule=None, policy=None):
    config = (rule.notify_config or {}) if rule else {}
    if policy is not None:
        groups = policy.recipient_groups.filter(is_enabled=True).prefetch_related('recipients', 'users')
    else:
        group_ids = _list(config.get('recipient_group_ids'))
        groups = AlertRecipientGroup.objects.filter(id__in=group_ids, is_enabled=True).prefetch_related('recipients', 'users')
    return build_recipient_contacts(groups=groups)


def _post_json(url, payload, timeout=8, headers=None):
    response = requests.post(url, json=payload, timeout=timeout, headers=headers or {})
    text = response.text[:1000]
    if response.status_code >= 400:
        raise RuntimeError(f'HTTP {response.status_code}: {text}')
    return text


def _feishu_sign(secret):
    timestamp = str(int(time.time()))
    string_to_sign = f'{timestamp}\n{secret}'
    digest = hmac.new(string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
    return timestamp, base64.b64encode(digest).decode('utf-8')


def _post_feishu_json(url, payload, timeout=8):
    response_body = _post_json(url, payload, timeout=timeout)
    try:
        data = json.loads(response_body)
    except (TypeError, ValueError):
        return response_body
    code = data.get('code')
    if code not in (None, 0, '0'):
        message = data.get('msg') or data.get('message') or response_body
        raise NotificationDeliveryError(f'Feishu API error {code}: {message}', response_body=response_body)
    return response_body


def _channel_url(channel):
    config = channel.config or {}
    url = _text(config.get('webhook_url') or config.get('url'))
    if url:
        return url
    token = _text(config.get('access_token') or config.get('token'))
    if channel.channel_type == AlertNotificationChannel.CHANNEL_DINGTALK and token:
        return f'https://oapi.dingtalk.com/robot/send?access_token={token}'
    if channel.channel_type == AlertNotificationChannel.CHANNEL_WECOM and token:
        return f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={token}'
    return ''


def _card_buttons(alert, provider, request=None, action='fire'):
    labels = {
        'acknowledge': '确认',
        'claim': '认领',
        'mute': '屏蔽 1 小时',
        'escalate': '升级',
    }
    buttons = []
    detail_url = _base_url(request)
    if detail_url:
        buttons.append({
            'action': 'detail',
            'title': '查看详情',
            'url': f'{detail_url}/observability/alerts/{alert.id}',
        })
    if action in {'analysis', 'resolved'}:
        return buttons
    for card_action in CARD_ACTIONS:
        url = _interaction_url(alert, card_action, provider=provider, request=request)
        if url:
            buttons.append({'action': card_action, 'title': labels[card_action], 'url': url})
    return buttons


def send_plain_notification(channel, recipients, *, title, body, action='inspection_report'):
    config = channel.config or {}
    status = AlertNotificationLog.STATUS_SUCCESS
    response_body = ''
    error_message = ''
    request_summary = {'channel_type': channel.channel_type, 'title': title, 'action': action}
    try:
        if channel.channel_type == AlertNotificationChannel.CHANNEL_EMAIL:
            emails = sorted(set(_list(config.get('to')) + recipients.get('emails', [])))
            if not emails:
                status = AlertNotificationLog.STATUS_SKIPPED
                response_body = '没有可用邮箱接收人'
            else:
                EmailMessage(title, body, getattr(settings, 'DEFAULT_FROM_EMAIL', None), emails).send(fail_silently=False)
                response_body = f'sent email to {len(emails)} recipients'
                request_summary['recipient_count'] = len(emails)
        elif channel.channel_type in {AlertNotificationChannel.CHANNEL_SMS, AlertNotificationChannel.CHANNEL_VOICE}:
            preferred_key = 'sms_phones' if channel.channel_type == AlertNotificationChannel.CHANNEL_SMS else 'voice_phones'
            phones = sorted(set(_list(config.get('phones')) + recipients.get(preferred_key, recipients.get('phones', []))))
            url = _channel_url(channel)
            if not phones or not url:
                status = AlertNotificationLog.STATUS_SKIPPED
                response_body = '没有手机号或渠道 webhook_url'
            else:
                payload = {
                    'phones': phones, 'title': title, 'content': body,
                    'config': {key: value for key, value in config.items() if key not in {'token', 'access_token', 'secret'}},
                }
                request_summary['recipient_count'] = len(phones)
                response_body = _post_json(url, payload, timeout=channel.timeout_seconds)
        elif channel.channel_type == AlertNotificationChannel.CHANNEL_DINGTALK:
            url = _channel_url(channel)
            if not url:
                status = AlertNotificationLog.STATUS_SKIPPED
                response_body = '未配置钉钉 webhook_url 或 access_token'
            else:
                payload = {'msgtype': 'markdown', 'markdown': {'title': title, 'text': body}}
                response_body = _post_json(url, payload, timeout=channel.timeout_seconds)
        elif channel.channel_type == AlertNotificationChannel.CHANNEL_FEISHU:
            url = _channel_url(channel)
            secret = _text(config.get('secret') or config.get('sign_secret'))
            if not url:
                status = AlertNotificationLog.STATUS_SKIPPED
                response_body = '未配置飞书 webhook_url'
            elif not secret:
                status = AlertNotificationLog.STATUS_SKIPPED
                response_body = '飞书渠道未配置签名密钥，已拒绝发送未签名通知'
            else:
                payload = {
                    'msg_type': 'interactive',
                    'card': {
                        'config': {'wide_screen_mode': True, 'enable_forward': True},
                        'header': {
                            'template': 'green',
                            'title': {'tag': 'plain_text', 'content': title},
                        },
                        'elements': [{'tag': 'markdown', 'content': body}],
                    },
                }
                timestamp, sign = _feishu_sign(secret)
                payload['timestamp'] = timestamp
                payload['sign'] = sign
                request_summary['signing'] = 'enabled'
                response_body = _post_feishu_json(url, payload, timeout=channel.timeout_seconds)
        elif channel.channel_type == AlertNotificationChannel.CHANNEL_WECOM:
            url = _channel_url(channel)
            if not url:
                status = AlertNotificationLog.STATUS_SKIPPED
                response_body = '未配置企微 webhook_url 或 key'
            else:
                payload = {'msgtype': 'markdown', 'markdown': {'content': f'**{title}**\n\n{body}'}}
                response_body = _post_json(url, payload, timeout=channel.timeout_seconds)
        else:
            status = AlertNotificationLog.STATUS_SKIPPED
            response_body = '未知通知渠道'
    except NotificationDeliveryError as exc:
        status = AlertNotificationLog.STATUS_ERROR
        response_body = exc.response_body
        error_message = str(exc)
    except Exception as exc:
        status = AlertNotificationLog.STATUS_ERROR
        error_message = str(exc)
    return {
        'channel_id': channel.id,
        'channel_name': channel.name,
        'channel_type': channel.channel_type,
        'status': status,
        'recipient_summary': ', '.join(recipients.get('names', [])[:20]),
        'request': request_summary,
        'response_body': response_body,
        'error_message': error_message,
        'sent_at': timezone.now().isoformat() if status == AlertNotificationLog.STATUS_SUCCESS else None,
    }


def send_alert_notification(channel, alert, recipients, action='fire', rule=None, policy=None, request=None):
    config = channel.config or {}
    title = _render(channel.template_title, alert, action) or _default_title(alert, action)
    body = _render(channel.template_body, alert, action) or _default_body(alert, action)
    status = AlertNotificationLog.STATUS_SUCCESS
    response_body = ''
    error_message = ''
    request_summary = {'channel_type': channel.channel_type, 'title': title, 'action': action, 'group_key': alert.group_key}
    if action == 'analysis':
        latest_analysis = alert.analyses.order_by('-created_at', '-id').first()
        if latest_analysis:
            request_summary['analysis_id'] = latest_analysis.id

    try:
        if channel.channel_type == AlertNotificationChannel.CHANNEL_EMAIL:
            emails = sorted(set(_list(config.get('to')) + recipients.get('emails', [])))
            if not emails:
                status = AlertNotificationLog.STATUS_SKIPPED
                response_body = '没有可用邮箱接收人'
            else:
                EmailMessage(title, body, getattr(settings, 'DEFAULT_FROM_EMAIL', None), emails).send(fail_silently=False)
                response_body = f'sent email to {len(emails)} recipients'
                request_summary['recipient_count'] = len(emails)
        elif channel.channel_type in {AlertNotificationChannel.CHANNEL_SMS, AlertNotificationChannel.CHANNEL_VOICE}:
            phones = sorted(set(_list(config.get('phones')) + recipients.get('phones', [])))
            url = _channel_url(channel)
            if not phones or not url:
                status = AlertNotificationLog.STATUS_SKIPPED
                response_body = '没有手机号或渠道 webhook_url'
            else:
                payload = {'phones': phones, 'title': title, 'content': body, 'alert': _alert_context(alert, action), 'config': {k: v for k, v in config.items() if k not in {'token', 'access_token', 'secret'}}}
                request_summary['recipient_count'] = len(phones)
                response_body = _post_json(url, payload, timeout=channel.timeout_seconds)
        elif channel.channel_type == AlertNotificationChannel.CHANNEL_DINGTALK:
            url = _channel_url(channel)
            if not url:
                status = AlertNotificationLog.STATUS_SKIPPED
                response_body = '未配置钉钉 webhook_url 或 access_token'
            else:
                buttons = _card_buttons(alert, 'dingtalk', request=request, action=action)
                payload = {
                    'msgtype': 'actionCard',
                    'actionCard': {
                        'title': title,
                        'text': body.replace('\n', '\n\n'),
                        'btnOrientation': '0',
                        'btns': [{'title': item['title'], 'actionURL': item['url']} for item in buttons],
                    },
                }
                if not buttons:
                    payload = {'msgtype': 'markdown', 'markdown': {'title': title, 'text': body}}
                request_summary['buttons'] = [item['action'] for item in buttons]
                response_body = _post_json(url, payload, timeout=channel.timeout_seconds)
        elif channel.channel_type == AlertNotificationChannel.CHANNEL_FEISHU:
            url = _channel_url(channel)
            if not url:
                status = AlertNotificationLog.STATUS_SKIPPED
                response_body = '未配置飞书 webhook_url'
            elif not _text(config.get('secret') or config.get('sign_secret')):
                status = AlertNotificationLog.STATUS_SKIPPED
                response_body = '飞书渠道未配置签名密钥，已拒绝发送未签名通知'
            else:
                buttons = _card_buttons(alert, 'feishu', request=request, action=action)
                payload = {
                    'msg_type': 'interactive',
                    'card': {
                        'config': {'wide_screen_mode': True, 'enable_forward': True},
                        'header': {
                            'template': 'green' if action == 'resolved' else ('blue' if action == 'analysis' else ('red' if alert.level == 'critical' else 'orange')),
                            'title': {'tag': 'plain_text', 'content': title},
                        },
                        'elements': [
                            {'tag': 'markdown', 'content': body},
                            {'tag': 'action', 'actions': [
                                {'tag': 'button', 'text': {'tag': 'plain_text', 'content': item['title']}, 'url': item['url'], 'type': 'primary' if item['action'] == 'detail' else 'default'}
                                for item in buttons
                            ]},
                        ],
                    },
                }
                secret = _text(config.get('secret') or config.get('sign_secret'))
                timestamp, sign = _feishu_sign(secret)
                payload['timestamp'] = timestamp
                payload['sign'] = sign
                request_summary['buttons'] = [item['action'] for item in buttons]
                request_summary['signing'] = 'enabled'
                response_body = _post_feishu_json(url, payload, timeout=channel.timeout_seconds)
        elif channel.channel_type == AlertNotificationChannel.CHANNEL_WECOM:
            url = _channel_url(channel)
            if not url:
                status = AlertNotificationLog.STATUS_SKIPPED
                response_body = '未配置企微 webhook_url 或 key'
            else:
                button_text = '\n'.join([f'[{item["title"]}]({item["url"]})' for item in _card_buttons(alert, 'wecom', request=request, action=action)])
                title_color = 'info' if action == 'resolved' else ('comment' if action == 'analysis' else 'warning')
                colored_title = f'<font color="{title_color}">**{title}**</font>'
                payload = {'msgtype': 'markdown', 'markdown': {'content': f'{colored_title}\n\n{body}\n\n{button_text}'.rstrip()}}
                response_body = _post_json(url, payload, timeout=channel.timeout_seconds)
        else:
            status = AlertNotificationLog.STATUS_SKIPPED
            response_body = '未知通知渠道'
    except NotificationDeliveryError as exc:
        status = AlertNotificationLog.STATUS_ERROR
        response_body = exc.response_body
        error_message = str(exc)
    except Exception as exc:
        status = AlertNotificationLog.STATUS_ERROR
        error_message = str(exc)

    log = AlertNotificationLog.objects.create(
        alert=alert,
        rule_id=getattr(rule, 'id', None),
        policy_id=getattr(policy, 'id', None),
        channel_id=channel.id,
        action=action,
        status=status,
        recipient_summary=', '.join(recipients.get('names', [])[:20]),
        request_payload=request_summary,
        response_body=response_body,
        error_message=error_message,
        sent_at=timezone.now() if status == AlertNotificationLog.STATUS_SUCCESS else None,
    )
    _save_action(
        alert,
        AlertAction.ACTION_NOTIFY,
        actor='system',
        note=f'{channel.name}: {log.get_status_display()}',
        metadata={
            'channel_type': channel.channel_type,
            'log_id': log.id,
            'notification_action': action,
            'analysis_id': request_summary.get('analysis_id'),
        },
    )
    return log


def _alert_rule(alert):
    labels = alert.labels if isinstance(alert.labels, dict) else {}
    rule_id = labels.get('alert_rule_id')
    if not rule_id:
        return None
    try:
        return AlertRule.objects.select_related('metric_datasource').get(pk=rule_id, is_enabled=True, is_template=False, notify_enabled=True)
    except (AlertRule.DoesNotExist, TypeError, ValueError):
        return None


def _rule_can_send(rule, action):
    config = rule.notify_config or {}
    if action == 'resolved':
        return config.get('notify_on_resolved', True)
    if action == 'fire':
        return config.get('notify_on_fire', True)
    return action != 'escalation' or rule.escalation_minutes > 0


def _policy_action_enabled(policy, action):
    if action == 'fire':
        return policy.notify_on_fire
    if action == 'resolved':
        return policy.notify_on_resolved
    if action == 'analysis':
        return getattr(policy, 'notify_on_analysis', False)
    return True


def _activity_cycle_start(alert):
    """Return the start boundary used to inherit the current alert cycle's delivery."""
    return alert.starts_at or alert.created_at or timezone.now()


def _successful_fire_channel_ids(alert, policy=None):
    """Channels that actually delivered the first notification in this activity cycle."""
    cycle_start = _activity_cycle_start(alert)
    logs = AlertNotificationLog.objects.filter(
        alert=alert,
        action='fire',
        status=AlertNotificationLog.STATUS_SUCCESS,
        created_at__gte=cycle_start,
    )
    if policy is not None:
        logs = logs.filter(policy_id=policy.id)
    return set(logs.values_list('channel_id', flat=True))


def analysis_notification_gate(alert, policy=None):
    """Decide whether analysis may follow a notification that was actually delivered.

    Analysis is evidence for an alert, not an independent alert.  It must not
    bypass silence, inhibition, storm aggregation, or a policy/channel that did
    not deliver the first alert in the current activity cycle.
    """
    if alert.is_suppressed or alert.status == Alert.STATUS_MUTED:
        return False, '告警已静默或屏蔽，研判结果仅保存在平台详情'
    if policy is not None:
        now = timezone.now()
        if not _policy_action_enabled(policy, 'analysis'):
            return False, '命中的通知策略未开启研判通知，结果仅保存在平台详情'
        if _policy_is_muted(policy, timezone.localtime(now)):
            return False, '命中的通知策略当前处于静默时段，研判结果仅保存在平台详情'
        if _policy_inhibits_alert(policy, alert):
            return False, '告警被通知策略抑制，研判结果仅保存在平台详情'
    payload = alert.raw_payload or {}
    batch = payload.get('fire_notification_batch') or payload.get('notification_batch') or {}
    if batch.get('mode') == 'storm':
        return False, '告警已被聚合/风暴降噪，研判结果仅保存在平台详情'
    if not _successful_fire_channel_ids(alert, policy=policy):
        return False, '首次告警未实际发送，研判结果仅保存在平台详情'
    return True, ''


def _policy_is_muted(policy, now=None):
    schedule = policy.mute_schedule if isinstance(policy.mute_schedule, dict) else {}
    if not schedule:
        return False
    now = now or timezone.localtime()
    weekdays = schedule.get('weekdays')
    if weekdays and now.weekday() not in [int(value) for value in weekdays]:
        return False
    start_text = str(schedule.get('start_time') or '').strip()
    end_text = str(schedule.get('end_time') or '').strip()
    if not start_text or not end_text:
        return bool(schedule.get('enabled', False))
    try:
        start_parts = [int(value) for value in start_text.split(':')[:2]]
        end_parts = [int(value) for value in end_text.split(':')[:2]]
        current = now.hour * 60 + now.minute
        start = start_parts[0] * 60 + start_parts[1]
        end = end_parts[0] * 60 + end_parts[1]
    except (TypeError, ValueError, IndexError):
        return False
    return start <= current < end if start <= end else current >= start or current < end


def resolve_notification_policies(alert, rule=None, metric_datasource_id=None):
    labels = alert.labels if isinstance(alert.labels, dict) else {}
    datasource_id = metric_datasource_id or getattr(rule, 'metric_datasource_id', None) or labels.get('metric_datasource_id')
    queryset = AlertNotificationPolicy.objects.filter(is_enabled=True).select_related('metric_datasource').prefetch_related('channels', 'recipient_groups')
    if datasource_id not in (None, ''):
        queryset = queryset.filter(Q(metric_datasource__isnull=True) | Q(metric_datasource_id=datasource_id))
    else:
        queryset = queryset.filter(metric_datasource__isnull=True)
    matched = []
    for policy in queryset.order_by('priority', 'id'):
        if policy.min_level and LEVEL_RANK.get(alert.level, 0) < LEVEL_RANK.get(policy.min_level, 0):
            continue
        if not match_matchers(alert, policy.matchers):
            continue
        matched.append(policy)
        if not policy.continue_matching:
            break
    return matched


def dispatch_alert_notifications(alert, action='fire', request=None, force=False):
    if action == 'analysis' and alert.status not in {Alert.STATUS_ACTIVE, Alert.STATUS_RESOLVED}:
        return []
    if (not force or action == 'analysis') and (alert.is_suppressed or alert.status == Alert.STATUS_MUTED):
        return []
    if action == 'resolved' and alert.status != Alert.STATUS_RESOLVED:
        return []

    rule = _alert_rule(alert)
    if not rule or not _rule_can_send(rule, action):
        return []

    policies = resolve_notification_policies(alert, rule=rule)
    if policies:
        logs = []
        now = timezone.now()
        for policy in policies:
            if not _policy_action_enabled(policy, action) or _policy_is_muted(policy, timezone.localtime(now)):
                continue
            if _policy_inhibits_alert(policy, alert):
                continue
            analysis_channel_ids = None
            if action == 'analysis':
                allowed, _reason = analysis_notification_gate(alert, policy=policy)
                if not allowed:
                    continue
                analysis_channel_ids = _successful_fire_channel_ids(alert, policy=policy)
            channels = list(policy.channels.filter(is_enabled=True))
            if analysis_channel_ids is not None:
                channels = [channel for channel in channels if channel.id in analysis_channel_ids]
            if action == 'resolved':
                channels = [channel for channel in channels if channel.send_resolved]
            if not channels:
                continue
            group_by = list(policy.group_by or DEFAULT_GROUP_BY)
            datasource_dimension = 'label.metric_datasource_id'
            if datasource_dimension not in group_by:
                group_by.insert(0, datasource_dimension)
            alert.group_key = compute_group_key(alert, group_by)
            alert.save(update_fields=['group_key', 'updated_at'])
            started_at = alert.starts_at or alert.created_at or now
            if not force and action == 'fire' and (now - started_at).total_seconds() < policy.group_wait_seconds:
                continue
            if not force and AlertNotificationLog.objects.filter(
                policy_id=policy.id,
                action=action,
                status=AlertNotificationLog.STATUS_SUCCESS,
                alert__group_key=alert.group_key,
                created_at__gte=now - timedelta(seconds=policy.group_interval_seconds),
            ).exists():
                continue
            if not force and AlertNotificationLog.objects.filter(
                alert=alert,
                policy_id=policy.id,
                action=action,
                status=AlertNotificationLog.STATUS_SUCCESS,
                created_at__gte=now - timedelta(minutes=policy.repeat_interval_minutes),
            ).exists():
                continue
            recipients = _recipient_contacts(policy=policy)
            logs.extend([
                send_alert_notification(channel, alert, recipients, action=action, rule=rule, policy=policy, request=request)
                for channel in channels
            ])
        return logs

    if action == 'analysis':
        return []

    config = rule.notify_config or {}
    channel_ids = _list(config.get('channel_ids'))
    channels = list(AlertNotificationChannel.objects.filter(id__in=channel_ids, is_enabled=True))
    if action == 'resolved':
        channels = [channel for channel in channels if channel.send_resolved]
    if not channels:
        return []

    alert.group_key = compute_group_key(alert, DEFAULT_GROUP_BY)
    alert.save(update_fields=['group_key', 'updated_at'])
    since = timezone.now() - timedelta(minutes=rule.repeat_interval)
    if not force and AlertNotificationLog.objects.filter(
        alert=alert,
        rule_id=rule.id,
        action=action,
        created_at__gte=since,
        status=AlertNotificationLog.STATUS_SUCCESS,
    ).exists():
        return []

    recipients = _recipient_contacts(rule)
    return [
        send_alert_notification(channel, alert, recipients, action=action, rule=rule, request=request)
        for channel in channels
    ]


def _storm_group_key(alert):
    return '|'.join([
        alert.environment or '-',
        alert.cluster or '-',
        alert.namespace or '-',
        alert.resource or alert.service or '-',
    ])


def _storm_threshold_for_alert(alert, fallback=3):
    rule = _alert_rule(alert)
    thresholds = [
        max(1, int(policy.storm_threshold or fallback))
        for policy in resolve_notification_policies(alert, rule=rule)
        if policy.is_enabled
    ]
    return min(thresholds) if thresholds else fallback


def _mark_notification_batch(alert, batch):
    raw_payload = dict(alert.raw_payload or {})
    raw_payload['notification_batch'] = batch
    if batch.get('action') == 'fire':
        raw_payload['fire_notification_batch'] = batch
    alert.raw_payload = raw_payload
    alert.save(update_fields=['raw_payload', 'updated_at'])


def dispatch_alert_batch_notifications(alerts, action='fire', request=None, force=False, storm_threshold=3):
    alerts = [alert for alert in alerts or [] if alert]
    if not alerts:
        return {'notified_count': 0, 'notification_logs': [], 'storm_batches': []}

    logs = []
    notified = set()
    storm_batches = []
    groups = defaultdict(list)
    for alert in alerts:
        groups[_storm_group_key(alert)].append(alert)

    for group_key, group_alerts in groups.items():
        group_threshold = min(_storm_threshold_for_alert(alert, storm_threshold) for alert in group_alerts)
        if len(group_alerts) >= group_threshold:
            ordered = sorted(group_alerts, key=lambda item: (LEVEL_RANK.get(item.level, 0), item.created_at or timezone.now()), reverse=True)
            primary = ordered[0]
            batch = {
                'mode': 'storm',
                'group_key': group_key,
                'count': len(group_alerts),
                'threshold': group_threshold,
                'primary_alert_id': primary.id,
                'action': action,
            }
            storm_batches.append(batch)
            for alert in group_alerts:
                _mark_notification_batch(alert, {**batch, 'role': 'primary' if alert.id == primary.id else 'timeline_only'})
            if primary.id not in notified:
                logs.extend(dispatch_alert_notifications(primary, action=action, request=request, force=force))
                notified.add(primary.id)
            continue

        for alert in group_alerts:
            if alert.id in notified:
                continue
            _mark_notification_batch(alert, {
                'mode': 'single',
                'group_key': group_key,
                'count': 1,
                'primary_alert_id': alert.id,
                'action': action,
            })
            logs.extend(dispatch_alert_notifications(alert, action=action, request=request, force=force))
            notified.add(alert.id)

    return {
        'notified_count': len(notified),
        'notification_logs': logs,
        'storm_batches': storm_batches,
    }


def apply_escalation_policy(alert, request=None):
    if alert.status not in {Alert.STATUS_ACTIVE, Alert.STATUS_MUTED}:
        return False
    rule = _alert_rule(alert)
    if not rule:
        return False
    now = timezone.now()
    started_at = alert.starts_at or alert.created_at or now
    duration_minutes = max(int((now - started_at).total_seconds() // 60), 0)

    for policy in resolve_notification_policies(alert, rule=rule):
        steps = [item for item in (policy.escalation_steps or []) if isinstance(item, dict)]
        steps.sort(key=lambda item: int(item.get('after_minutes') or 0))
        next_index = int(alert.escalation_level or 0)
        if next_index >= len(steps):
            continue
        step = steps[next_index]
        after_minutes = max(int(step.get('after_minutes') or 0), 0)
        if duration_minutes < after_minutes:
            continue
        channel_ids = _list(step.get('channel_ids'))
        channels = list(policy.channels.filter(is_enabled=True)) if not channel_ids else list(AlertNotificationChannel.objects.filter(id__in=channel_ids, is_enabled=True))
        recipients = _recipient_contacts(policy=policy)
        alert.escalation_level = next_index + 1
        alert.escalated_at = now
        alert.save(update_fields=['escalation_level', 'escalated_at', 'updated_at'])
        _save_action(
            alert,
            AlertAction.ACTION_ESCALATE,
            actor='system',
            note=f'通知策略 {policy.name} 执行第 {next_index + 1} 级升级',
            metadata={'rule_id': rule.id, 'policy_id': policy.id, 'duration_minutes': duration_minutes},
        )
        for channel in channels:
            send_alert_notification(channel, alert, recipients, action='escalation', rule=rule, policy=policy, request=request)
        return True

    if rule.escalation_minutes <= 0:
        return False
    if duration_minutes < rule.escalation_minutes or alert.escalation_level >= 1:
        return False
    alert.escalation_level = 1
    alert.escalated_at = now
    alert.save(update_fields=['escalation_level', 'escalated_at', 'updated_at'])
    _save_action(
        alert,
        AlertAction.ACTION_ESCALATE,
        actor='system',
        note=f'告警规则 {rule.name} 超时升级',
        metadata={'rule_id': rule.id, 'duration_minutes': duration_minutes},
    )
    dispatch_alert_notifications(alert, action='escalation', request=request, force=True)
    return True


def apply_alert_action(alert, action, actor='', note='', metadata=None, request=None, mute_minutes=60):
    now = timezone.now()
    metadata = metadata or {}
    if action == AlertAction.ACTION_ACKNOWLEDGE:
        alert.is_acknowledged = True
        alert.acknowledged_by = actor
        alert.acknowledged_at = now
        update_fields = ['is_acknowledged', 'acknowledged_by', 'acknowledged_at', 'updated_at']
    elif action == AlertAction.ACTION_CLAIM:
        if actor:
            AlertClaim.objects.get_or_create(alert=alert, claimant=actor)
        getattr(alert, '_prefetched_objects_cache', {}).pop('claim_records', None)
        claim_records = _claim_records(alert)
        alert.claimed_by = claim_records[0].claimant if claim_records else (actor or '')
        alert.claimed_at = claim_records[0].claimed_at if claim_records else now
        update_fields = ['claimed_by', 'claimed_at', 'updated_at']
    elif action == AlertAction.ACTION_UNCLAIM:
        if actor:
            AlertClaim.objects.filter(alert=alert, claimant=actor).delete()
        getattr(alert, '_prefetched_objects_cache', {}).pop('claim_records', None)
        claim_records = _claim_records(alert)
        alert.claimed_by = claim_records[0].claimant if claim_records else ''
        alert.claimed_at = claim_records[0].claimed_at if claim_records else None
        update_fields = ['claimed_by', 'claimed_at', 'updated_at']
    elif action == AlertAction.ACTION_MUTE:
        alert.status = Alert.STATUS_MUTED
        alert.is_suppressed = True
        alert.suppressed_by = 'manual_mute'
        alert.suppressed_until = now + timedelta(minutes=mute_minutes)
        alert.mute_until = alert.suppressed_until
        alert.muted_by = actor
        alert.muted_reason = note or f'屏蔽 {mute_minutes} 分钟'
        update_fields = ['status', 'is_suppressed', 'suppressed_by', 'suppressed_until', 'mute_until', 'muted_by', 'muted_reason', 'updated_at']
    elif action == AlertAction.ACTION_ESCALATE:
        alert.escalation_level = alert.escalation_level + 1
        alert.escalated_at = now
        update_fields = ['escalation_level', 'escalated_at', 'updated_at']
    elif action == AlertAction.ACTION_RESOLVE:
        alert.status = Alert.STATUS_RESOLVED
        alert.ends_at = now
        update_fields = ['status', 'ends_at', 'updated_at']
    elif action == AlertAction.ACTION_CLOSE:
        alert.status = Alert.STATUS_CLOSED
        alert.closed_at = now
        update_fields = ['status', 'closed_at', 'updated_at']
    elif action == AlertAction.ACTION_REOPEN:
        alert.status = Alert.STATUS_ACTIVE
        alert.closed_at = None
        alert.ends_at = None
        alert.is_acknowledged = False
        alert.is_suppressed = False
        update_fields = ['status', 'closed_at', 'ends_at', 'is_acknowledged', 'is_suppressed', 'updated_at']
    else:
        update_fields = ['updated_at']
    alert.save(update_fields=update_fields)
    action_record = _save_action(alert, action, actor=actor, note=note, metadata=metadata)
    if action == AlertAction.ACTION_ESCALATE:
        dispatch_alert_notifications(alert, action='escalation', request=request, force=True)
    return action_record


def handle_interaction_token(token_value, request=None, execute=False):
    token = AlertInteractionToken.objects.select_related('alert').filter(token=token_value).first()
    if not token:
        return False, '交互令牌不存在', None, None
    if not token.is_available:
        return False, '交互令牌已过期或已使用', token.alert, token
    if not execute:
        return True, '请确认告警操作', token.alert, token
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return False, '请登录后执行告警操作', token.alert, token
    actor = user.username
    note = f'{token.provider or "通知卡片"}按钮确认操作'
    apply_alert_action(token.alert, token.action, actor=actor, note=note, metadata={'token': str(token.token)}, request=request)
    token.used_at = timezone.now()
    token.save(update_fields=['used_at'])
    return True, '告警操作已处理', token.alert, token


def alert_group_summary(queryset, group_by=None, limit=5000):
    group_by = [item for item in (group_by or DEFAULT_GROUP_BY) if item]
    groups = {}
    for alert in queryset.order_by('-created_at')[:limit]:
        values = {key: alert_dimension_value(alert, key) or '-' for key in group_by}
        key = ' | '.join([f'{name}={value}' for name, value in values.items()])
        if key not in groups:
            groups[key] = {
                'key': key,
                'dimensions': values,
                'total': 0,
                'critical': 0,
                'warning': 0,
                'info': 0,
                'unacknowledged': 0,
                'suppressed': 0,
                'latest_at': None,
                'sample_alert_id': None,
                'sample_title': '',
            }
        item = groups[key]
        item['total'] += 1
        item[alert.level] = item.get(alert.level, 0) + 1
        if not _has_claimants(alert):
            item['unacknowledged'] += 1
        if alert.is_suppressed or alert.status == Alert.STATUS_MUTED:
            item['suppressed'] += 1
        if not item['latest_at'] or alert.created_at > item['latest_at']:
            item['latest_at'] = alert.created_at
            item['sample_alert_id'] = alert.id
            item['sample_title'] = alert.title
    data = list(groups.values())
    for item in data:
        item['latest_at'] = item['latest_at'].isoformat() if item['latest_at'] else ''
    data.sort(key=lambda item: (item['critical'], item['warning'], item['total']), reverse=True)
    return data


def alert_summary(queryset):
    alerts = list(queryset)
    level_counter = Counter(alert.level for alert in alerts)
    status_counter = Counter(alert.status for alert in alerts)
    return {
        'total': len(alerts),
        'critical': level_counter.get('critical', 0),
        'warning': level_counter.get('warning', 0),
        'info': level_counter.get('info', 0),
        'active': status_counter.get(Alert.STATUS_ACTIVE, 0),
        'resolved': status_counter.get(Alert.STATUS_RESOLVED, 0),
        'muted': status_counter.get(Alert.STATUS_MUTED, 0),
        'closed': status_counter.get(Alert.STATUS_CLOSED, 0),
        'unacknowledged': sum(1 for alert in alerts if not _has_claimants(alert)),
        'claimed': sum(1 for alert in alerts if _has_claimants(alert)),
        'suppressed': sum(1 for alert in alerts if alert.is_suppressed or alert.status == Alert.STATUS_MUTED),
    }


