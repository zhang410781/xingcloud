import hashlib
import json
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    DiscoveryRun,
    DiscoverySource,
    Resource,
    ResourceChange,
    ResourceIdentifier,
    ResourceRelation,
    ResourceSourceBinding,
    ResourceType,
    RuntimeResource,
)

logger = logging.getLogger(__name__)

BUILTIN_RESOURCE_TYPES = [
    ('product', '产品', 'organization', 'Briefcase'),
    ('business_system', '业务系统', 'organization', 'Grid'),
    ('application_service', '应用服务', 'organization', 'Service'),
    ('physical_server', '物理机', 'compute', 'Monitor'),
    ('virtual_machine', '虚拟机', 'compute', 'Cpu'),
    ('k8s_cluster', 'K8S 集群', 'compute', 'Connection'),
    ('k8s_node', 'K8S 节点', 'compute', 'SetUp'),
    ('mysql', 'MySQL', 'platform', 'Coin'),
    ('postgresql', 'PostgreSQL', 'platform', 'Coin'),
    ('redis', 'Redis', 'platform', 'DataBoard'),
    ('kafka', 'Kafka', 'platform', 'DataLine'),
    ('rocketmq', 'RocketMQ', 'platform', 'Promotion'),
]


def ensure_builtin_resource_types():
    result = {}
    for code, name, category, icon in BUILTIN_RESOURCE_TYPES:
        item, _ = ResourceType.objects.get_or_create(
            code=code,
            defaults={'name': name, 'category': category, 'icon': icon, 'is_builtin': True},
        )
        result[code] = item
    return result


def ensure_k8s_discovery_source(cluster, actor='system'):
    source, _ = DiscoverySource.objects.get_or_create(
        k8s_cluster=cluster,
        defaults={
            'name': f'{cluster.name} K8S 自动发现',
            'source_type': 'k8s',
            'sync_interval_minutes': 10,
            'next_run_at': timezone.now(),
            'created_by': actor,
        },
    )
    changed = False
    expected_name = f'{cluster.name} K8S 自动发现'
    if source.name != expected_name:
        source.name = expected_name
        changed = True
    if source.source_type != 'k8s':
        source.source_type = 'k8s'
        changed = True
    if changed:
        source.save(update_fields=['name', 'source_type', 'updated_at'])
    return source


def ensure_all_k8s_sources():
    from ops.models import K8sCluster

    count = 0
    for cluster in K8sCluster.objects.all().iterator():
        ensure_k8s_discovery_source(cluster)
        count += 1
    return count


def _request_timeout():
    return (5, 20)


def _owner(resource):
    refs = list(resource.metadata.owner_references or [])
    if not refs:
        return '', ''
    controller = next((item for item in refs if getattr(item, 'controller', False)), refs[0])
    return controller.kind or '', controller.name or ''


def _node_address(node, address_type):
    return next((item.address for item in (node.status.addresses or []) if item.type == address_type), '')


