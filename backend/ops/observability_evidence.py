from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
import math
import re

from django.utils import timezone

from aiops.business_context import context_payload, resolve_business_context

from .anomaly_detection import detect_anomaly
from .log_views import _merge_config, _run_query


METRIC_MATRIX = [
    ('node_count', '节点数量', 'count(kube_node_info)'),
    ('node_cpu', '节点 CPU 使用率', '100 - avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100'),
    ('node_memory', '节点内存使用率', '(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100'),
    ('node_load', '节点一分钟负载', 'node_load1'),
    ('disk_usage', '磁盘使用率', '(1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"}) * 100'),
    ('inode_usage', 'inode 使用率', '(1 - node_filesystem_files_free{fstype!~"tmpfs|overlay"} / node_filesystem_files{fstype!~"tmpfs|overlay"}) * 100'),
    ('network_receive', '网络接收速率', 'sum by(instance) (rate(node_network_receive_bytes_total{device!~"lo|veth.*"}[5m]))'),
    ('network_transmit', '网络发送速率', 'sum by(instance) (rate(node_network_transmit_bytes_total{device!~"lo|veth.*"}[5m]))'),
    ('network_errors', '网络错误', 'sum by(instance) (rate(node_network_receive_errs_total[5m]) + rate(node_network_transmit_errs_total[5m]))'),
    ('network_drops', '网络丢包', 'sum by(instance) (rate(node_network_receive_drop_total[5m]) + rate(node_network_transmit_drop_total[5m]))'),
    ('tcp_connections', 'TCP 连接', 'node_netstat_Tcp_CurrEstab'),
    ('disk_io', '磁盘 I/O', 'sum by(instance) (rate(node_disk_read_bytes_total[5m]) + rate(node_disk_written_bytes_total[5m]))'),
    ('pod_restarts', 'Pod 重启', 'sum by(namespace,pod) (increase(kube_pod_container_status_restarts_total[15m]))'),
    ('pvc_usage', 'PVC 使用率', 'kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes * 100'),
    ('apiserver_rate', 'API Server 请求速率', 'sum(rate(apiserver_request_total[5m]))'),
    ('apiserver_errors', 'API Server 错误率', 'sum(rate(apiserver_request_total{code=~"5.."}[5m]))'),
    ('apiserver_latency', 'API Server P99 延迟', 'histogram_quantile(0.99, sum by(le) (rate(apiserver_request_duration_seconds_bucket[5m])))'),
    ('requests_cpu', 'CPU Requests', 'sum(kube_pod_container_resource_requests{resource="cpu"})'),
    ('limits_memory', '内存 Limits', 'sum(kube_pod_container_resource_limits{resource="memory"})'),
]

DEPTH_METRIC_LIMIT = {'light': 4, 'targeted': 12, 'full': len(METRIC_MATRIX)}
INSPECTION_PROFILE_ALIASES = {'inspection': 'cluster', 'k8s': 'cluster'}
INSPECTION_PROFILE_METRICS = {
    'cluster': {item[0] for item in METRIC_MATRIX},
    'server': {
        'node_count', 'node_cpu', 'node_memory', 'node_load', 'disk_usage', 'inode_usage',
        'network_receive', 'network_transmit', 'network_errors', 'network_drops',
        'tcp_connections', 'disk_io',
    },
    'node': {
        'node_count', 'node_cpu', 'node_memory', 'node_load', 'disk_usage', 'inode_usage',
        'network_receive', 'network_transmit', 'network_errors', 'network_drops',
        'tcp_connections', 'disk_io',
    },
    'workload': {'pod_restarts', 'requests_cpu', 'limits_memory', 'node_cpu', 'node_memory'},
    'service': {'pod_restarts', 'network_receive', 'network_transmit', 'requests_cpu', 'limits_memory'},
    'control_plane': {
        'apiserver_rate', 'apiserver_errors', 'apiserver_latency',
        'node_count', 'node_cpu', 'node_memory', 'network_errors', 'network_drops', 'disk_io',
    },
}
INSPECTION_PROFILE_RESOURCES = {
    'cluster': ['deployments', 'statefulsets', 'daemonsets', 'pvcs'],
    'server': [],
    'node': [],
    'workload': ['deployments', 'statefulsets', 'daemonsets', 'pvcs'],
    'service': ['services', 'ingresses', 'deployments'],
    'control_plane': ['deployments', 'daemonsets'],
}
CONTROL_PLANE_POD_KEYWORDS = (
    'kube-apiserver', 'apiserver', 'etcd', 'coredns',
    'kube-scheduler', 'kube-controller-manager',
)
SECRET_PATTERN = re.compile(
    r'(?i)\b(password|passwd|pwd|token|api[_-]?key|authorization|cookie|secret)\b(\s*[:=]\s*)([^\s,;]+)'
)
BEARER_PATTERN = re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*')
PHONE_PATTERN = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')


