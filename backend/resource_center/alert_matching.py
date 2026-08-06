import ipaddress
import re
from urllib.parse import urlparse

from django.db.models import Q

from .models import Resource, ResourceContact, ResourceIdentifier, ResourceRelation, RuntimeResource


def _clean(value):
    return str(value or '').strip()


def _ip_from_value(value):
    text = _clean(value)
    if not text:
        return ''
    try:
        parsed = urlparse(text if '://' in text else f'//{text}')
        candidate = parsed.hostname or text.split(':', 1)[0]
        return str(ipaddress.ip_address(candidate.strip('[]')))
    except (ValueError, TypeError):
        match = re.search(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])', text)
        if not match:
            return ''
        try:
            return str(ipaddress.ip_address(match.group(0)))
        except ValueError:
            return ''


def _endpoint_from_value(value):
    text = _clean(value)
    if not text:
        return ''
    try:
        parsed = urlparse(text if '://' in text else f'//{text}')
        if parsed.hostname and parsed.port:
            host = parsed.hostname
            if ':' in host and not host.startswith('['):
                host = f'[{host}]'
            return f'{host}:{parsed.port}'
    except ValueError:
        return ''
    return ''


def _unique_resource(queryset):
    ids = list(queryset.values_list('resource_id', flat=True).distinct()[:2])
    if len(ids) == 1:
        return Resource.objects.filter(pk=ids[0]).first(), 'matched'
    return None, 'conflict' if len(ids) > 1 else 'unmatched'


def match_alert_to_resource(alert):
    labels = alert.labels if isinstance(alert.labels, dict) else {}
    identifier_candidates = []
    for key in ('node_uid', 'cluster_uid', 'kubernetes_uid'):
        if _clean(labels.get(key)):
            identifier_candidates.append(('k8s_uid', _clean(labels[key]), key))
    for key in ('hostid', 'zabbix_hostid'):
        if _clean(labels.get(key)):
            identifier_candidates.append(('zabbix_hostid', _clean(labels[key]), key))
    for kind, value, reason in identifier_candidates:
        resource, state = _unique_resource(ResourceIdentifier.objects.filter(kind=kind, value=value))
        if state == 'matched':
            return resource, 'matched', f'{reason}={value}'
        if state == 'conflict':
            return None, 'conflict', f'{reason}={value} 匹配多个资源'

    pod = _clean(labels.get('pod') or (alert.resource if str(alert.resource_type).lower() in {'pod', 'container'} else ''))
    namespace = _clean(labels.get('namespace') or alert.namespace)
    if pod:
        runtime = RuntimeResource.objects.filter(kind='Pod', name=pod)
        if namespace:
            runtime = runtime.filter(namespace=namespace)
        cluster_name = _clean(labels.get('cluster') or alert.cluster)
        if cluster_name:
            runtime = runtime.filter(cluster_resource__name=cluster_name)
        cluster_ids = list(runtime.values_list('cluster_resource_id', flat=True).distinct()[:2])
        if len(cluster_ids) == 1:
            return Resource.objects.get(pk=cluster_ids[0]), 'matched', f'Pod {namespace}/{pod} 运行时索引'
        if len(cluster_ids) > 1:
            return None, 'conflict', f'Pod {namespace}/{pod} 匹配多个集群'

    values = [
        labels.get(key) for key in ('ip', 'host_ip', 'node_ip', 'instance', 'host', 'hostname')
    ] + [alert.resource, getattr(alert.host, 'ip_address', '') if alert.host_id else '']
    endpoints = []
    for value in values:
        endpoint = _endpoint_from_value(value)
        if endpoint and endpoint not in endpoints:
            endpoints.append(endpoint)
    for endpoint in endpoints:
        resource, state = _unique_resource(ResourceIdentifier.objects.filter(kind='endpoint', value=endpoint))
        if state == 'matched':
            return resource, 'matched', f'端点={endpoint}'
        if state == 'conflict':
            return None, 'conflict', f'端点={endpoint} 匹配多个资源'
    ips = []
    for value in values:
        ip = _ip_from_value(value)
        if ip and ip not in ips:
            ips.append(ip)
    for ip in ips:
        direct = Resource.objects.filter(primary_ip=ip)
        ids = list(direct.values_list('id', flat=True)[:2])
        if len(ids) == 1:
            return direct.first(), 'matched', f'IP={ip}'
        if len(ids) > 1:
            return None, 'conflict', f'IP={ip} 匹配多个资源'
        resource, state = _unique_resource(ResourceIdentifier.objects.filter(kind='ip', value=ip))
        if state == 'matched':
            return resource, 'matched', f'标识 IP={ip}'
        if state == 'conflict':
            return None, 'conflict', f'标识 IP={ip} 匹配多个资源'

    cluster_name = _clean(labels.get('cluster') or alert.cluster)
    if cluster_name:
        clusters = Resource.objects.filter(resource_type__code='k8s_cluster').filter(Q(name=cluster_name) | Q(display_name=cluster_name))
        ids = list(clusters.values_list('id', flat=True)[:2])
        if len(ids) == 1:
            return clusters.first(), 'matched', f'集群名称={cluster_name}'
        if len(ids) > 1:
            return None, 'conflict', f'集群名称={cluster_name} 匹配多个资源'
    return None, 'unmatched', '告警未提供可唯一识别的 UID、IP、实例或运行时对象'


