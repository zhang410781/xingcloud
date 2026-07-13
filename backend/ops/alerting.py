import base64
import hashlib
import hmac
import json
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
    AlertAction,
    AlertAggregationRule,
    AlertClaim,
    AlertEscalationPolicy,
    AlertInhibitionRule,
    AlertInteractionToken,
    AlertMuteRule,
    AlertNotificationChannel,
    AlertNotificationLog,
    AlertNotificationRule,
    AlertRecipient,
    Host,
)


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
        'labels': normalized.get('labels') or {},
        'annotations': normalized.get('annotations') or {},
        'raw_payload': normalized.get('raw_payload') or {},
        'starts_at': normalized.get('starts_at'),
        'ends_at': normalized.get('ends_at') if status_value == Alert.STATUS_RESOLVED else None,
        'last_received_at': now,
    }
    defaults['host'] = _host_for(defaults['resource'], defaults['labels'])

    created = existing is None
    if created:
        alert = Alert.objects.create(**defaults)
    else:
        alert = existing
        was_resolved = alert.status == Alert.STATUS_RESOLVED
        for field, value in defaults.items():
            if field == 'starts_at' and alert.starts_at:
                continue
            setattr(alert, field, value)
        alert.occurrence_count = alert.occurrence_count + 1
        if status_value == Alert.STATUS_ACTIVE and was_resolved:
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
        op = _text(matcher.get('op') or matcher.get('func') or '==')
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


def apply_alert_suppression(alert):
    now = timezone.now()
    changed = False
    mute = AlertMuteRule.objects.filter(is_enabled=True).filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=now),
        Q(ends_at__isnull=True) | Q(ends_at__gte=now),
    ).order_by('-created_at').first()
    matched_mute = None
    for rule in AlertMuteRule.objects.filter(is_enabled=True).filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=now),
        Q(ends_at__isnull=True) | Q(ends_at__gte=now),
    ):
        if match_matchers(alert, rule.matchers):
            matched_mute = rule
            break
    if matched_mute:
        alert.status = Alert.STATUS_MUTED
        alert.is_suppressed = True
        alert.suppressed_by = f'mute:{matched_mute.name}'
        alert.suppressed_until = matched_mute.ends_at
        alert.mute_until = matched_mute.ends_at
        alert.muted_reason = matched_mute.reason
        changed = True
    elif alert.mute_until and alert.mute_until > now:
        alert.status = Alert.STATUS_MUTED
        alert.is_suppressed = True
        alert.suppressed_by = 'manual_mute'
        alert.suppressed_until = alert.mute_until
        changed = True
    else:
        inhibited_by = None
        inhibit_until = None
        for rule in AlertInhibitionRule.objects.filter(is_enabled=True):
            if not match_matchers(alert, rule.target_matchers):
                continue
            source_qs = Alert.objects.filter(status=Alert.STATUS_ACTIVE).exclude(pk=alert.pk)
            for source_alert in source_qs[:300]:
                if not match_matchers(source_alert, rule.source_matchers):
                    continue
                equal_labels = rule.equal_labels or []
                if all(alert_dimension_value(alert, key) == alert_dimension_value(source_alert, key) for key in equal_labels):
                    inhibited_by = rule
                    inhibit_until = now + timedelta(minutes=rule.duration_minutes)
                    break
            if inhibited_by:
                break
        alert.is_suppressed = bool(inhibited_by)
        alert.suppressed_by = f'inhibit:{inhibited_by.name}' if inhibited_by else ''
        alert.suppressed_until = inhibit_until
        changed = True
    if changed:
        alert.save(update_fields=['status', 'is_suppressed', 'suppressed_by', 'suppressed_until', 'mute_until', 'muted_reason', 'updated_at'])
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
    token = AlertInteractionToken.objects.create(
        alert=alert,
        action=action,
        provider=provider or '',
        expires_at=timezone.now() + timedelta(days=7),
    )
    base = _base_url(request)
    if not base:
        return ''
    return f'{base}/api/alerts/card-actions/{token.token}/'


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
    return alert.title


def _default_body(alert, action='fire'):
    lines = [
        f'级别: {alert.get_level_display()}',
        f'状态: {alert.get_status_display()}',
        f'来源: {alert.source_type} / {alert.source}',
        f'对象: {alert.resource or alert.host.hostname if alert.host else alert.resource or "-"}',
        f'服务: {alert.service or "-"}',
        f'环境: {alert.environment or "-"}',
        f'时间: {alert.starts_at.strftime("%Y-%m-%d %H:%M:%S") if alert.starts_at else "-"}',
        '',
        alert.message or alert.title,
    ]
    if alert.runbook_url:
        lines.append(f'Runbook: {alert.runbook_url}')
    return '\n'.join(lines)