def _series_values(result):
    values = []
    for series in result.get('result') or []:
        samples = series.get('values') or []
        if not samples and series.get('value'):
            samples = [series.get('value')]
        for sample in samples:
            raw = sample[1] if isinstance(sample, (list, tuple)) and len(sample) > 1 else sample
            try:
                number = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                values.append(number)
    return values


def _query_metric(context, definition, start_time, end_time, step):
    from .observability_views import execute_promql_query

    code, title, promql = definition
    result = execute_promql_query(
        promql,
        range_query=True,
        start_time=start_time,
        end_time=end_time,
        step=step,
        metric_datasource_id=context.metric_datasource_id,
        environment=context.code,
        prefer_metric_datasource=True,
    )
    values = _series_values(result)
    anomaly = detect_anomaly(values)
    return {
        'code': code,
        'title': title,
        'query': promql,
        'status': 'ok',
        'series_count': result.get('series_count', 0),
        'sample_count': len(values),
        'latest': values[-1] if values else None,
        'anomaly': anomaly,
    }


def _namespaces(context):
    raw = context.k8s_namespaces if isinstance(context.k8s_namespaces, dict) else {}
    values = raw.get('namespaces')
    if values is None and context.k8s_cluster_id:
        values = raw.get(str(context.k8s_cluster_id))
    return values or None


def _k8s_evidence(context, depth, target='', profile='cluster'):
    from .k8s_views import get_k8s_nodes_snapshot, get_k8s_pods_snapshot, get_k8s_resource_snapshot

    cluster = context.k8s_cluster
    namespaces = _namespaces(context)
    if profile in {'node', 'control_plane'}:
        namespaces = None
    nodes = get_k8s_nodes_snapshot(cluster)
    pods = get_k8s_pods_snapshot(cluster, namespaces)
    if profile == 'control_plane':
        pods = [
            item for item in pods
            if str(item.get('namespace') or '') == 'kube-system'
            and any(keyword in str(item.get('name') or '').lower() for keyword in CONTROL_PLANE_POD_KEYWORDS)
        ]
    elif profile == 'node' and not target:
        pods = []
    elif profile == 'service' and not target:
        pods = []
    if target:
        lowered = target.lower()
        if profile == 'node':
            nodes = [item for item in nodes if lowered in str(item.get('name') or '').lower()]
            pods_on_node = [item for item in pods if lowered in str(item.get('node') or item.get('node_name') or '').lower()]
            if pods_on_node:
                pods = pods_on_node
        elif profile in {'workload', 'service'}:
            pods = [item for item in pods if lowered in str(item.get('name') or '').lower()]
    resources = {}
    if depth in {'targeted', 'full'}:
        kinds = list(INSPECTION_PROFILE_RESOURCES.get(profile, INSPECTION_PROFILE_RESOURCES['cluster']))
        if depth == 'targeted':
            kinds = kinds[:2]
        for kind in kinds:
            items = get_k8s_resource_snapshot(cluster, kind, namespaces)
            if target and profile in {'workload', 'service'}:
                matched = [item for item in items if target.lower() in str(item.get('name') or '').lower()]
                items = matched or items
            resources[kind] = items

    findings = []
    for node in nodes:
        if node.get('status') != 'Ready':
            findings.append({'fingerprint': f"node-not-ready:{node.get('name')}", 'severity': 'critical', 'code': 'node_not_ready', 'target': node.get('name'), 'message': '节点状态不是 Ready'})
    for pod in pods:
        pod_status = str(pod.get('status') or 'Unknown')
        containers = list(pod.get('containers') or [])
        not_ready = pod_status == 'Running' and any(not item.get('ready') for item in containers)
        if pod_status not in {'Running', 'Succeeded', 'Failed'}:
            findings.append({'fingerprint': f"pod-phase:{pod.get('namespace')}:{pod.get('name')}", 'severity': 'warning', 'code': 'pod_abnormal', 'target': pod.get('name'), 'namespace': pod.get('namespace'), 'message': f"Pod 状态为 {pod_status}"})
        elif not_ready:
            restart_suffix = f"，累计重启 {pod.get('restarts')} 次" if int(pod.get('restarts') or 0) else ''
            findings.append({'fingerprint': f"pod-not-ready:{pod.get('namespace')}:{pod.get('name')}", 'severity': 'warning', 'code': 'pod_not_ready', 'target': pod.get('name'), 'namespace': pod.get('namespace'), 'message': f"Pod 容器未就绪{restart_suffix}"})
    for pvc in resources.get('pvcs') or []:
        if pvc.get('status') != 'Bound':
            findings.append({'fingerprint': f"pvc:{pvc.get('namespace')}:{pvc.get('name')}", 'severity': 'warning', 'code': 'pvc_unbound', 'target': pvc.get('name'), 'namespace': pvc.get('namespace'), 'message': f"PVC 状态为 {pvc.get('status')}"})
    return {
        'status': 'ok',
        'profile': profile,
        'cluster': {'id': cluster.id, 'name': cluster.name, 'status': cluster.status},
        'summary': {
            'node_count': len(nodes),
            'ready_nodes': sum(1 for item in nodes if item.get('status') == 'Ready'),
            'pod_count': len(pods),
            'pod_status': dict(Counter(str(item.get('status') or 'Unknown') for item in pods)),
        },
        'nodes': nodes,
        'pods': pods,
        'resources': resources,
        'findings': findings,
    }