def collect_k8s_inventory(source, include_runtime=True):
    if not source.k8s_cluster_id:
        raise ValueError('K8S 发现源未关联集群连接')

    from ops.k8s_views import _get_k8s_client

    cluster = source.k8s_cluster
    client = _get_k8s_client(cluster)
    core = client.CoreV1Api()
    apps = client.AppsV1Api()
    system_ns = core.read_namespace('kube-system', _request_timeout=_request_timeout())
    cluster_uid = str(system_ns.metadata.uid or f'connection-{cluster.id}')
    runtime_errors = []
    try:
        cluster_version = client.VersionApi().get_code(_request_timeout=_request_timeout())
    except Exception as exc:
        cluster_version = None
        runtime_errors.append({'kind': 'ClusterVersion', 'error': str(exc)[:500]})
    nodes = core.list_node(_request_timeout=_request_timeout()).items

    inventory = {
        'cluster': {
            'external_id': cluster_uid,
            'name': cluster.name,
            'display_name': cluster.name,
            'status': 'active' if cluster.status == 'connected' else 'warning',
            'attributes': {
                'api_server': cluster.api_server,
                'kubernetes_version': getattr(cluster_version, 'git_version', '') or '',
                'connection_id': cluster.id,
                'user_type': cluster.user_type,
            },
            'identifiers': [('k8s_uid', cluster_uid, True)],
        },
        'nodes': [],
        'runtime': [],
        'runtime_errors': runtime_errors,
    }
    for node in nodes:
        conditions = {item.type: item.status for item in (node.status.conditions or [])}
        labels = node.metadata.labels or {}
        roles = [key.replace('node-role.kubernetes.io/', '') or 'worker' for key in labels if key.startswith('node-role.kubernetes.io/')]
        info = node.status.node_info
        capacity = node.status.capacity or {}
        internal_ip = _node_address(node, 'InternalIP')
        node_uid = str(node.metadata.uid)
        inventory['nodes'].append({
            'external_id': node_uid,
            'name': node.metadata.name,
            'display_name': node.metadata.name,
            'primary_ip': internal_ip or None,
            'status': 'active' if conditions.get('Ready') == 'True' else 'warning',
            'attributes': {
                'cluster_uid': cluster_uid,
                'roles': roles or ['worker'],
                'provider_id': node.spec.provider_id or '',
                'kubelet_version': info.kubelet_version if info else '',
                'kernel_version': info.kernel_version if info else '',
                'os_image': info.os_image if info else '',
                'container_runtime': info.container_runtime_version if info else '',
                'architecture': info.architecture if info else '',
                'cpu_capacity': capacity.get('cpu', ''),
                'memory_capacity': capacity.get('memory', ''),
                'pod_capacity': capacity.get('pods', ''),
                'conditions': conditions,
                'labels': labels,
                'taints': [
                    {'key': item.key, 'value': item.value or '', 'effect': item.effect}
                    for item in (node.spec.taints or [])
                ],
            },
            'identifiers': [
                ('k8s_uid', node_uid, True),
                *(([('ip', internal_ip, False)] if internal_ip else [])),
                *(([('provider_id', node.spec.provider_id, False)] if node.spec.provider_id else [])),
            ],
        })

    if not include_runtime:
        return inventory

    expires_at = timezone.now() + timedelta(minutes=max(source.sync_interval_minutes * 3, 30))

    def append_runtime(kind, item, status='', node_name='', attributes=None):
        owner_kind, owner_name = _owner(item)
        uid = str(item.metadata.uid or f'{item.metadata.namespace or "_cluster"}/{item.metadata.name}')
        inventory['runtime'].append({
            'kind': kind,
            'uid': uid,
            'namespace': item.metadata.namespace or '',
            'name': item.metadata.name,
            'status': status or '',
            'owner_kind': owner_kind,
            'owner_name': owner_name,
            'node_name': node_name or '',
            'attributes': attributes or {},
            'expires_at': expires_at,
        })

    collectors = [
        ('Namespace', lambda: core.list_namespace(_request_timeout=_request_timeout()).items,
         lambda item: append_runtime('Namespace', item, getattr(item.status, 'phase', ''))),
        ('Deployment', lambda: apps.list_deployment_for_all_namespaces(_request_timeout=_request_timeout()).items,
         lambda item: append_runtime('Deployment', item, attributes={'ready': item.status.ready_replicas or 0, 'desired': item.spec.replicas or 0})),
        ('StatefulSet', lambda: apps.list_stateful_set_for_all_namespaces(_request_timeout=_request_timeout()).items,
         lambda item: append_runtime('StatefulSet', item, attributes={'ready': item.status.ready_replicas or 0, 'desired': item.spec.replicas or 0})),
        ('DaemonSet', lambda: apps.list_daemon_set_for_all_namespaces(_request_timeout=_request_timeout()).items,
         lambda item: append_runtime('DaemonSet', item, attributes={'ready': item.status.number_ready or 0, 'desired': item.status.desired_number_scheduled or 0})),
        ('Service', lambda: core.list_service_for_all_namespaces(_request_timeout=_request_timeout()).items,
         lambda item: append_runtime('Service', item, attributes={'type': item.spec.type or '', 'cluster_ip': item.spec.cluster_ip or '', 'selector': item.spec.selector or {}})),
        ('Pod', lambda: core.list_pod_for_all_namespaces(_request_timeout=_request_timeout()).items,
         lambda item: append_runtime(
             'Pod', item, item.status.phase or '', item.spec.node_name or '',
             {'pod_ip': item.status.pod_ip or '', 'restarts': sum(state.restart_count for state in (item.status.container_statuses or []))},
         )),
    ]
    for kind, fetch, append in collectors:
        try:
            for item in fetch():
                append(item)
        except Exception as exc:
            logger.warning('K8S runtime discovery failed source=%s kind=%s: %s', source.id, kind, exc)
            inventory['runtime_errors'].append({'kind': kind, 'error': str(exc)[:500]})
    return inventory


def preview_source(source):
    if source.source_type != 'k8s':
        return {'supported': False, 'detail': f'{source.get_source_type_display()} 自动发现尚未启用'}
    inventory = collect_k8s_inventory(source, include_runtime=True)
    return {
        'supported': True,
        'cluster': inventory['cluster'],
        'nodes': inventory['nodes'],
        'runtime_counts': _runtime_counts(inventory['runtime']),
        'runtime_errors': inventory.get('runtime_errors') or [],
    }