def _recipient_contacts(rule):
    result = defaultdict(set)
    names = set()
    recipients = set(rule.recipients.filter(is_enabled=True))
    for group in rule.recipient_groups.filter(is_enabled=True).prefetch_related('recipients', 'users'):
        recipients.update(group.recipients.filter(is_enabled=True))
        for user in group.users.filter(is_active=True):
            names.add(user.get_full_name() or user.username)
            if user.email:
                result['emails'].add(user.email)
    for recipient in recipients:
        names.add(recipient.name)
        if recipient.email:
            result['emails'].add(recipient.email)
        if recipient.phone:
            result['phones'].add(recipient.phone)
        if recipient.dingtalk_user_id:
            result['dingtalk_user_ids'].add(recipient.dingtalk_user_id)
        if recipient.feishu_user_id:
            result['feishu_user_ids'].add(recipient.feishu_user_id)
        if recipient.wecom_user_id:
            result['wecom_user_ids'].add(recipient.wecom_user_id)
        if recipient.user and recipient.user.email:
            result['emails'].add(recipient.user.email)
    result['names'] = names
    return {key: sorted(value) for key, value in result.items()}


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


def _card_buttons(alert, provider, request=None):
    labels = {
        'acknowledge': '确认',
        'claim': '认领',
        'mute': '屏蔽 1 小时',
        'escalate': '升级',
    }
    buttons = []
    for action in CARD_ACTIONS:
        url = _interaction_url(alert, action, provider=provider, request=request)
        if url:
            buttons.append({'action': action, 'title': labels[action], 'url': url})
    return buttons


def send_alert_notification(channel, alert, recipients, action='fire', rule=None, request=None):
    config = channel.config or {}
    title = _render(channel.template_title, alert, action) or _default_title(alert, action)
    body = _render(channel.template_body, alert, action) or _default_body(alert, action)
    status = AlertNotificationLog.STATUS_SUCCESS
    response_body = ''
    error_message = ''
    request_summary = {'channel_type': channel.channel_type, 'title': title, 'action': action, 'group_key': alert.group_key}

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
                buttons = _card_buttons(alert, 'dingtalk', request=request)
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
            else:
                buttons = _card_buttons(alert, 'feishu', request=request)
                payload = {
                    'msg_type': 'interactive',
                    'card': {
                        'config': {'wide_screen_mode': True, 'enable_forward': True},
                        'header': {'template': 'red' if alert.level == 'critical' else 'orange', 'title': {'tag': 'plain_text', 'content': title}},
                        'elements': [
                            {'tag': 'markdown', 'content': body},
                            {'tag': 'action', 'actions': [
                                {'tag': 'button', 'text': {'tag': 'plain_text', 'content': item['title']}, 'url': item['url'], 'type': 'primary' if item['action'] == 'acknowledge' else 'default'}
                                for item in buttons
                            ]},
                        ],
                    },
                }
                secret = _text(config.get('secret') or config.get('sign_secret'))
                if secret:
                    timestamp, sign = _feishu_sign(secret)
                    payload['timestamp'] = timestamp
                    payload['sign'] = sign
                request_summary['buttons'] = [item['action'] for item in buttons]
                response_body = _post_feishu_json(url, payload, timeout=channel.timeout_seconds)
        elif channel.channel_type == AlertNotificationChannel.CHANNEL_WECOM:
            url = _channel_url(channel)
            if not url:
                status = AlertNotificationLog.STATUS_SKIPPED
                response_body = '未配置企微 webhook_url 或 key'
            else:
                button_text = '\n'.join([f'[{item["title"]}]({item["url"]})' for item in _card_buttons(alert, 'wecom', request=request)])
                payload = {'msgtype': 'markdown', 'markdown': {'content': f'**{title}**\n\n{body}\n\n{button_text}'}}
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
        rule=rule,
        channel=channel,
        action=action,
        status=status,
        recipient_summary=', '.join(recipients.get('names', [])[:20]),
        request_payload=request_summary,
        response_body=response_body,
        error_message=error_message,
        sent_at=timezone.now() if status == AlertNotificationLog.STATUS_SUCCESS else None,
    )
    _save_action(alert, AlertAction.ACTION_NOTIFY, actor='system', note=f'{channel.name}: {log.get_status_display()}', metadata={'channel_type': channel.channel_type, 'log_id': log.id})
    return log


