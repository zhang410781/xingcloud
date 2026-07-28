import hashlib
import logging
import secrets
from datetime import datetime, timezone as datetime_timezone

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .alerting import (
    apply_escalation_policy,
    dispatch_alert_batch_notifications,
    upsert_alert,
)
from .models import Alert, AlertAction


logger = logging.getLogger(__name__)


class AlertIngestError(ValueError):
    pass


SEVERITY_MAP = {
    'not classified': 'info',
    'information': 'info',
    'info': 'info',
    'notice': 'info',
    'warning': 'warning',
    'average': 'warning',
    'warn': 'warning',
    'high': 'critical',
    'disaster': 'critical',
    'critical': 'critical',
    'fatal': 'critical',
    'emergency': 'critical',
}


def _text(value, limit=None):
    result = str(value or '').strip()
    return result[:limit] if limit else result


def _first(*values):
    for value in values:
        text = _text(value)
        if text:
            return text
    return ''


def _dict(value):
    return value if isinstance(value, dict) else {}


def _level(value):
    return SEVERITY_MAP.get(_text(value).casefold(), 'warning')


def _timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000
        parsed = datetime.fromtimestamp(seconds, tz=datetime_timezone.utc)
    else:
        text = _text(value)
        if not text:
            return None
        parsed = parse_datetime(text)
        if parsed is None:
            for pattern in ('%Y-%m-%d %H:%M:%S', '%Y.%m.%d %H:%M:%S'):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
        if parsed is None:
            return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _stable_fingerprint(source, *parts):
    value = ':'.join(_text(part) for part in parts if _text(part))
    readable = f'{source}:{value}'
    if len(readable) <= 128:
        return readable
    digest = hashlib.sha256(value.encode('utf-8')).hexdigest()
    return f'{source}:{digest}'


def _zabbix_status(payload):
    value = _first(
        payload.get('event_status'),
        payload.get('problem_status'),
        payload.get('status'),
        payload.get('value'),
    ).casefold()
    if value in {'resolved', 'resolve', 'recovery', 'recovered', 'ok', 'closed', '0', 'false'}:
        return Alert.STATUS_RESOLVED
    return Alert.STATUS_ACTIVE


def detect_source(payload):
    if not isinstance(payload, dict):
        return 'unknown'
    if 'event_id' in payload or 'trigger_id' in payload:
        return 'zabbix'
    if 'status' in payload and isinstance(payload.get('alerts'), list):
        return 'alertmanager'
    return 'unknown'


def normalize_zabbix(payload):
    if not isinstance(payload, dict):
        raise AlertIngestError('Zabbix payload must be a JSON object.')
    trigger_id = _first(payload.get('trigger_id'), payload.get('triggerid'))
    event_id = _first(payload.get('event_id'), payload.get('eventid'))
    host_name = _first(payload.get('host_name'), payload.get('host'), payload.get('hostname'))
    title = _first(payload.get('subject'), payload.get('trigger_name'), 'Zabbix 告警')
    message = _first(payload.get('message'), payload.get('trigger_description'), title)
    status_value = _zabbix_status(payload)
    starts_at = _timestamp(_first(payload.get('starts_at'), payload.get('timestamp'), payload.get('clock')))
    ends_at = _timestamp(_first(payload.get('ends_at'), payload.get('recovery_time'), payload.get('timestamp'))) if status_value == Alert.STATUS_RESOLVED else None
    labels = {
        **_dict(payload.get('labels')),
        'zabbix_host': host_name,
        'trigger_id': trigger_id,
        'event_id': event_id,
        'severity': _text(payload.get('severity')),
    }
    raw_payload = dict(payload)
    raw_payload['ingest'] = {'source': 'zabbix', 'schema_version': 1}
    return {
        'title': _text(title, 256),
        'message': message,
        'level': _level(payload.get('severity')),
        'source': 'zabbix',
        'source_type': Alert.SOURCE_ZABBIX,
        'external_id': _text(event_id, 128),
        'fingerprint': _stable_fingerprint('zabbix', trigger_id or title, host_name),
        'resource': _text(host_name, 256),
        'resource_type': _text(payload.get('resource_type') or 'host', 64),
        'environment': _text(payload.get('environment'), 64),
        'cluster': _text(payload.get('cluster'), 128),
        'namespace': _text(payload.get('namespace'), 128),
        'service': _text(payload.get('service'), 128),
        'business_line': _text(payload.get('business_line'), 128),
        'labels': labels,
        'annotations': _dict(payload.get('annotations')),
        'raw_payload': raw_payload,
        'starts_at': starts_at,
        'ends_at': ends_at,
        'status': status_value,
    }


def _alertmanager_status(group_status, alert_payload):
    value = _first(alert_payload.get('status'), group_status).casefold()
    return Alert.STATUS_RESOLVED if value in {'resolved', 'resolve', 'recovered', 'closed'} else Alert.STATUS_ACTIVE