def _runtime_counts(items):
    counts = {}
    for item in items:
        counts[item['kind']] = counts.get(item['kind'], 0) + 1
    return counts


def _content_hash(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str).encode()).hexdigest()


def _set_discovered_fields(resource, payload, run):
    changed = []
    manual = set(resource.manual_fields or [])
    for field in ('name', 'display_name', 'primary_ip', 'status'):
        if field in manual or field not in payload:
            continue
        new_value = payload.get(field)
        if getattr(resource, field) != new_value:
            changed.append((field, getattr(resource, field), new_value))
            setattr(resource, field, new_value)
    old_attributes = dict(resource.attributes or {})
    new_attributes = dict(old_attributes)
    for key, value in (payload.get('attributes') or {}).items():
        if f'attributes.{key}' not in manual:
            new_attributes[key] = value
    if old_attributes != new_attributes:
        changed.append(('attributes', old_attributes, new_attributes))
        resource.attributes = new_attributes
    resource.last_seen_at = timezone.now()
    resource.consecutive_misses = 0
    if resource.status in ('missing', 'offline') and 'status' not in manual:
        resource.status = payload.get('status', 'active')
    resource.updated_by = f'discovery:{run.source_id}'
    resource.save()
    for field, old_value, new_value in changed:
        ResourceChange.objects.create(
            resource=resource, discovery_run=run, action='update', field=field,
            old_value=old_value, new_value=new_value, actor=resource.updated_by,
        )
    return bool(changed)


def _upsert_discovered_resource(source, run, type_code, external_type, payload):
    now = timezone.now()
    binding = ResourceSourceBinding.objects.select_related('resource').filter(
        source=source, external_type=external_type, external_id=payload['external_id'],
    ).first()
    content_hash = _content_hash(payload)
    created = False
    changed = False
    if binding:
        resource = binding.resource
        if binding.content_hash != content_hash or resource.consecutive_misses:
            changed = _set_discovered_fields(resource, payload, run)
        else:
            Resource.objects.filter(pk=resource.pk).update(last_seen_at=now, consecutive_misses=0)
    else:
        resource_type = ResourceType.objects.get(code=type_code)
        resource = Resource.objects.create(
            resource_type=resource_type,
            name=payload['name'],
            display_name=payload.get('display_name', ''),
            primary_ip=payload.get('primary_ip'),
            status=payload.get('status', 'active'),
            source=source.source_type,
            attributes=payload.get('attributes') or {},
            first_seen_at=now,
            last_seen_at=now,
            created_by=f'discovery:{source.id}',
            updated_by=f'discovery:{source.id}',
        )
        binding = ResourceSourceBinding.objects.create(
            source=source, resource=resource, external_type=external_type,
            external_id=payload['external_id'], content_hash=content_hash, last_seen_at=now,
        )
        ResourceChange.objects.create(resource=resource, discovery_run=run, action='create', new_value=payload, actor=f'discovery:{source.id}')
        created = True
    binding.content_hash = content_hash
    binding.last_seen_at = now
    binding.save(update_fields=['content_hash', 'last_seen_at', 'updated_at'])
    scope = f'discovery:{source.id}'
    for kind, value, is_primary in payload.get('identifiers') or []:
        if not value:
            continue
        ResourceIdentifier.objects.update_or_create(
            kind=kind, scope=scope, value=str(value),
            defaults={'resource': resource, 'source': source.source_type, 'is_primary': is_primary},
        )
    return resource, created, changed