def _deep_k8s_samples(context, findings, limit=5):
    from .k8s_views import _get_k8s_client

    cluster = context.k8s_cluster
    k8s = _get_k8s_client(cluster)
    v1 = k8s.CoreV1Api()
    samples = []
    seen = set()
    for finding in findings:
        namespace, pod_name = finding.get('namespace'), finding.get('target')
        key = (namespace, pod_name)
        if not namespace or not pod_name or key in seen:
            continue
        seen.add(key)
        item = {'namespace': namespace, 'pod': pod_name, 'events': [], 'current_logs': '', 'previous_logs': ''}
        try:
            events = v1.list_namespaced_event(namespace, field_selector=f'involvedObject.name={pod_name}', limit=20)
            item['events'] = [
                {'type': event.type, 'reason': event.reason, 'message': event.message, 'count': event.count}
                for event in events.items if event.type == 'Warning'
            ]
        except Exception as exc:
            item['events_error'] = str(exc)[:200]
        try:
            item['current_logs'] = str(v1.read_namespaced_pod_log(pod_name, namespace, tail_lines=50))[-8000:]
        except Exception as exc:
            item['current_logs_error'] = str(exc)[:200]
        if finding.get('code') == 'pod_restarts':
            try:
                item['previous_logs'] = str(v1.read_namespaced_pod_log(pod_name, namespace, tail_lines=50, previous=True))[-8000:]
            except Exception as exc:
                item['previous_logs_error'] = str(exc)[:200]
        samples.append(item)
        if len(samples) >= limit:
            break
    return samples


def _log_dimensions(alert=None, target=''):
    labels = alert.labels if alert and isinstance(alert.labels, dict) else {}
    resource_type = str(getattr(alert, 'resource_type', '') or '').lower()
    resource = str(getattr(alert, 'resource', '') or '').strip()
    values = {
        'pod': str(labels.get('pod') or labels.get('pod_name') or (resource if resource_type in {'pod', 'k8s', 'prometheus'} else '')).strip(),
        'namespace': str(getattr(alert, 'namespace', '') or labels.get('namespace') or labels.get('namespace_name') or '').strip(),
        'service': str(getattr(alert, 'service', '') or labels.get('service') or labels.get('app') or labels.get('job') or '').strip(),
        'node': str(labels.get('node') or labels.get('node_name') or (resource if resource_type == 'node' else '')).strip(),
        'host': str(labels.get('host') or labels.get('instance') or '').strip(),
        'cluster': str(getattr(alert, 'cluster', '') or labels.get('cluster') or '').strip(),
    }
    if alert and not values.get('service'):
        alert_text = ' '.join([
            str(getattr(alert, 'title', '') or ''),
            str(getattr(alert, 'metric_name', '') or ''),
            str(labels.get('alertname') or ''),
            str(labels.get('component') or ''),
        ]).lower()
        control_plane_services = [
            (('apiserver', 'api server'), 'kube-apiserver'),
            (('etcd',), 'etcd'),
            (('coredns', 'core dns'), 'coredns'),
            (('scheduler',), 'kube-scheduler'),
            (('controller manager', 'controller-manager'), 'kube-controller-manager'),
        ]
        for keywords, service_name in control_plane_services:
            if any(keyword in alert_text for keyword in keywords):
                values['service'] = service_name
                break
    if target and not any(values.values()):
        values['target'] = str(target).strip()
    return {key: value for key, value in values.items() if value}


