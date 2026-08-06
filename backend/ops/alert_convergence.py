from datetime import timedelta

from django.utils import timezone

from ops.alerting import LEVEL_RANK, alert_dimension_value
from ops.models import Alert


DEFAULT_GROUP_FIELDS = ['source_type', 'environment', 'service', 'cluster', 'namespace', 'resource']


def _dimension_key(alert, group_fields):
    dims = [item for item in (group_fields or []) if str(item or '').strip()]
    if not dims:
        dims = ['alertname']
    values = [f'{key}={alert_dimension_value(alert, key) or "-"}' for key in dims]
    return ':'.join(values)


def convergence_group_key(alert, group_fields, prefix):
    return f'{prefix}:{_dimension_key(alert, group_fields)}'


def find_window_group_root(converge_key, window_minutes):
    window = max(int(window_minutes or 5), 1)
    return Alert.objects.filter(
        converge_key=converge_key,
        is_group_root=True,
        status=Alert.STATUS_ACTIVE,
        created_at__gte=timezone.now() - timedelta(minutes=window),
    ).order_by('-created_at').first()


def _refresh_root_fields(root, alert):
    updates = {}
    if LEVEL_RANK.get(alert.level, 0) > LEVEL_RANK.get(root.level, 0):
        updates['title'] = alert.title or root.title
        updates['level'] = alert.level
    updates['labels'] = alert.labels or {}
    updates['last_received_at'] = timezone.now()
    return updates


def promote_or_attach(alert, converge_key, window_minutes):
    """将告警归并到收敛聚合根。返回 'root'（作为聚合根，需通知）或 'child'（归并，不通知）。"""
    root = find_window_group_root(converge_key, window_minutes)
    now = timezone.now()
    if root is None:
        Alert.objects.filter(pk=alert.pk).update(is_group_root=True, converge_key=converge_key)
        alert.is_group_root = True
        alert.converge_key = converge_key
        return 'root'
    if alert.pk == root.pk:
        if int(alert.occurrence_count or 1) > 1:
            Alert.objects.filter(pk=alert.pk).update(occurrence_count=int(alert.occurrence_count) - 1)
            alert.occurrence_count = int(alert.occurrence_count) - 1
        return 'root'
    was_child = bool(alert.group_parent_id)
    previous_child = Alert.objects.filter(
        group_parent=root, fingerprint=alert.fingerprint,
    ).exclude(pk=alert.pk).exists()
    Alert.objects.filter(pk=alert.pk).update(
        group_parent=root, converge_key=converge_key, is_group_root=False,
    )
    alert.group_parent = root
    alert.converge_key = converge_key
    alert.is_group_root = False
    if not was_child and not previous_child:
        root.occurrence_count = int(root.occurrence_count or 1) + 1
    updates = _refresh_root_fields(root, alert)
    Alert.objects.filter(pk=root.pk).update(
        occurrence_count=root.occurrence_count,
        **updates,
    )
    for key, value in updates.items():
        setattr(root, key, value)
    return 'child'


def refresh_group_root_status(root):
    """所有子实例消失且聚合根自身实例已消失后 resolve。返回需通知的根（已 resolve）或 None。"""
    if root.status != Alert.STATUS_ACTIVE:
        return None
    has_active_child = root.group_children.exclude(
        is_group_root=True,
    ).filter(status=Alert.STATUS_ACTIVE).exists()
    if has_active_child:
        return None
    raw_payload = dict(root.raw_payload or {})
    if not raw_payload.get('instance_resolved'):
        return None
    now = timezone.now()
    raw_payload.pop('instance_resolved', None)
    Alert.objects.filter(pk=root.pk).update(
        status=Alert.STATUS_RESOLVED, ends_at=now, raw_payload=raw_payload,
    )
    root.status = Alert.STATUS_RESOLVED
    root.ends_at = now
    root.raw_payload = raw_payload
    return root


def converge_resolved_alert(alert):
    """告警恢复（规则评估 no_data/值恢复 或 webhook resolved）时的收敛处理。
    返回需要发送恢复通知的聚合根列表（普通独立告警返回空列表，由调用方按原逻辑处理）。"""
    if alert.is_group_root:
        has_active_child = alert.group_children.exclude(
            is_group_root=True,
        ).filter(status=Alert.STATUS_ACTIVE).exists()
        if has_active_child:
            raw_payload = dict(alert.raw_payload or {})
            raw_payload['instance_resolved'] = True
            Alert.objects.filter(pk=alert.pk).update(
                status=Alert.STATUS_ACTIVE, ends_at=None, raw_payload=raw_payload,
            )
            alert.status = Alert.STATUS_ACTIVE
            alert.ends_at = None
            alert.raw_payload = raw_payload
            return []
        return [alert]
    if alert.group_parent_id:
        root = refresh_group_root_status(alert.group_parent)
        return [root] if root else []
    return []