def attach_alert_resource(alert):
    resource, status, reason = match_alert_to_resource(alert)
    alert.__class__.objects.filter(pk=alert.pk).update(
        matched_resource=resource,
        resource_match_status=status,
        resource_match_reason=reason,
    )
    alert.matched_resource = resource
    alert.resource_match_status = status
    alert.resource_match_reason = reason
    return resource


def ancestor_resource_ids(resource, hops=3):
    if not resource:
        return set()
    ancestor_ids = set()
    frontier = {resource.id}
    for _ in range(max(int(hops or 3), 1)):
        parent_ids = set(ResourceRelation.objects.filter(
            target_id__in=frontier,
            relation_type='contains',
        ).values_list('source_id', flat=True))
        parent_ids.update(ResourceRelation.objects.filter(
            source_id__in=frontier,
            relation_type__in=['belongs_to', 'runs_on', 'deployed_on'],
        ).values_list('target_id', flat=True))
        parent_ids -= ancestor_ids | {resource.id}
        if not parent_ids:
            break
        ancestor_ids.update(parent_ids)
        frontier = parent_ids
    return ancestor_ids


def descendant_resource_ids(resource, hops=3):
    if not resource:
        return set()
    descendant_ids = set()
    frontier = {resource.id}
    for _ in range(max(int(hops or 3), 1)):
        child_ids = set(ResourceRelation.objects.filter(
            source_id__in=frontier,
            relation_type='contains',
        ).values_list('target_id', flat=True))
        child_ids.update(ResourceRelation.objects.filter(
            target_id__in=frontier,
            relation_type__in=['belongs_to', 'runs_on', 'deployed_on'],
        ).values_list('source_id', flat=True))
        child_ids -= descendant_ids | {resource.id}
        if not child_ids:
            break
        descendant_ids.update(child_ids)
        frontier = child_ids
    return descendant_ids


def resource_contact_recipients(resource, level='warning'):
    if not resource:
        return []
    roles = {'ops_owner', 'oncall'}
    if level == 'critical':
        roles.update({'project_owner', 'product_owner'})
    ancestor_ids = ancestor_resource_ids(resource, hops=3)
    return list(
        ResourceContact.objects.filter(
            Q(resource_id=resource.id) | Q(resource_id__in=ancestor_ids, inherit_to_children=True),
            role__in=roles,
            recipient__isnull=False,
        ).select_related('recipient').values_list('recipient', flat=True).distinct()
    )


def check_topology_suppression(alert, ancestor_hops=3):
    """拓扑抑制判定：祖先资源存在 active 且未被抑制的告警时返回抑制原因，否则返回空串。"""
    resource = alert.matched_resource
    if not resource:
        return ''
    ancestor_ids = ancestor_resource_ids(resource, hops=ancestor_hops)
    if not ancestor_ids:
        return ''
    from ops.models import Alert
    parent_alerts = Alert.objects.filter(
        matched_resource_id__in=ancestor_ids,
        status=Alert.STATUS_ACTIVE,
        is_suppressed=False,
    ).exclude(pk=alert.pk)
    for parent in parent_alerts[:20]:
        if str(parent.suppressed_by or '').startswith('topology:'):
            continue
        parent_name = parent.resource or str(parent.matched_resource_id)
        return f'父资源 {parent_name} 存在 active 告警'
    return ''


def apply_topology_suppression(alert, ancestor_hops=3):
    reason = check_topology_suppression(alert, ancestor_hops=ancestor_hops)
    if reason:
        Alert = alert.__class__
        Alert.objects.filter(pk=alert.pk).update(
            is_suppressed=True, suppressed_by='topology', suppressed_reason=reason,
        )
        alert.is_suppressed = True
        alert.suppressed_by = 'topology'
        alert.suppressed_reason = reason
        return True
    return False


def release_topology_suppression(resource, ancestor_hops=3):
    """父资源告警恢复后解除其子孙资源上的拓扑抑制标记。"""
    if not resource:
        return 0
    from ops.models import Alert
    scope_ids = {resource.id} | descendant_resource_ids(resource, hops=ancestor_hops)
    updated = Alert.objects.filter(
        matched_resource_id__in=scope_ids,
        is_suppressed=True,
        suppressed_by='topology',
    ).update(is_suppressed=False, suppressed_by='', suppressed_reason='')
    return updated