def _log_query_terms(dimensions):
    ordered = ['pod', 'namespace', 'service', 'node', 'host', 'cluster', 'target']
    terms = []
    for key in ordered:
        value = dimensions.get(key)
        if value and value not in terms:
            terms.append(value)
        if len(terms) >= 3:
            break
    return ' '.join(f'"{item}"' for item in terms) or '*'


def _redact_log_text(value):
    text = str(value or '')
    text = SECRET_PATTERN.sub(lambda match: f'{match.group(1)}{match.group(2)}***', text)
    text = BEARER_PATTERN.sub('Bearer ***', text)
    return PHONE_PATTERN.sub('1**********', text)


def _sanitize_log(log):
    return {
        'timestamp': str(log.get('timestamp') or ''),
        'level': str(log.get('level') or 'unknown').lower(),
        'source': str(log.get('source') or ''),
        'service': str(log.get('service') or ''),
        'namespace': str(log.get('namespace') or ''),
        'pod': str(log.get('pod') or ''),
        'container': str(log.get('container') or ''),
        'host': str(log.get('host') or ''),
        'message': _redact_log_text(log.get('message'))[:1200],
    }


def _dedupe_logs(logs, limit=20):
    result = []
    seen = set()
    for raw in logs or []:
        item = _sanitize_log(raw)
        fingerprint = re.sub(r'\b\d+\b', '#', item['message'].casefold())[:500]
        key = (item['level'], item['source'], fingerprint)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _log_evidence(context, *, alert=None, target='', window_minutes=60, profile='cluster'):
    datasource = context.log_datasource
    dimensions = _log_dimensions(alert=alert, target=target)
    queries = [_log_query_terms(dimensions)]
    if profile == 'control_plane' and not dimensions:
        queries = [f'"{service}"' for service in CONTROL_PLANE_POD_KEYWORDS if service != 'apiserver']

    def run_window(start_at, end_at, *, limit=50):
        payload = {
            'query': ' OR '.join(queries),
            'start_ms': int(start_at.timestamp() * 1000),
            'end_ms': int(end_at.timestamp() * 1000),
            'limit': limit,
        }
        if datasource.provider == 'clickhouse':
            config = datasource.config if isinstance(datasource.config, dict) else {}
            payload['collection'] = config.get('default_collection') or 'container-logs'
        config = _merge_config(datasource.provider, datasource.config)
        combined = {'total': 0, 'logs': []}
        for query in queries:
            query_payload = {**payload, 'query': query}
            result = _run_query(datasource.provider, config, query_payload)
            combined['total'] += int(result.get('total') or 0)
            combined['logs'].extend(result.get('logs') or [])
        return payload, combined

    now = timezone.now()
    alert_started_at = getattr(alert, 'starts_at', None) if alert else None
    if alert_started_at:
        primary_start = alert_started_at - timedelta(minutes=5)
        expected_end = alert_started_at + timedelta(minutes=2)
        primary_end = min(now, expected_end) if now >= alert_started_at else expected_end
        baseline_start = alert_started_at - timedelta(minutes=30)
        baseline_end = primary_start
        fallback_minutes = [15, 60]
    else:
        primary_end = now
        primary_minutes = max(5, min(int(window_minutes or 60), 360))
        primary_start = primary_end - timedelta(minutes=primary_minutes)
        baseline_start = None
        baseline_end = None
        fallback_minutes = [60] if primary_minutes != 60 else []

    attempts = []
    result = None
    payload, result = run_window(primary_start, primary_end)
    attempts.append({
        'kind': 'primary',
        'start_at': primary_start.isoformat(),
        'end_at': primary_end.isoformat(),
        'query': payload['query'],
    })
    if not result.get('logs'):
        for minutes in fallback_minutes:
            fallback_start = primary_end - timedelta(minutes=minutes)
            payload, result = run_window(fallback_start, primary_end)
            attempts.append({
                'kind': 'fallback',
                'window_minutes': minutes,
                'start_at': fallback_start.isoformat(),
                'end_at': primary_end.isoformat(),
                'query': payload['query'],
            })
            if result.get('logs') or minutes == 60:
                break

    logs = _dedupe_logs((result or {}).get('logs') or [])
    levels = Counter(item.get('level') or 'unknown' for item in logs)
    error_count = sum(count for level, count in levels.items() if level in {'warning', 'warn', 'error', 'critical', 'fatal'})
    baseline = None
    if baseline_start and baseline_end:
        baseline_payload, baseline_result = run_window(baseline_start, baseline_end)
        baseline_logs = _dedupe_logs((baseline_result or {}).get('logs') or [])
        baseline_levels = Counter(item.get('level') or 'unknown' for item in baseline_logs)
        baseline_error_count = sum(
            count for level, count in baseline_levels.items()
            if level in {'warning', 'warn', 'error', 'critical', 'fatal'}
        )
        baseline_total = int((baseline_result or {}).get('total') or len(baseline_logs) or 0)
        baseline = {
            'start_at': baseline_start.isoformat(),
            'end_at': baseline_end.isoformat(),
            'query': baseline_payload['query'],
            'total': baseline_total,
            'sample_count': len(baseline_logs),
            'error_count': baseline_error_count,
            'error_rate': (baseline_error_count / max(len(baseline_logs), 1)) if baseline_logs else 0,
            'level_distribution': dict(baseline_levels),
        }
    return {
        'status': 'ok',
        'profile': profile,
        'datasource': {'id': datasource.id, 'name': datasource.name, 'provider': datasource.provider},
        'dimensions': dimensions,
        'field_map': (datasource.config if isinstance(datasource.config, dict) else {}).get('field_map') or {},
        'attempts': attempts,
        'window': {'start_at': primary_start.isoformat(), 'end_at': primary_end.isoformat()},
        'total': (result or {}).get('total', len(logs)),
        'sample_count': len(logs),
        'error_count': error_count,
        'error_rate': (error_count / max(len(logs), 1)) if logs else 0,
        'level_distribution': dict(levels),
        'samples': logs,
        'baseline': baseline,
    }


