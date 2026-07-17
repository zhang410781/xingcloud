from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
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
                values.append(float(raw))
            except (TypeError, ValueError):
                continue
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


def _k8s_evidence(context, depth, target=''):
    from .k8s_views import get_k8s_nodes_snapshot, get_k8s_pods_snapshot, get_k8s_resource_snapshot

    cluster = context.k8s_cluster
    namespaces = _namespaces(context)
    nodes = get_k8s_nodes_snapshot(cluster)
    pods = get_k8s_pods_snapshot(cluster, namespaces)
    if target:
        lowered = target.lower()
        nodes = [item for item in nodes if lowered in str(item.get('name') or '').lower()] or nodes
        pods = [item for item in pods if lowered in str(item.get('name') or '').lower()] or pods
    resources = {}
    if depth in {'targeted', 'full'}:
        kinds = ['deployments', 'statefulsets', 'daemonsets', 'pvcs'] if depth == 'full' else ['deployments', 'pvcs']
        for kind in kinds:
            resources[kind] = get_k8s_resource_snapshot(cluster, kind, namespaces)

    findings = []
    for node in nodes:
        if node.get('status') != 'Ready':
            findings.append({'fingerprint': f"node-not-ready:{node.get('name')}", 'severity': 'critical', 'code': 'node_not_ready', 'target': node.get('name'), 'message': '节点状态不是 Ready'})
    for pod in pods:
        if pod.get('status') not in {'Running', 'Succeeded'}:
            findings.append({'fingerprint': f"pod-phase:{pod.get('namespace')}:{pod.get('name')}", 'severity': 'warning', 'code': 'pod_abnormal', 'target': pod.get('name'), 'namespace': pod.get('namespace'), 'message': f"Pod 状态为 {pod.get('status')}"})
        if int(pod.get('restarts') or 0) >= 3:
            findings.append({'fingerprint': f"pod-restart:{pod.get('namespace')}:{pod.get('name')}", 'severity': 'warning', 'code': 'pod_restarts', 'target': pod.get('name'), 'namespace': pod.get('namespace'), 'message': f"Pod 已重启 {pod.get('restarts')} 次"})
    for pvc in resources.get('pvcs') or []:
        if pvc.get('status') != 'Bound':
            findings.append({'fingerprint': f"pvc:{pvc.get('namespace')}:{pvc.get('name')}", 'severity': 'warning', 'code': 'pvc_unbound', 'target': pvc.get('name'), 'namespace': pvc.get('namespace'), 'message': f"PVC 状态为 {pvc.get('status')}"})
    return {
        'status': 'ok',
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


def _log_evidence(context, *, alert=None, target='', window_minutes=60):
    datasource = context.log_datasource
    dimensions = _log_dimensions(alert=alert, target=target)
    end_at = (
        getattr(alert, 'ends_at', None)
        or getattr(alert, 'last_received_at', None)
        or getattr(alert, 'starts_at', None)
        or timezone.now()
    )
    initial_minutes = max(15, min(int(window_minutes or 60), 360))
    attempts = []
    result = None
    for minutes in list(dict.fromkeys([initial_minutes, 60])):
        payload = {
            'query': _log_query_terms(dimensions),
            'start_ms': int((end_at - timedelta(minutes=minutes)).timestamp() * 1000),
            'end_ms': int(end_at.timestamp() * 1000),
            'limit': 50,
        }
        if datasource.provider == 'clickhouse':
            config = datasource.config if isinstance(datasource.config, dict) else {}
            payload['collection'] = config.get('default_collection') or 'container-logs'
        attempts.append({'window_minutes': minutes, 'query': payload['query']})
        result = _run_query(datasource.provider, _merge_config(datasource.provider, datasource.config), payload)
        if result.get('logs') or minutes == 60:
            break
    logs = _dedupe_logs((result or {}).get('logs') or [])
    levels = Counter(item.get('level') or 'unknown' for item in logs)
    return {
        'status': 'ok',
        'datasource': {'id': datasource.id, 'name': datasource.name, 'provider': datasource.provider},
        'dimensions': dimensions,
        'field_map': (datasource.config if isinstance(datasource.config, dict) else {}).get('field_map') or {},
        'attempts': attempts,
        'total': (result or {}).get('total', len(logs)),
        'sample_count': len(logs),
        'level_distribution': dict(levels),
        'samples': logs,
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
        .filter(environment=environment)
        .values('id', 'name', 'resource_type', 'status', 'ip_address', 'cluster_id', 'owner')[:100]
    )
    middleware = list(
        MiddlewareAsset.objects
        .filter(task_resource_environment=environment)
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
    evidence = {
        'profile': profile,
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
        definitions = METRIC_MATRIX[:DEPTH_METRIC_LIMIT[depth]]
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

    if context.k8s_cluster_id:
        try:
            k8s = _k8s_evidence(context, depth, target=target)
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
    score = max(0, 100 - sum(deductions.get(item.get('severity'), 2) for item in findings))
    summary = (evidence.get('k8s') or {}).get('summary') or {}
    missing = [item.get('message') for item in evidence.get('diagnostics') or []]
    return {
        'status': 'completed' if not missing else 'partial',
        'health_score': score,
        'conclusion': '集群运行正常' if score >= 90 else ('集群存在需要关注的问题' if score >= 75 else '集群存在明显异常'),
        'cluster_summary': summary,
        'findings': findings,
        'evidence': evidence,
        'suggestions': ['优先处理严重问题并复核关联事件和日志'] if findings else ['保持当前监控并按需复查'],
        'missing_evidence': missing,
        'links': [
            {'title': 'K8s 监控', 'path': '/observability/dashboards'},
            {'title': '告警中心', 'path': '/observability/alerts'},
            {'title': '日志检索', 'path': '/observability/logs'},
            {'title': '资产登记', 'path': '/cmdb/assets'},
        ],
    }