@transaction.atomic
def reconcile_k8s_inventory(run, inventory):
    source = run.source
    types = ensure_builtin_resource_types()
    del types
    cluster_resource, cluster_created, cluster_changed = _upsert_discovered_resource(
        source, run, 'k8s_cluster', 'cluster', inventory['cluster'],
    )
    counts = {'created': int(cluster_created), 'updated': int(cluster_changed), 'unchanged': int(not cluster_created and not cluster_changed)}
    seen_node_ids = set()
    for payload in inventory['nodes']:
        node, created, changed = _upsert_discovered_resource(source, run, 'k8s_node', 'node', payload)
        seen_node_ids.add(payload['external_id'])
        counts['created'] += int(created)
        counts['updated'] += int(changed)
        counts['unchanged'] += int(not created and not changed)
        relation, relation_created = ResourceRelation.objects.get_or_create(
            source=cluster_resource, target=node, relation_type='contains',
            defaults={'origin': source.source_type, 'last_seen_at': timezone.now(), 'first_seen_at': timezone.now()},
        )
        if not relation_created:
            relation.origin = source.source_type
            relation.last_seen_at = timezone.now()
            relation.save(update_fields=['origin', 'last_seen_at', 'updated_at'])

    missing_count = 0
    stale_bindings = source.bindings.filter(external_type='node').exclude(external_id__in=seen_node_ids).select_related('resource')
    for binding in stale_bindings:
        resource = binding.resource
        resource.consecutive_misses += 1
        if resource.consecutive_misses >= 3 and 'status' not in set(resource.manual_fields or []):
            resource.status = 'missing'
        resource.save(update_fields=['consecutive_misses', 'status', 'updated_at'])
        missing_count += 1

    now = timezone.now()
    for item in inventory['runtime']:
        RuntimeResource.objects.update_or_create(
            source=source, kind=item['kind'], uid=item['uid'],
            defaults={
                'cluster_resource': cluster_resource, 'namespace': item['namespace'], 'name': item['name'],
                'status': item['status'], 'owner_kind': item['owner_kind'], 'owner_name': item['owner_name'],
                'node_name': item['node_name'], 'attributes': item['attributes'], 'last_seen_at': now,
                'expires_at': item['expires_at'],
            },
        )
    RuntimeResource.objects.filter(source=source, expires_at__lt=now).delete()
    return cluster_resource, counts, missing_count


def execute_discovery_run(run):
    source = run.source
    now = timezone.now()
    run.status = 'connecting'
    run.started_at = now
    run.save(update_fields=['status', 'started_at'])
    try:
        if source.source_type != 'k8s':
            raise NotImplementedError(f'{source.get_source_type_display()} 发现连接器尚未启用')
        run.status = 'collecting'
        run.save(update_fields=['status'])
        inventory = collect_k8s_inventory(source, include_runtime=True)
        run.status = 'reconciling'
        run.save(update_fields=['status'])
        cluster_resource, counts, missing_count = reconcile_k8s_inventory(run, inventory)
        finished = timezone.now()
        runtime_errors = inventory.get('runtime_errors') or []
        run.status = 'partial' if runtime_errors else 'completed'
        run.discovered_count = 1 + len(inventory['nodes'])
        run.created_count = counts['created']
        run.updated_count = counts['updated']
        run.unchanged_count = counts['unchanged']
        run.missing_count = missing_count
        run.summary = {
            'cluster_resource_id': cluster_resource.id,
            'cluster': inventory['cluster']['name'],
            'nodes': len(inventory['nodes']),
            'runtime_counts': _runtime_counts(inventory['runtime']),
            'runtime_errors': runtime_errors,
        }
        run.finished_at = finished
        run.save()
        source.status = 'degraded' if runtime_errors else 'healthy'
        source.last_run_at = finished
        source.last_success_at = finished
        source.last_error = '; '.join(f"{item['kind']}: {item['error']}" for item in runtime_errors)[:4000]
        source.next_run_at = finished + timedelta(minutes=source.sync_interval_minutes)
        source.save()
    except Exception as exc:
        logger.exception('Resource discovery failed for source=%s', source.id)
        finished = timezone.now()
        run.status = 'failed'
        run.error = str(exc)[:4000]
        run.finished_at = finished
        run.save(update_fields=['status', 'error', 'finished_at'])
        source.status = 'failed'
        source.last_run_at = finished
        source.last_error = str(exc)[:4000]
        source.next_run_at = finished + timedelta(minutes=max(source.sync_interval_minutes, 10))
        source.save()
    return run


def run_due_discoveries(limit=10):
    ensure_all_k8s_sources()
    now = timezone.now()
    for source in DiscoverySource.objects.filter(is_enabled=True, next_run_at__lte=now).order_by('next_run_at')[:limit]:
        if not source.runs.filter(status__in=['pending', 'connecting', 'collecting', 'reconciling']).exists():
            DiscoveryRun.objects.create(source=source, trigger='schedule')
        source.next_run_at = now + timedelta(minutes=source.sync_interval_minutes)
        source.save(update_fields=['next_run_at', 'updated_at'])

    processed = 0
    failed = 0
    pending_ids = list(DiscoveryRun.objects.filter(status='pending').order_by('created_at').values_list('id', flat=True)[:limit])
    for run_id in pending_ids:
        run = DiscoveryRun.objects.select_related('source', 'source__k8s_cluster').get(pk=run_id)
        execute_discovery_run(run)
        processed += 1
        failed += int(run.status == 'failed')
    return {'processed': processed, 'failed': failed}