def _log_findings(logs):
    findings = []
    for item in logs or []:
        level = str(item.get('level') or '').lower()
        if level not in {'warning', 'warn', 'error', 'critical', 'fatal'}:
            continue
        message = str(item.get('message') or '')
        normalized = re.sub(r'\b\d+\b', '#', message.casefold())[:300]
        findings.append({
            'fingerprint': f"log:{item.get('source')}:{normalized}",
            'severity': 'critical' if level in {'critical', 'fatal'} else 'warning',
            'code': 'log_error',
            'target': item.get('pod') or item.get('service') or item.get('source'),
            'message': message[:300],
            'timestamp': item.get('timestamp'),
        })
    return findings[:20]


def _asset_and_topology_evidence(context):
    from .models import MiddlewareAsset, TaskResource

    environment = context.task_resource_environment
    if not environment:
        return [], [], []
    resources = list(
        TaskResource.objects
        .filter(business_groups=environment)
        .distinct()
        .values('id', 'name', 'resource_type', 'status', 'ip_address', 'cluster_id', 'owner')[:100]
    )
    middleware = list(
        MiddlewareAsset.objects
        .filter(business_groups=environment)
        .distinct()
        .values('id', 'name', 'asset_type', 'status', 'endpoint', 'version')[:100]
    )
    topology = [
        {
            'relation': 'business_context_binding',
            'source': context.code,
            'target_type': target_type,
            'target_id': target_id,
            'target_name': target_name,
        }
        for target_type, target_id, target_name in [
            ('metric_datasource', context.metric_datasource_id, getattr(context.metric_datasource, 'name', '')),
            ('log_datasource', context.log_datasource_id, getattr(context.log_datasource, 'name', '')),
            ('k8s_cluster', context.k8s_cluster_id, getattr(context.k8s_cluster, 'name', '')),
            ('asset_environment', context.task_resource_environment_id, environment.name),
        ]
        if target_id
    ]
    return resources, middleware, topology


