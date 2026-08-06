"""事件中心（Event Hub）写入模块。

单一写入入口 record_event：新语义调用（source_type/kind/...）直接落库；
旧事件墙语义调用（module/category/action/...）经适配层映射后落库。
写失败仅告警日志，绝不抛出（降级原则：事件写失败不影响告警/部署主链路）。
"""
import logging

from django.conf import settings
from django.utils import timezone

from .models import Alert, Event

logger = logging.getLogger(__name__)


SOURCE_TYPE_MAP = {
    'deployment': 'deployment',
    'alert': 'alerting',
    'transaction_ticket': 'task',
    'host_task': 'task',
    'host_task_batch': 'task',
    'host_task_schedule': 'task',
    'log_datasource': 'datasource',
    'metric_datasource': 'datasource',
    'nginx_environment': 'datasource',
    'nginx_certificate': 'system',
    'nginx_domain': 'system',
    'host': 'system',
    'rbac_user': 'security',
    'rbac_permission_registry': 'security',
    'rbac_system_module_setting': 'security',
    'aiops_host_task': 'task',
    'aiops_action': 'aiops',
    'aiops_mcp_tool': 'aiops',
}

LEGACY_CONTEXT_KEYS = (
    'module', 'category', 'action', 'result', 'actor_type',
    'actor_username', 'actor_display', 'business_line', 'environment',
    'application', 'correlation_id', 'source_type',
)


def _text(value, limit=None):
    result = str(value or '').strip()
    return result[:limit] if limit else result


def _legacy_source_type(category, resource_type):
    resource_type = _text(resource_type)
    if resource_type in SOURCE_TYPE_MAP:
        return SOURCE_TYPE_MAP[resource_type]
    category = _text(category)
    if category == 'alert':
        return 'alerting'
    if category in ('security', 'system'):
        return 'security'
    if category in ('execution', 'workflow'):
        return 'task'
    return 'system'


def _resolve_alert(resource_type, resource_id):
    if _text(resource_type) != 'alert' or resource_id in (None, ''):
        return None
    try:
        return Alert.objects.filter(id=int(resource_id)).first()
    except (TypeError, ValueError):
        return None


def _record_legacy_event(kwargs):
    payload = dict(kwargs.get('metadata') or {})
    context = {}
    for key in LEGACY_CONTEXT_KEYS:
        value = kwargs.get(key)
        if value not in (None, ''):
            context[key] = value
    if context:
        payload['legacy'] = context
    request = kwargs.get('request')
    if request is not None:
        method = getattr(request, 'method', '') or ''
        path = getattr(request, 'path', '') or ''
        if method or path:
            payload['http'] = {'method': method, 'path': path}
    resource_type = _text(kwargs.get('resource_type'))
    resource_id = kwargs.get('resource_id')
    return Event.objects.create(
        source_type=_legacy_source_type(kwargs.get('category'), resource_type),
        kind=_text(kwargs.get('action') or 'system_event', 64),
        severity=_text(kwargs.get('severity') or 'info', 16),
        title=_text(kwargs.get('title'), 255),
        message=_text(kwargs.get('summary')),
        target_type=resource_type,
        target_resource=_text(kwargs.get('resource_name') or (resource_id if resource_id is not None else ''), 255),
        alert=_resolve_alert(resource_type, resource_id),
        payload=payload,
        occurred_at=kwargs.get('occurred_at') or timezone.now(),
    )


def record_event(source_type='system', kind='', severity='info', title='', message='',
                 target_type='', target_resource='', alert=None, payload=None,
                 occurred_at=None, **legacy):
    """写入一条事件。

    新语义：source_type/kind/severity/title/message/target_type/target_resource/
    alert/payload/occurred_at。
    旧语义（事件墙兼容）：module/category/action/result/summary/actor_*/resource_*
    等参数会自动识别并适配映射。
    返回 Event 或 None；任何异常仅记 warning，绝不抛出。
    """
    try:
        if legacy.get('category') is not None or legacy.get('module') is not None:
            legacy['severity'] = legacy.get('severity') or severity
            legacy['title'] = legacy.get('title') or title
            legacy['summary'] = legacy.get('summary') or message
            legacy['occurred_at'] = legacy.get('occurred_at') or occurred_at
            return _record_legacy_event(legacy)
        return Event.objects.create(
            source_type=_text(source_type, 32),
            kind=_text(kind, 64),
            severity=_text(severity, 16),
            title=_text(title, 255),
            message=_text(message),
            target_type=_text(target_type, 64),
            target_resource=_text(target_resource, 255),
            alert=alert if isinstance(alert, Alert) else None,
            payload=dict(payload or {}),
            occurred_at=occurred_at or timezone.now(),
        )
    except Exception:
        logger.warning('record_event failed (kind=%s source_type=%s)', kind, source_type, exc_info=True)
        return None


def event_retention_days():
    return max(int(getattr(settings, 'EVENT_RETENTION_DAYS', 30) or 30), 1)


def run_due_event_cleanup(limit=5000):
    """删除保留期外的事件，返回删除数量。"""
    try:
        cutoff = timezone.now() - timezone.timedelta(days=event_retention_days())
        queryset = Event.objects.filter(occurred_at__lt=cutoff)
        total = queryset.count()
        deleted = 0
        remaining = min(limit, total or 0)
        while deleted < remaining:
            batch = list(queryset.values_list('id', flat=True)[:min(500, remaining - deleted)])
            if not batch:
                break
            Event.objects.filter(id__in=batch).delete()
            deleted += len(batch)
        return deleted
    except Exception:
        logger.warning('run_due_event_cleanup failed', exc_info=True)
        return 0