def _rule_can_send(rule, alert, action):
    if not rule.is_enabled:
        return False
    if action == 'resolved' and not rule.notify_on_resolved:
        return False
    if action == 'escalation' and not rule.notify_on_escalation:
        return False
    if action == 'fire' and not rule.notify_on_fire:
        return False
    if rule.min_level and LEVEL_RANK.get(alert.level, 0) < LEVEL_RANK.get(rule.min_level, 0):
        return False
    return match_matchers(alert, rule.matchers)


def dispatch_alert_notifications(alert, action='fire', request=None, force=False):
    if not force and (alert.is_suppressed or alert.status == Alert.STATUS_MUTED):
        return []
    if action == 'resolved' and alert.status != Alert.STATUS_RESOLVED:
        return []
    logs = []
    rules = AlertNotificationRule.objects.filter(is_enabled=True).prefetch_related('channels', 'recipients', 'recipient_groups__recipients', 'recipient_groups__users')
    for rule in rules:
        if not _rule_can_send(rule, alert, action):
            continue
        recipients = _recipient_contacts(rule)
        channels = [channel for channel in rule.channels.all() if channel.is_enabled]
        if action == 'resolved':
            channels = [channel for channel in channels if channel.send_resolved]
        if not channels:
            continue
        aggregation = rule.aggregation_rule
        if aggregation and aggregation.is_enabled:
            group_key = compute_group_key(alert, aggregation.group_by or DEFAULT_GROUP_BY)
            alert.group_key = group_key
            alert.save(update_fields=['group_key', 'updated_at'])
            since = timezone.now() - timedelta(minutes=aggregation.repeat_interval_minutes)
            if not force and AlertNotificationLog.objects.filter(alert=alert, rule=rule, action=action, created_at__gte=since, status=AlertNotificationLog.STATUS_SUCCESS).exists():
                continue
        for channel in channels:
            logs.append(send_alert_notification(channel, alert, recipients, action=action, rule=rule, request=request))
    return logs


def _storm_group_key(alert):
    return '|'.join([
        alert.environment or '-',
        alert.cluster or '-',
        alert.namespace or '-',
        alert.resource or alert.service or '-',
    ])


def _mark_notification_batch(alert, batch):
    raw_payload = dict(alert.raw_payload or {})
    raw_payload['notification_batch'] = batch
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
        if len(group_alerts) >= storm_threshold:
            ordered = sorted(group_alerts, key=lambda item: (LEVEL_RANK.get(item.level, 0), item.created_at or timezone.now()), reverse=True)
            primary = ordered[0]
            batch = {
                'mode': 'storm',
                'group_key': group_key,
                'count': len(group_alerts),
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
    policy = matching_escalation_policy(alert)
    if not policy or not policy.levels:
        return False
    now = timezone.now()
    started_at = alert.starts_at or alert.created_at or now
    duration_minutes = max(int((now - started_at).total_seconds() // 60), 0)
    target_level = alert.escalation_level
    matched_level = None
    for index, item in enumerate(policy.levels):
        try:
            after_minutes = int(item.get('after_minutes') or item.get('minutes') or 0)
        except (TypeError, ValueError):
            after_minutes = 0
        if duration_minutes >= after_minutes and index + 1 > target_level:
            target_level = index + 1
            matched_level = item
    if target_level <= alert.escalation_level:
        return False
    alert.escalation_level = target_level
    alert.escalated_at = now
    alert.save(update_fields=['escalation_level', 'escalated_at', 'updated_at'])
    _save_action(
        alert,
        AlertAction.ACTION_ESCALATE,
        actor='system',
        note=f'命中升级策略 {policy.name}',
        metadata={'policy_id': policy.id, 'level': matched_level or {}, 'duration_minutes': duration_minutes},
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


def handle_interaction_token(token_value, request=None):
    token = AlertInteractionToken.objects.select_related('alert').filter(token=token_value).first()
    if not token:
        return False, '交互令牌不存在', None
    if not token.is_available:
        return False, '交互令牌已过期或已使用', token.alert
    actor = f'card:{token.provider or "unknown"}'
    note = '卡片按钮操作'
    apply_alert_action(token.alert, token.action, actor=actor, note=note, metadata={'token': str(token.token)}, request=request)
    token.used_at = timezone.now()
    token.save(update_fields=['used_at'])
    return True, '告警操作已处理', token.alert


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


def matching_escalation_policy(alert):
    for policy in AlertEscalationPolicy.objects.filter(is_enabled=True):
        if match_matchers(alert, policy.matchers):
            return policy
    return None