def _change_evidence(context, *, window_minutes=60, target=''):
    from .models import Deployment

    if not context.k8s_cluster_id:
        return []
    start_time = timezone.now() - timedelta(minutes=max(60, min(int(window_minutes or 60) * 2, 1440)))
    queryset = Deployment.objects.filter(
        cluster_id=context.k8s_cluster_id,
        deployed_at__gte=start_time,
    ).order_by('-deployed_at')
    if target:
        from django.db.models import Q
        queryset = queryset.filter(Q(app_name__icontains=target) | Q(namespace__icontains=target))
    return [
        {
            'id': item.id,
            'app_name': item.app_name,
            'version': item.version,
            'namespace': item.namespace,
            'status': item.status,
            'action_type': item.action_type,
            'change_summary': item.change_summary,
            'deployed_at': item.deployed_at.isoformat() if item.deployed_at else None,
            'severity': 'warning' if item.status == 'failed' else 'info',
        }
        for item in queryset[:20]
    ]


def collect_observability_evidence(context, profile='inspection', depth='full', *, alert=None, target='', window_minutes=60):
    context = resolve_business_context(context)
    if not context:
        raise ValueError('业务上下文不存在或已停用')
    depth = depth if depth in DEPTH_METRIC_LIMIT else 'targeted'
    profile = INSPECTION_PROFILE_ALIASES.get(str(profile or '').strip(), str(profile or '').strip()) or 'cluster'
    profile_for_collection = profile if profile in INSPECTION_PROFILE_METRICS else 'cluster'
    if alert and profile not in INSPECTION_PROFILE_METRICS:
        alert_text = ' '.join([
            str(getattr(alert, 'title', '') or ''),
            str(getattr(alert, 'metric_name', '') or ''),
            str(getattr(alert, 'resource_type', '') or ''),
        ]).lower()
        if any(keyword in alert_text for keyword in ['apiserver', 'api server', 'etcd', 'coredns', 'scheduler', 'controller manager']):
            profile_for_collection = 'control_plane'
        elif str(getattr(alert, 'resource_type', '') or '').lower() == 'node':
            profile_for_collection = 'node'
        elif getattr(alert, 'service', '') and not getattr(alert, 'resource', ''):
            profile_for_collection = 'service'
        elif getattr(alert, 'resource', '') or any(keyword in alert_text for keyword in ['pod', 'container', 'workload', 'deployment']):
            profile_for_collection = 'workload'
    evidence = {
        'profile': profile,
        'collection_profile': profile_for_collection,
        'depth': depth,
        'context': context_payload(context),
        'stage_status': {},
        'source_coverage': {},
        'metric_anomalies': [],
        'metrics': [],
        'k8s_findings': [],
        'event_findings': [],
        'log_findings': [],
        'change_findings': [],
        'topology_findings': [],
        'diagnostics': [],
    }
    if alert:
        evidence['alert'] = {'id': alert.id, 'title': alert.title, 'level': alert.level, 'resource': alert.resource, 'namespace': alert.namespace, 'service': alert.service}

    if context.metric_datasource_id and context.metric_datasource.is_enabled:
        start_time = timezone.now() - timedelta(minutes=max(15, min(int(window_minutes or 60), 360)))
        end_time = timezone.now()
        allowed_metric_codes = INSPECTION_PROFILE_METRICS.get(profile_for_collection) or INSPECTION_PROFILE_METRICS['cluster']
        definitions = [item for item in METRIC_MATRIX if item[0] in allowed_metric_codes][:DEPTH_METRIC_LIMIT[depth]]
        with ThreadPoolExecutor(max_workers=min(6, len(definitions))) as executor:
            futures = {executor.submit(_query_metric, context, item, start_time, end_time, 60): item for item in definitions}
            for future in as_completed(futures):
                definition = futures[future]
                try:
                    metric = future.result()
                    evidence['metrics'].append(metric)
                    if metric['anomaly'].get('is_anomaly'):
                        evidence['metric_anomalies'].append(metric)
                except Exception as exc:
                    evidence['metrics'].append({'code': definition[0], 'title': definition[1], 'query': definition[2], 'status': 'error', 'error': str(exc)[:300]})
        successful = sum(1 for item in evidence['metrics'] if item.get('status') == 'ok')
        evidence['stage_status']['metrics'] = 'completed' if successful == len(definitions) else ('partial' if successful else 'failed')
        evidence['source_coverage']['metrics'] = successful > 0
    else:
        evidence['stage_status']['metrics'] = 'unavailable'
        evidence['source_coverage']['metrics'] = False
        evidence['diagnostics'].append({'code': 'metric_datasource_unavailable', 'message': '业务上下文未绑定可用的 Prometheus'})

    if profile_for_collection == 'server':
        evidence['stage_status']['k8s'] = 'skipped'
        evidence['source_coverage']['k8s'] = False
        evidence['k8s'] = {'status': 'skipped', 'profile': 'server', 'summary': {}}
    elif context.k8s_cluster_id:
        try:
            k8s = _k8s_evidence(context, depth, target=target, profile=profile_for_collection)
            evidence['k8s'] = k8s
            evidence['k8s_findings'] = k8s['findings']
            if depth in {'targeted', 'full'} and k8s['findings']:
                evidence['k8s_samples'] = _deep_k8s_samples(context, k8s['findings'])
                evidence['event_findings'] = [event for item in evidence['k8s_samples'] for event in item.get('events') or []]
            evidence['stage_status']['k8s'] = 'completed'
            evidence['source_coverage']['k8s'] = True
        except Exception as exc:
            evidence['stage_status']['k8s'] = 'failed'
            evidence['source_coverage']['k8s'] = False
            evidence['diagnostics'].append({'code': 'k8s_query_failed', 'message': str(exc)[:300]})
    else:
        evidence['stage_status']['k8s'] = 'unavailable'
        evidence['source_coverage']['k8s'] = False
        evidence['diagnostics'].append({'code': 'k8s_cluster_unavailable', 'message': '业务上下文未绑定 K8s 集群'})

    if context.log_datasource_id and context.log_datasource.is_enabled:
        try:
            logs = _log_evidence(
                context,
                alert=alert,
                target=target,
                window_minutes=window_minutes,
                profile=profile,
            )
            evidence['logs'] = logs
            evidence['log_findings'] = _log_findings(logs.get('samples') or [])
            evidence['stage_status']['logs'] = 'completed'
            evidence['source_coverage']['logs'] = True
        except Exception as exc:
            evidence['logs'] = {'status': 'query_error', 'error': str(exc)[:300], 'samples': []}
            evidence['stage_status']['logs'] = 'failed'
            evidence['source_coverage']['logs'] = False
            evidence['diagnostics'].append({'code': 'log_query_failed', 'message': str(exc)[:300]})
    else:
        message = '业务上下文未绑定可用的日志源'
        evidence['logs'] = {'status': 'configuration_error', 'error': message, 'samples': []}
        evidence['stage_status']['logs'] = 'unavailable'
        evidence['source_coverage']['logs'] = False
        evidence['diagnostics'].append({'code': 'log_datasource_unavailable', 'message': message})

    if context.task_resource_environment_id:
        try:
            resources, middleware, topology = _asset_and_topology_evidence(context)
            evidence['assets'] = {'resources': resources, 'middleware': middleware}
            evidence['topology_findings'] = topology
            evidence['stage_status']['assets'] = 'completed'
            evidence['stage_status']['topology'] = 'completed'
            evidence['source_coverage']['assets'] = True
            evidence['source_coverage']['topology'] = bool(topology)
        except Exception as exc:
            evidence['stage_status']['assets'] = 'failed'
            evidence['stage_status']['topology'] = 'failed'
            evidence['source_coverage']['assets'] = False
            evidence['source_coverage']['topology'] = False
            evidence['diagnostics'].append({'code': 'asset_query_failed', 'message': str(exc)[:300]})
    else:
        evidence['stage_status']['assets'] = 'unavailable'
        evidence['stage_status']['topology'] = 'unavailable'
        evidence['source_coverage']['assets'] = False
        evidence['source_coverage']['topology'] = False

    try:
        evidence['change_findings'] = _change_evidence(
            context,
            window_minutes=window_minutes,
            target=target,
        )
        evidence['stage_status']['changes'] = 'completed'
        evidence['source_coverage']['changes'] = True
    except Exception as exc:
        evidence['stage_status']['changes'] = 'failed'
        evidence['source_coverage']['changes'] = False
        evidence['diagnostics'].append({'code': 'change_query_failed', 'message': str(exc)[:300]})
    return evidence