def normalize_alertmanager_alert(payload, alert_payload):
    if not isinstance(alert_payload, dict):
        raise AlertIngestError('Alertmanager alerts must contain JSON objects.')
    labels = _dict(alert_payload.get('labels'))
    annotations = _dict(alert_payload.get('annotations'))
    status_value = _alertmanager_status(payload.get('status'), alert_payload)
    title = _first(annotations.get('summary'), labels.get('alertname'), 'Alertmanager 告警')
    message = _first(annotations.get('description'), annotations.get('message'), title)
    resource = _first(labels.get('instance'), labels.get('pod'), labels.get('host'), labels.get('node'))
    resource_type = _first(labels.get('resource_type'), 'pod' if labels.get('pod') else 'host' if resource else '')
    external_id = _text(alert_payload.get('fingerprint'), 128)
    starts_at = _timestamp(alert_payload.get('startsAt'))
    ends_at = _timestamp(alert_payload.get('endsAt')) if status_value == Alert.STATUS_RESOLVED else None
    raw_payload = {
        'receiver': payload.get('receiver'),
        'status': payload.get('status'),
        'groupLabels': _dict(payload.get('groupLabels')),
        'commonLabels': _dict(payload.get('commonLabels')),
        'commonAnnotations': _dict(payload.get('commonAnnotations')),
        'externalURL': payload.get('externalURL'),
        'alert': alert_payload,
        'ingest': {'source': 'alertmanager', 'schema_version': 1},
    }
    return {
        'title': _text(title, 256),
        'message': message,
        'level': _level(labels.get('severity')),
        'source': 'alertmanager',
        'source_type': Alert.SOURCE_ALERTMANAGER,
        'external_id': external_id,
        'fingerprint': (
            _stable_fingerprint('alertmanager', external_id)
            if external_id
            else _stable_fingerprint('alertmanager', labels.get('alertname') or title, sorted(labels.items()))
        ),
        'resource': _text(resource, 256),
        'resource_type': _text(resource_type, 64),
        'environment': _text(labels.get('environment') or labels.get('env'), 64),
        'cluster': _text(labels.get('cluster'), 128),
        'namespace': _text(labels.get('namespace'), 128),
        'service': _text(labels.get('service') or labels.get('job'), 128),
        'business_line': _text(labels.get('business_line') or labels.get('system'), 128),
        'metric_name': _text(labels.get('__name__'), 128),
        'labels': labels,
        'annotations': annotations,
        'raw_payload': raw_payload,
        'starts_at': starts_at,
        'ends_at': ends_at,
        'status': status_value,
    }


def normalize_alertmanager(payload):
    alerts = payload.get('alerts') if isinstance(payload, dict) else None
    if not isinstance(alerts, list) or not alerts:
        raise AlertIngestError('Alertmanager payload must contain at least one alert.')
    return normalize_alertmanager_alert(payload, alerts[0])


def normalize_payload(payload):
    source = detect_source(payload)
    if source == 'zabbix':
        return source, [normalize_zabbix(payload)]
    if source == 'alertmanager':
        alerts = payload.get('alerts') or []
        if not alerts:
            raise AlertIngestError('Alertmanager payload must contain at least one alert.')
        return source, [normalize_alertmanager_alert(payload, item) for item in alerts]
    raise AlertIngestError('无法识别外部告警来源。')


def configured_webhook_tokens():
    configured = getattr(settings, 'WEBHOOK_TOKENS', {})
    if isinstance(configured, dict):
        return [_text(value) for value in configured.values() if _text(value)]
    if isinstance(configured, (list, tuple, set)):
        return [_text(value) for value in configured if _text(value)]
    return [_text(configured)] if _text(configured) else []


def authenticate_webhook_token(candidate):
    candidate = _text(candidate)
    if not candidate:
        return False
    return any(secrets.compare_digest(candidate, expected) for expected in configured_webhook_tokens())


def check_ingest_rate_limit(token, limit=None, namespace='global'):
    limit = max(int(limit or getattr(settings, 'ALERT_INGEST_RATE_LIMIT', 120) or 120), 1)
    token_digest = hashlib.sha256(_text(token).encode('utf-8')).hexdigest()
    bucket = timezone.now().strftime('%Y%m%d%H%M')
    key = f'alert-ingest-rate:{namespace}:{token_digest}:{bucket}'
    try:
        if cache.add(key, 1, timeout=70):
            return True
        return cache.incr(key) <= limit
    except Exception:
        logger.exception('external alert ingest rate-limit cache failed')
        return True