def inspection_result(evidence):
    findings = list(evidence.get('k8s_findings') or [])
    findings.extend(evidence.get('log_findings') or [])
    for metric in evidence.get('metric_anomalies') or []:
        findings.append({'fingerprint': f"metric:{metric.get('code')}", 'severity': 'warning', 'code': 'metric_anomaly', 'target': metric.get('title'), 'message': f"{metric.get('title')}偏离历史基线"})
    unique = {}
    for item in findings:
        unique.setdefault(item.get('fingerprint') or str(item), item)
    findings = list(unique.values())
    deductions = {'critical': 20, 'warning': 8, 'info': 2}
    deduction_groups = {}
    for item in findings:
        group_key = (
            item.get('code') or 'unknown',
            item.get('namespace') or '',
            item.get('target') or item.get('fingerprint') or '',
        )
        existing = deduction_groups.get(group_key)
        if not existing or deductions.get(item.get('severity'), 2) > deductions.get(existing.get('severity'), 2):
            deduction_groups[group_key] = item
    score_deductions = [
        {
            'code': item.get('code'),
            'target': item.get('target'),
            'namespace': item.get('namespace'),
            'severity': item.get('severity'),
            'points': deductions.get(item.get('severity'), 2),
        }
        for item in deduction_groups.values()
    ]
    score = max(0, 100 - sum(item['points'] for item in score_deductions))
    profile = evidence.get('collection_profile') or evidence.get('profile') or 'cluster'
    summary = (evidence.get('k8s') or {}).get('summary') or {}
    metric_summary = {
        item.get('code'): item.get('latest')
        for item in evidence.get('metrics') or []
        if item.get('status') == 'ok' and item.get('latest') is not None
    }
    missing = [item.get('message') for item in evidence.get('diagnostics') or []]
    core_coverage = evidence.get('source_coverage') or {}
    required_sources = ('metrics',) if profile == 'server' else ('metrics', 'k8s')
    missing_required_sources = [name for name in required_sources if not core_coverage.get(name)]
    evidence_incomplete = bool(missing_required_sources)
    if profile == 'server':
        conclusion = '服务器运行正常' if score >= 90 else ('服务器存在需要关注的问题' if score >= 75 else '服务器存在明显异常')
        suggestions = ['优先处理服务器资源异常，并复核关联日志和资产信息'] if findings else ['保持当前监控并按计划复查服务器资源']
        links = [
            {'title': '服务器监控', 'path': '/observability/dashboards'},
            {'title': '告警中心', 'path': '/observability/alerts'},
            {'title': '日志检索', 'path': '/observability/logs'},
            {'title': '资产登记', 'path': '/cmdb/assets'},
        ]
    else:
        conclusion = '集群运行正常' if score >= 90 else ('集群存在需要关注的问题' if score >= 75 else '集群存在明显异常')
        suggestions = ['优先处理严重问题并复核关联事件和日志'] if findings else ['保持当前监控并按需复查']
        links = [
            {'title': 'K8s 监控', 'path': '/observability/dashboards'},
            {'title': '告警中心', 'path': '/observability/alerts'},
            {'title': '日志检索', 'path': '/observability/logs'},
            {'title': '资产登记', 'path': '/cmdb/assets'},
        ]
    if evidence_incomplete:
        source_names = {'metrics': 'Prometheus 指标', 'k8s': 'K8s API'}
        missing_text = '、'.join(source_names.get(name, name) for name in missing_required_sources)
        scope_name = '服务器' if profile == 'server' else '集群'
        conclusion = f'{scope_name}巡检证据不完整，当前健康分仅基于已获取证据，不能确认整体健康状态'
        suggestions.insert(0, f'先恢复 {missing_text} 采集，再重新执行巡检')
    return {
        'status': 'completed' if not missing and not evidence_incomplete else 'partial',
        'profile': profile,
        'health_score': score,
        'conclusion': conclusion,
        'cluster_summary': summary,
        'server_summary': metric_summary,
        'findings': findings,
        'score_deductions': score_deductions,
        'evidence': evidence,
        'suggestions': suggestions,
        'missing_evidence': missing,
        'links': links,
    }