def prepare_external_alerts(payload, ingress_source):
    detected_source, normalized_alerts = normalize_payload(payload)
    if detected_source != ingress_source.provider:
        raise AlertIngestError(
            f'载荷来源为 {detected_source}，与接入源类型 {ingress_source.provider} 不一致。'
        )
    prepared = []
    for normalized in normalized_alerts:
        normalized = dict(normalized)
        original_fingerprint = normalized['fingerprint']
        normalized['fingerprint'] = _stable_fingerprint(
            'external', ingress_source.public_id, original_fingerprint,
        )
        normalized['source'] = ingress_source.code
        normalized['ingress_source'] = ingress_source
        normalized['knowledge_environment'] = None
        normalized['binding_status'] = 'not_applicable'
        raw_payload = _dict(normalized.get('raw_payload')).copy()
        ingest_metadata = _dict(raw_payload.get('ingest')).copy()
        ingest_metadata.update({
            'source_id': ingress_source.id,
            'source_code': ingress_source.code,
            'source_name': ingress_source.name,
            'provider': ingress_source.provider,
            'external_fingerprint': original_fingerprint,
            'binding_reason': 'not_required',
        })
        raw_payload['ingest'] = ingest_metadata
        normalized['raw_payload'] = raw_payload
        prepared.append(normalized)
    return detected_source, prepared


def ingest_external_alert_payload(payload, ingress_source=None):
    if ingress_source is None:
        source, normalized_alerts = normalize_payload(payload)
    else:
        source, normalized_alerts = prepare_external_alerts(payload, ingress_source)
    results = []
    fire_alerts = []
    resolved_alerts = []
    analysis_targets = []
    active_alerts = []

    for normalized in normalized_alerts:
        existing = Alert.objects.filter(
            fingerprint=normalized['fingerprint'],
        ).exclude(status=Alert.STATUS_CLOSED).order_by('-created_at').first()
        previous_status = existing.status if existing else None
        if existing:
            incoming_payload = _dict(normalized.get('raw_payload')).copy()
            existing_payload = _dict(existing.raw_payload)
            for key in ('ai_analysis', 'fire_notification_batch', 'notification_batch'):
                if key in existing_payload and key not in incoming_payload:
                    incoming_payload[key] = existing_payload[key]
            normalized['raw_payload'] = incoming_payload
        alert, created = upsert_alert(
            normalized,
            actor=f'webhook:{source}',
            action=AlertAction.ACTION_RULE_EVALUATION,
            action_note=f'{source} Webhook 告警接入',
        )
        reactivated = previous_status == Alert.STATUS_RESOLVED and alert.status == Alert.STATUS_ACTIVE
        newly_resolved = previous_status == Alert.STATUS_ACTIVE and alert.status == Alert.STATUS_RESOLVED
        if alert.status == Alert.STATUS_ACTIVE and (created or reactivated):
            fire_alerts.append(alert)
            analysis_targets.append(alert)
        elif newly_resolved:
            resolved_alerts.append(alert)
        if alert.status == Alert.STATUS_ACTIVE:
            active_alerts.append(alert)
        results.append({
            'id': alert.id,
            'created': created,
            'reactivated': reactivated,
            'fingerprint': alert.fingerprint,
            'status': alert.status,
            'occurrence_count': alert.occurrence_count,
            'analysis_id': None,
        })

    notify_enabled = ingress_source is None or ingress_source.notify_enabled
    analyze_enabled = ingress_source is None or ingress_source.analyze_enabled
    fire_dispatch = (
        dispatch_alert_batch_notifications(fire_alerts, action='fire', force=True)
        if notify_enabled else {'notification_logs': [], 'storm_batches': []}
    )
    resolved_dispatch = (
        dispatch_alert_batch_notifications(resolved_alerts, action='resolved', force=True)
        if notify_enabled else {'notification_logs': [], 'storm_batches': []}
    )
    if notify_enabled:
        for alert in active_alerts:
            apply_escalation_policy(alert)

    if analysis_targets and analyze_enabled:
        from .alert_analysis import enqueue_lightweight_analysis

        result_by_id = {item['id']: item for item in results}
        for alert in analysis_targets:
            analysis, _created = enqueue_lightweight_analysis(alert, requested_by=f'webhook:{source}')
            if analysis:
                result_by_id[alert.id]['analysis_id'] = analysis.id

    return {
        'source': source,
        'results': results,
        'notification_log_count': len(fire_dispatch.get('notification_logs') or []) + len(resolved_dispatch.get('notification_logs') or []),
        'storm_batches': (fire_dispatch.get('storm_batches') or []) + (resolved_dispatch.get('storm_batches') or []),
    }


def run_due_external_alert_escalations(limit=100):
    queryset = Alert.objects.filter(
        source_type__in=[Alert.SOURCE_ZABBIX, Alert.SOURCE_ALERTMANAGER],
        status=Alert.STATUS_ACTIVE,
        is_suppressed=False,
    ).order_by('starts_at', 'created_at', 'id')[:max(int(limit or 100), 1)]
    scanned = escalated = 0
    ids = []
    for alert in queryset:
        scanned += 1
        if apply_escalation_policy(alert):
            escalated += 1
            ids.append(alert.id)
    return {'scanned': scanned, 'escalated': escalated, 'ids': ids}
