from urllib.parse import quote

import re
from datetime import datetime, timedelta, timezone as datetime_timezone
from urllib.parse import urlparse

import requests as http_requests
from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from eventwall.mixins import EventWallModelViewSetMixin
from eventwall.models import EventRecord
from eventwall.services import record_event
from rbac.permissions import RBACPermissionMixin, build_rbac_permission
from rbac.services import user_has_permissions
from .dashboard_presets import ensure_builtin_dashboards
from .datasource_health import datasource_health_payload
from .models import Alert, Deployment, LogDataSource, LogEntry, MetricDataSource, ObservabilityDashboard
from .sla import build_sla_summary
from .serializers import (
    AlertSerializer,
    MetricDataSourceSerializer,
    ObservabilityDashboardSerializer,
)

def _deny_if_missing_any(request, codes):
    allowed = any(user_has_permissions(request.user, [code]) for code in codes)
    if allowed:
        return None
    return Response({'detail': f"缺少权限: {', '.join(codes)}"}, status=403)


def _has_permission(request, code):
    return user_has_permissions(request.user, [code])


def _observability_access(request):
    return {
        'log_query': _has_permission(request, 'ops.log.query'),
        'log_entry': _has_permission(request, 'ops.log.entry.view'),
        'log_datasource': _has_permission(request, 'ops.log.datasource.view'),
        'alerts': _has_permission(request, 'ops.alert.view'),
        'metric_query': _has_permission(request, 'ops.metric.query'),
        'metric_datasource': _has_permission(request, 'ops.metric.datasource.view'),
        'monitor_dashboard': _has_permission(request, 'ops.monitor.dashboard.view'),
        'eventwall': _has_permission(request, 'eventwall.view'),
    }


def _observability_defaults():
    return getattr(settings, 'OBSERVABILITY_CONFIG', {}) or {}


def _log_module_summary():
    providers = []
    grouped = LogDataSource.objects.values('provider').annotate(total=Count('id')).order_by('provider')
    enabled_by_provider = {
        item['provider']: item['count']
        for item in LogDataSource.objects.filter(is_enabled=True).values('provider').annotate(count=Count('id'))
    }
    for item in grouped:
        provider = item['provider']
        providers.append({
            'provider': provider,
            'total': item['total'],
            'enabled': enabled_by_provider.get(provider, 0),
        })

    return {
        'query_path': '/logs/query',
        'datasource_path': '/logs/datasources',
        'datasource_count': LogDataSource.objects.count(),
        'enabled_count': LogDataSource.objects.filter(is_enabled=True).count(),
        'default_count': LogDataSource.objects.filter(is_default=True).count(),
        'providers': providers,
    }


def _alert_module_summary():
    latest = Alert.objects.select_related('host').prefetch_related('claim_records').all()[:5]
    return {
        'path': '/alerts',
        'total': Alert.objects.count(),
        'unacknowledged': Alert.objects.filter(claim_records__isnull=True).distinct().count(),
        'critical': Alert.objects.filter(level='critical').count(),
        'warning': Alert.objects.filter(level='warning').count(),
        'info': Alert.objects.filter(level='info').count(),
        'recent': AlertSerializer(latest, many=True).data,
    }


def _is_example_url(value):
    parsed = urlparse(str(value or ''))
    host = (parsed.hostname or '').lower()
    return not host or host.endswith('.example.com') or host in {'example.com', 'demo-loki.example.com'}


def _config_bool(value, default=True):
    if value is None:
        return default
    return str(value).strip().lower() not in {'0', 'false', 'no', 'off'}


def _config_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _prometheus_headers(config):
    headers = {'Accept': 'application/json'}
    token = str(config.get('bearer_token') or config.get('token') or config.get('api_token') or '').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _metric_config_value(config, *keys, default=''):
    if not isinstance(config, dict):
        return default
    for key in keys:
        if key in config and config.get(key) not in (None, ''):
            return config.get(key)
    basic = config.get('prometheus.basic') if isinstance(config.get('prometheus.basic'), dict) else {}
    for key in keys:
        if key in basic and basic.get(key) not in (None, ''):
            return basic.get(key)
    return default


def _metric_headers(config):
    headers = {'Accept': 'application/json'}
    configured = _metric_config_value(config, 'headers', 'prometheus.headers', default={})
    if isinstance(configured, dict):
        for key, value in configured.items():
            header_key = str(key or '').strip()
            if header_key and value not in (None, ''):
                headers[header_key] = str(value)

    auth_type = str(_metric_config_value(config, 'auth_type', default='none') or 'none').lower()
    bearer_token = str(_metric_config_value(config, 'bearer_token', 'token', 'api_key', default='') or '').strip()
    if auth_type in {'bearer', 'token'} and bearer_token and 'Authorization' not in headers:
        headers['Authorization'] = f'Bearer {bearer_token}'
    return headers


def _metric_auth(config):
    auth_type = str(_metric_config_value(config, 'auth_type', default='none') or 'none').lower()
    username = str(_metric_config_value(config, 'username', 'user', 'prometheus.user', default='') or '').strip()
    password = str(_metric_config_value(config, 'password', 'prometheus.password', default='') or '').strip()
    if auth_type == 'basic' and username:
        return (username, password)
    if not auth_type or auth_type == 'none':
        if username and password:
            return (username, password)
    return None


def _metric_datasource_payload(datasource):
    if not datasource:
        return None
    return {
        'id': datasource.id,
        'name': datasource.name,
        'provider': datasource.provider,
        'provider_display': datasource.get_provider_display(),
        'environment': datasource.environment,
        'cluster_name': datasource.cluster_name,
        'tsdb_type': datasource.tsdb_type,
        'is_default': datasource.is_default,
    }


def _select_metric_datasource(metric_datasource_id='', environment=''):
    datasource_id = str(metric_datasource_id or '').strip()
    if datasource_id:
        try:
            datasource = MetricDataSource.objects.get(pk=datasource_id)
        except (MetricDataSource.DoesNotExist, ValueError) as exc:
            raise ValueError('指标数据源不存在') from exc
        if not datasource.is_enabled:
            raise ValueError('指标数据源已停用')
        return datasource

    queryset = MetricDataSource.objects.filter(is_enabled=True)
    env_text = str(environment or '').strip()
    if env_text:
        datasource = queryset.filter(environment=env_text, is_default=True).order_by('name').first()
        if datasource:
            return datasource
        datasource = queryset.filter(environment=env_text).order_by('-is_default', 'name').first()
        if datasource:
            return datasource

    datasource = queryset.filter(environment='', is_default=True).order_by('name').first()
    if datasource:
        return datasource
    return queryset.order_by('-is_default', 'environment', 'name').first()


def _resolve_metric_datasource_client(metric_datasource_id='', environment=''):
    datasource = _select_metric_datasource(metric_datasource_id=metric_datasource_id, environment=environment)
    if not datasource:
        return None
    config = datasource.config if isinstance(datasource.config, dict) else {}
    query_url = str(_metric_config_value(
        config,
        'query_url',
        'addr',
        'prometheus.addr',
        'internal_addr',
        'prometheus.internal_addr',
        default='',
    ) or '').strip().rstrip('/')
    if not query_url or _is_example_url(query_url):
        return {
            'ready': False,
            'warning': '指标数据源未配置 Prometheus 地址',
            'metric_datasource': _metric_datasource_payload(datasource),
        }
    timeout = _config_int(_metric_config_value(config, 'timeout', 'prometheus.timeout', default=6), 6)
    tls_skip_verify = _config_bool(_metric_config_value(config, 'tls_skip_verify', 'insecure_skip_verify', default=False), False)
    return {
        'ready': True,
        'base_url': query_url,
        'headers': _metric_headers(config),
        'auth': _metric_auth(config),
        'timeout': timeout,
        'verify': not tls_skip_verify,
        'source': 'metric_datasource',
        'description': f'{datasource.name} / {datasource.get_provider_display()}',
        'metric_datasource': _metric_datasource_payload(datasource),
    }


def _prometheus_config():
    defaults = _observability_defaults()
    config = dict(defaults.get('prometheus') or {})
    config.setdefault('enabled', True)
    config.setdefault('query_url', '')
    config.setdefault('bearer_token', '')
    config.setdefault('api_token', '')
    config.setdefault('timeout', 6)
    return config


def _resolve_prometheus_client(overrides=None):
    config = _prometheus_config()
    if isinstance(overrides, dict):
        for key in ['query_url', 'timeout']:
            if overrides.get(key) not in (None, ''):
                config[key] = overrides.get(key)
    if not _config_bool(config.get('enabled'), True):
        return {'ready': False, 'warning': 'Prometheus 查询已禁用'}

    timeout = _config_int(config.get('timeout'), 6)
    headers = _prometheus_headers(config)
    query_url = str(config.get('query_url') or '').strip().rstrip('/')
    if query_url:
        return {
            'ready': True,
            'base_url': query_url,
            'headers': headers,
            'timeout': timeout,
            'source': 'prometheus',
            'description': 'Prometheus HTTP API',
        }

    return {'ready': False, 'warning': '未配置可用的 Prometheus 地址'}


def _prometheus_query(client, query, at_time=None):
    params = {'query': query}
    if at_time:
        params['time'] = at_time.timestamp()
    response = http_requests.get(
        f"{client['base_url'].rstrip('/')}/api/v1/query",
        params=params,
        headers=client.get('headers') or {},
        timeout=client.get('timeout') or 6,
        auth=client.get('auth'),
        verify=client.get('verify', True),
    )
    if response.status_code >= 400:
        raise RuntimeError(f'Prometheus HTTP {response.status_code}')
    body = response.json()
    if body.get('status') != 'success':
        raise RuntimeError(body.get('error') or 'Prometheus 查询失败')
    return ((body.get('data') or {}).get('result') or [])


def _prometheus_query_range(client, query, start_time, end_time, step):
    params = {
        'query': query,
        'start': start_time.timestamp(),
        'end': end_time.timestamp(),
        'step': step,
    }
    response = http_requests.get(
        f"{client['base_url'].rstrip('/')}/api/v1/query_range",
        params=params,
        headers=client.get('headers') or {},
        timeout=client.get('timeout') or 6,
        auth=client.get('auth'),
        verify=client.get('verify', True),
    )
    if response.status_code >= 400:
        raise RuntimeError(f'Prometheus HTTP {response.status_code}')
    body = response.json()
    if body.get('status') != 'success':
        raise RuntimeError(body.get('error') or 'Prometheus 查询失败')
    data = body.get('data') or {}
    return data.get('result') or [], data.get('resultType') or ''


def _prometheus_label_values(client, label_name, *, match_expr='', start_time=None, end_time=None, limit=2000):
    params = {}
    if match_expr:
        params['match[]'] = match_expr
    if start_time:
        params['start'] = start_time.timestamp()
    if end_time:
        params['end'] = end_time.timestamp()
    response = http_requests.get(
        f"{client['base_url'].rstrip('/')}/api/v1/label/{quote(str(label_name or ''), safe='')}/values",
        params=params,
        headers=client.get('headers') or {},
        timeout=client.get('timeout') or 6,
        auth=client.get('auth'),
        verify=client.get('verify', True),
    )
    if response.status_code >= 400:
        raise RuntimeError(f'Prometheus HTTP {response.status_code}')
    body = response.json()
    if body.get('status') != 'success':
        raise RuntimeError(body.get('error') or 'Prometheus 标签查询失败')
    values = (body.get('data') or []) if isinstance(body.get('data'), list) else []
    return [str(item) for item in values if item not in (None, '')][:limit]


def _prometheus_scalar(client, query, at_time=None):
    results = _prometheus_query(client, query, at_time=at_time)
    return _prometheus_value(results[0]) if results else None


def _prometheus_series_map(client, query, labels, at_time=None):
    mapped = {}
    for result in _prometheus_query(client, query, at_time=at_time):
        metric = result.get('metric') or {}
        key = tuple(str(metric.get(label) or '') for label in labels)
        if len(key) == 1:
            key = key[0]
        value = _prometheus_value(result)
        if value is not None:
            mapped[key] = value
    return mapped


def _safe_prometheus_scalar(client, query, warnings, at_time=None):
    try:
        return _prometheus_scalar(client, query, at_time=at_time)
    except Exception as exc:
        warnings.append(str(exc))
        return None


def _parse_promql_datetime(value, default):
    if value in (None, ''):
        return default
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromtimestamp(float(text), tz=datetime_timezone.utc)
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
            except ValueError:
                parsed = default
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, datetime_timezone.utc)
    return parsed


def _normalize_promql_step(value, default=60):
    text = str(value or '').strip().lower()
    if not text:
        return default
    multipliers = {'s': 1, 'm': 60, 'h': 3600}
    suffix = text[-1]
    try:
        if suffix in multipliers:
            seconds = int(float(text[:-1]) * multipliers[suffix])
        else:
            seconds = int(float(text))
    except (TypeError, ValueError):
        return default
    return min(max(seconds, 1), 3600)


def _promql_result_sample(results, limit=5):
    sample = []
    for item in (results or [])[:limit]:
        metric = item.get('metric') or {}
        value = item.get('value')
        values = item.get('values')
        latest = values[-1] if values else value
        sample.append({
            'metric': metric,
            'value': latest,
            'points': len(values or []),
        })
    return sample


def execute_promql_query(query, *, range_query=False, start_time=None, end_time=None, step=60, metric_datasource_id='', environment='', prefer_metric_datasource=False):
    query = str(query or '').strip()
    if not query:
        raise ValueError('PromQL 不能为空')
    if len(query) > 2000:
        raise ValueError('PromQL 过长')

    client = None
    if prefer_metric_datasource or metric_datasource_id or environment:
        client = _resolve_metric_datasource_client(metric_datasource_id=metric_datasource_id, environment=environment)
    if client is None:
        client = _resolve_prometheus_client()
    if not client.get('ready'):
        raise RuntimeError(client.get('warning') or 'Prometheus 数据源未就绪')

    now = timezone.now()
    end_dt = _parse_promql_datetime(end_time, now)
    start_dt = _parse_promql_datetime(start_time, end_dt - timedelta(minutes=30))
    if start_dt >= end_dt:
        start_dt = end_dt - timedelta(minutes=30)
    step_seconds = _normalize_promql_step(step)

    if range_query:
        results, result_type = _prometheus_query_range(client, query, start_dt, end_dt, step_seconds)
    else:
        results = _prometheus_query(client, query, at_time=end_dt)
        result_type = 'vector'
    return {
        'query': query,
        'range': bool(range_query),
        'start': start_dt.isoformat(),
        'end': end_dt.isoformat(),
        'step': step_seconds,
        'source': client.get('source'),
        'description': client.get('description'),
        'metric_datasource': client.get('metric_datasource'),
        'resultType': result_type,
        'result': results,
        'sample': _promql_result_sample(results),
        'series_count': len(results or []),
    }


NATIVE_PROMETHEUS_DASHBOARDS = {
    'server': {
        'title': '服务器看板',
        'description': '服务器 CPU、内存、磁盘、网络与节点资源排行。',
        'panels': [
            {'key': 'server-node-total', 'title': '服务器数', 'type': 'stat', 'unit': '台', 'query': 'count(node_uname_info) or count(up{job=~"node.*|node-exporter"})'},
            {'key': 'server-cpu-usage', 'title': 'CPU 使用率', 'type': 'stat', 'unit': '%', 'decimals': 1, 'query': '(1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))) * 100'},
            {'key': 'server-memory-usage', 'title': '内存使用率', 'type': 'stat', 'unit': '%', 'decimals': 1, 'query': '(1 - sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)) * 100'},
            {'key': 'server-disk-usage', 'title': '根分区磁盘使用率', 'type': 'stat', 'unit': '%', 'decimals': 1, 'query': '(1 - sum(node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs"}) / sum(node_filesystem_size_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs"})) * 100'},
            {'key': 'server-node-cpu-top', 'title': '节点 CPU Top', 'type': 'bar', 'unit': '%', 'label': 'instance', 'query': 'topk(10, sum by(instance) (rate(node_cpu_seconds_total{mode!="idle"}[5m])) / sum by(instance) (rate(node_cpu_seconds_total[5m])) * 100)'},
            {'key': 'server-node-memory-top', 'title': '节点内存 Top', 'type': 'bar', 'unit': '%', 'label': 'instance', 'query': 'topk(10, (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100)'},
            {'key': 'server-node-disk-top', 'title': '节点磁盘 Top', 'type': 'bar', 'unit': '%', 'label': 'instance', 'query': 'topk(10, (1 - node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs"} / node_filesystem_size_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs"}) * 100)'},
            {'key': 'server-network-throughput', 'title': '节点网络吞吐', 'type': 'timeseries', 'unit': 'B/s', 'label': 'instance', 'query': 'sum by(instance) (rate(node_network_receive_bytes_total{device!~"lo|veth.*|cali.*|flannel.*|vxlan.*"}[5m]) + rate(node_network_transmit_bytes_total{device!~"lo|veth.*|cali.*|flannel.*|vxlan.*"}[5m]))'},
        ],
    },
    'kubernetes': {
        'title': 'K8S 集群看板',
        'description': '集群节点、命名空间、Pod 状态、资源用量与存储网络概览。',
        'panels': [
            {'key': 'cluster-node-total', 'title': '集群节点总数', 'type': 'stat', 'unit': '个', 'query': 'count(kube_node_info)'},
            {'key': 'cluster-namespace-total', 'title': '命名空间总数', 'type': 'stat', 'unit': '个', 'query': 'count(count by(namespace)(kube_pod_info))'},
            {'key': 'cluster-running-pods', 'title': '运行中 Pod', 'type': 'stat', 'unit': '个', 'query': 'count(kube_pod_status_phase{phase="Running"} == 1) or vector(0)'},
            {'key': 'cluster-abnormal-pods', 'title': '异常 Pod', 'type': 'stat', 'unit': '个', 'query': 'count(kube_pod_status_phase{phase=~"Pending|Failed|Unknown"} == 1) or vector(0)'},
            {'key': 'cluster-cpu-usage', 'title': '集群 CPU 使用率', 'type': 'stat', 'unit': '%', 'decimals': 1, 'query': 'sum(rate(container_cpu_usage_seconds_total{namespace!=""}[5m])) / sum(kube_node_status_allocatable{resource="cpu"}) * 100'},
            {'key': 'cluster-memory-usage', 'title': '集群内存使用率', 'type': 'stat', 'unit': '%', 'decimals': 1, 'query': 'sum(container_memory_usage_bytes{namespace!=""}) / sum(kube_node_status_allocatable{resource="memory"}) * 100'},
            {'key': 'node-cpu-usage', 'title': '节点 CPU 使用率', 'type': 'timeseries', 'unit': '%', 'label': 'instance', 'query': 'sum by(instance) (rate(node_cpu_seconds_total{mode!="idle"}[5m])) / sum by(instance) (rate(node_cpu_seconds_total[5m])) * 100'},
            {'key': 'node-memory-usage', 'title': '节点内存使用率', 'type': 'timeseries', 'unit': '%', 'label': 'instance', 'query': '(1 - sum by(instance) (node_memory_MemAvailable_bytes) / sum by(instance) (node_memory_MemTotal_bytes)) * 100'},
            {'key': 'pod-restarts-top', 'title': 'Pod 重启次数 Top 10', 'type': 'bar', 'unit': '次', 'label': 'pod', 'query': 'topk(10, sum by(pod, namespace) (increase(kube_pod_container_status_restarts_total[24h])))'},
            {'key': 'pod-phase-distribution', 'title': 'Pod 状态分布', 'type': 'bar', 'unit': '个', 'label': 'phase', 'query': 'count by(phase) (kube_pod_status_phase == 1)'},
            {'key': 'namespace-pod-count', 'title': '命名空间 Pod 数量', 'type': 'bar', 'unit': '个', 'label': 'namespace', 'query': 'sort_desc(count by(namespace) (kube_pod_info))'},
            {'key': 'pod-cpu-top', 'title': 'CPU 使用量 Top 10 Pod', 'type': 'bar', 'unit': 'core', 'label': 'pod', 'query': 'topk(10, sum by(pod, namespace) (rate(container_cpu_usage_seconds_total{pod!=""}[5m])))'},
            {'key': 'pod-memory-top', 'title': '内存使用量 Top 10 Pod', 'type': 'bar', 'unit': 'bytes', 'label': 'pod', 'query': 'topk(10, sum by(pod, namespace) (container_memory_working_set_bytes{pod!=""}))'},
        ],
    },
}

NATIVE_DASHBOARD_ALIASES = {
    'infrastructure': 'server',
}

NATIVE_DASHBOARD_CATALOG = [
    {
        'key': 'server',
        'title': '服务器看板',
        'type': 'server',
        'source_type': 'prometheus',
        'description': '查看服务器 CPU、内存、磁盘、网络与节点资源排行。',
    },
    {
        'key': 'kubernetes',
        'title': 'K8S 集群看板',
        'type': 'kubernetes',
        'source_type': 'prometheus',
        'description': '查看集群节点、命名空间、Pod 状态与资源用量。',
    },
    {
        'key': 'logs',
        'title': '日志看板',
        'type': 'logs',
        'source_type': 'clickhouse',
        'description': '查看容器日志与 WEB 请求日志的趋势、排行和明细。',
        'variants': ['container', 'web'],
    },
]


def _native_dashboard_summary():
    return {
        'configured': True,
        'source': 'native',
        'dashboard_count': len(NATIVE_DASHBOARD_CATALOG),
        'types': [item['type'] for item in NATIVE_DASHBOARD_CATALOG],
        'dashboards': NATIVE_DASHBOARD_CATALOG,
    }


NATIVE_LOG_DASHBOARDS = {
    'container': {
        'title': '容器日志看板',
        'description': 'K8S 容器日志总量、级别、节点、命名空间、Pod 与最近日志。',
        'default_collection': 'container-logs',
        'panels': [
            {'key': 'container-log-total', 'title': '日志总量', 'type': 'stat', 'unit': '条', 'sql': 'SELECT count() AS value FROM {table} WHERE {time_filter} {filters}'},
            {'key': 'container-error-total', 'title': '错误数', 'type': 'stat', 'unit': '条', 'sql': "SELECT countIf(log_level IN ('ERROR','FATAL','CRITICAL','error','fatal','critical')) AS value FROM {table} WHERE {time_filter} {filters}"},
            {'key': 'container-pod-total', 'title': 'Pod 数', 'type': 'stat', 'unit': '个', 'sql': 'SELECT uniq(pod_name) AS value FROM {table} WHERE {time_filter} {filters}'},
            {'key': 'container-node-total', 'title': '节点数', 'type': 'stat', 'unit': '个', 'sql': "SELECT uniq(node_name) AS value FROM {table} WHERE node_name != '' AND {time_filter} {filters}"},
            {'key': 'container-log-level-trend', 'title': '日志级别趋势', 'type': 'timeseries', 'unit': '条', 'sql': "SELECT toStartOfMinute({time_field}) AS time, log_level AS name, count() AS value FROM {table} WHERE {time_filter} AND log_level != '' {filters} GROUP BY time, name ORDER BY time"},
            {'key': 'container-log-by-node', 'title': '日志量 - 按节点', 'type': 'bar', 'unit': '条', 'sql': "SELECT node_name AS name, count() AS value FROM {table} WHERE node_name != '' AND {time_filter} {filters} GROUP BY name ORDER BY value DESC LIMIT 20"},
            {'key': 'container-log-by-pod', 'title': '日志量 - 按 Pod', 'type': 'bar', 'unit': '条', 'sql': "SELECT pod_name AS name, count() AS value FROM {table} WHERE pod_name != '' AND {time_filter} {filters} GROUP BY name ORDER BY value DESC LIMIT 20"},
            {'key': 'container-log-by-namespace', 'title': '日志量 - 按命名空间', 'type': 'bar', 'unit': '条', 'sql': "SELECT namespace AS name, count() AS value FROM {table} WHERE namespace != '' AND {time_filter} {filters} GROUP BY name ORDER BY value DESC LIMIT 20"},
            {'key': 'container-recent-logs', 'title': '最近容器日志', 'type': 'logs', 'unit': '', 'sql': 'SELECT toDateTime({time_field}) AS time, log_message AS body, log_level AS level, node_name, namespace, pod_name, container_name FROM {table} WHERE {time_filter} {filters} ORDER BY {time_field} DESC LIMIT 100'},
        ],
    },
    'web': {
        'title': 'WEB 请求日志看板',
        'description': 'NGINX/Ingress 请求 QPS、延迟、状态码、慢接口与来源分布。',
        'default_collection': 'ingress-access',
        'panels': [
            {'key': 'web-request-total', 'title': '请求总量', 'type': 'stat', 'unit': '次', 'sql': 'SELECT count() AS value FROM {table} WHERE {time_filter} {filters}'},
            {'key': 'web-error-total', 'title': '5XX 请求', 'type': 'stat', 'unit': '次', 'sql': 'SELECT countIf(status >= 500) AS value FROM {table} WHERE {time_filter} {filters}'},
            {'key': 'web-avg-latency', 'title': '平均响应时间', 'type': 'stat', 'unit': 'ms', 'decimals': 1, 'sql': 'SELECT avg(responsetime) * 1000 AS value FROM {table} WHERE {time_filter} {filters}'},
            {'key': 'web-qps', 'title': 'QPS 趋势', 'type': 'timeseries', 'unit': 'qps', 'sql': 'SELECT toStartOfMinute({time_field}) AS time, count() / 60 AS value, server_ip AS name FROM {table} WHERE {time_filter} {filters} GROUP BY time, name ORDER BY time'},
            {'key': 'web-latency', 'title': '响应时间趋势', 'type': 'timeseries', 'unit': 'ms', 'sql': 'SELECT toStartOfMinute({time_field}) AS time, avg(responsetime) * 1000 AS value, server_ip AS name FROM {table} WHERE {time_filter} {filters} GROUP BY time, name ORDER BY time'},
            {'key': 'web-status-distribution', 'title': '状态码分布', 'type': 'bar', 'unit': '次', 'sql': "SELECT toString(status) AS name, count() AS value FROM {table} WHERE {time_filter} {filters} GROUP BY name ORDER BY value DESC"},
            {'key': 'web-slow-paths', 'title': '慢请求路径 Top 20', 'type': 'bar', 'unit': 'ms', 'sql': 'SELECT top_path AS name, avg(responsetime) * 1000 AS value FROM {table} WHERE {time_filter} {filters} GROUP BY name HAVING count() > 0 ORDER BY value DESC LIMIT 20'},
            {'key': 'web-client-top', 'title': '用户 IP 请求量 Top 20', 'type': 'table', 'unit': '', 'sql': 'SELECT client_ip AS client_ip, count() AS pv, count(DISTINCT path) AS url_count, avg(responsetime) * 1000 AS avg_latency_ms FROM {table} WHERE {time_filter} {filters} GROUP BY client_ip ORDER BY pv DESC LIMIT 20'},
            {'key': 'web-path-top', 'title': 'URI 请求数 Top 30', 'type': 'table', 'unit': '', 'sql': 'SELECT path AS path, count() AS pv, count(DISTINCT client_ip) AS uv, avg(responsetime) * 1000 AS avg_latency_ms FROM {table} WHERE {time_filter} {filters} GROUP BY path ORDER BY pv DESC LIMIT 30'},
        ],
    },
}


def _native_now_ms():
    return int(timezone.now().timestamp() * 1000)


def _native_time_range(payload):
    now_ms = _native_now_ms()
    default_start = now_ms - 60 * 60 * 1000
    try:
        start_ms = int(float(payload.get('start_ms') or payload.get('start') or default_start))
    except (TypeError, ValueError):
        start_ms = default_start
    try:
        end_ms = int(float(payload.get('end_ms') or payload.get('end') or now_ms))
    except (TypeError, ValueError):
        end_ms = now_ms
    if start_ms < 10_000_000_000:
        start_ms *= 1000
    if end_ms < 10_000_000_000:
        end_ms *= 1000
    if start_ms >= end_ms:
        start_ms = end_ms - 60 * 60 * 1000
    return start_ms, end_ms


def _native_iso_from_ms(value):
    return datetime.fromtimestamp(int(value) / 1000, tz=datetime_timezone.utc).isoformat()


def _native_number(value):
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _native_promql_latest(result):
    values = result.get('values') if isinstance(result, dict) else None
    value = result.get('value') if isinstance(result, dict) else None
    latest = values[-1] if values else value
    if isinstance(latest, (list, tuple)) and len(latest) >= 2:
        return _native_number(latest[1])
    return _native_number(latest)


def _native_metric_label(metric, preferred=''):
    metric = metric or {}
    preferred = str(preferred or '').strip()
    if preferred and metric.get(preferred) not in (None, ''):
        return str(metric.get(preferred))
    for key in ['pod', 'namespace', 'node', 'instance', 'phase', 'status', 'name', 'job']:
        if metric.get(key) not in (None, ''):
            return str(metric.get(key))
    visible = [f'{key}={value}' for key, value in metric.items() if not str(key).startswith('__')]
    return ', '.join(visible) or 'value'


def _native_series_from_promql(payload, label=''):
    series = []
    for index, item in enumerate(payload.get('result') or []):
        metric = item.get('metric') or {}
        points = []
        raw_points = item.get('values') or ([item.get('value')] if item.get('value') else [])
        for point in raw_points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            value = _native_number(point[1])
            if value is None:
                continue
            points.append([int(float(point[0]) * 1000), value])
        series.append({
            'name': _native_metric_label(metric, label) or f'series-{index + 1}',
            'metric': metric,
            'points': points,
            'value': points[-1][1] if points else _native_promql_latest(item),
        })
    return series


def _native_bar_from_promql(payload, label=''):
    rows = []
    for item in payload.get('result') or []:
        value = _native_promql_latest(item)
        if value is None:
            continue
        rows.append({
            'name': _native_metric_label(item.get('metric') or {}, label),
            'value': value,
            'metric': item.get('metric') or {},
        })
    return sorted(rows, key=lambda item: item.get('value') or 0, reverse=True)


def _native_prometheus_panel(panel, request_data, start_ms, end_ms):
    payload = execute_promql_query(
        panel['query'],
        range_query=panel.get('type') == 'timeseries',
        start_time=_native_iso_from_ms(start_ms),
        end_time=_native_iso_from_ms(end_ms),
        step=request_data.get('step') or 60,
        metric_datasource_id=request_data.get('metric_datasource_id') or request_data.get('datasource_id') or '',
        environment=request_data.get('environment') or '',
        prefer_metric_datasource=True,
    )
    panel_type = panel.get('type')
    if panel_type == 'stat':
        series = _native_series_from_promql(payload, panel.get('label'))
        value = next((item.get('value') for item in series if item.get('value') is not None), None)
        return {'value': value, 'series': series}
    if panel_type == 'timeseries':
        return {'series': _native_series_from_promql(payload, panel.get('label'))}
    if panel_type == 'bar':
        return {'rows': _native_bar_from_promql(payload, panel.get('label'))}
    return {'series': _native_series_from_promql(payload, panel.get('label'))}


def _native_panel_response(panel, data=None, status_text='ok', error=''):
    return {
        'key': panel.get('key'),
        'title': panel.get('title'),
        'type': panel.get('type'),
        'unit': panel.get('unit') or '',
        'decimals': panel.get('decimals', 0),
        'status': status_text,
        'error': error,
        'data': data or {},
    }


def _native_prometheus_dashboard(request_data, start_ms, end_ms):
    request_data = dict(request_data or {})
    dashboard_key = str(request_data.get('dashboard') or 'kubernetes').strip() or 'kubernetes'
    dashboard_key = NATIVE_DASHBOARD_ALIASES.get(dashboard_key, dashboard_key)
    definition = NATIVE_PROMETHEUS_DASHBOARDS.get(dashboard_key) or NATIVE_PROMETHEUS_DASHBOARDS['kubernetes']
    datasource = _select_metric_datasource(
        metric_datasource_id=request_data.get('metric_datasource_id') or request_data.get('datasource_id') or '',
        environment=request_data.get('environment') or '',
    )
    if datasource:
        request_data['metric_datasource_id'] = datasource.id
    panels = []
    for panel in definition['panels']:
        try:
            panels.append(_native_panel_response(panel, _native_prometheus_panel(panel, request_data, start_ms, end_ms)))
        except Exception as exc:
            panels.append(_native_panel_response(panel, {}, 'warning', str(exc)))
    return {
        'dashboard': {
            'key': dashboard_key if dashboard_key in NATIVE_PROMETHEUS_DASHBOARDS else 'kubernetes',
            'title': definition['title'],
            'description': definition['description'],
            'source_type': 'prometheus',
        },
        'metric_datasource': _metric_datasource_payload(datasource),
        'panels': panels,
    }


def _native_sql_literal(value):
    escaped = str(value or '').replace('\\', '\\\\').replace("'", "\\'")
    return f"'{escaped}'"


def _native_sql_in_filter(field, values):
    if values in (None, '', [], ()):
        return ''
    if not isinstance(values, (list, tuple)):
        values = [values]
    cleaned = [str(item).strip() for item in values if str(item).strip() and str(item).strip() != '$__all']
    if not cleaned:
        return ''
    return f' AND {field} IN ({", ".join(_native_sql_literal(item) for item in cleaned)})'


def _native_clickhouse_filters(variant, request_data):
    if variant == 'container':
        return ''.join([
            _native_sql_in_filter('node_name', request_data.get('node') or request_data.get('nodes')),
            _native_sql_in_filter('pod_name', request_data.get('pod_name') or request_data.get('pods')),
            _native_sql_in_filter('namespace', request_data.get('namespace') or request_data.get('namespaces')),
            _native_sql_in_filter('log_level', request_data.get('log_level') or request_data.get('levels')),
        ])
    return ''.join([
        _native_sql_in_filter('server_ip', request_data.get('server_ip') or request_data.get('server_ips')),
        _native_sql_in_filter('domain', request_data.get('domain') or request_data.get('domains')),
        _native_sql_in_filter('status', request_data.get('status') or request_data.get('statuses')),
        _native_sql_in_filter('path', request_data.get('uri') or request_data.get('path')),
        _native_sql_in_filter('client_ip', request_data.get('client_ip') or request_data.get('client_ips')),
    ])


def _native_clickhouse_context(config, request_data, variant, start_ms, end_ms):
    from .log_views import _clickhouse_identifier, _clickhouse_time_expression, _resolve_clickhouse_collection

    collection_key = request_data.get('collection') or request_data.get('collection_key') or NATIVE_LOG_DASHBOARDS[variant]['default_collection']
    collection = _resolve_clickhouse_collection(config, {**request_data, 'collection': collection_key})
    table_ref = f'{_clickhouse_identifier(collection["database"], "database")}.{_clickhouse_identifier(collection["table"], "table")}'
    time_field = request_data.get('time_field') or collection.get('time_field') or config.get('time_field') or 'timestamp'
    timezone_name = request_data.get('timezone') or collection.get('timezone') or config.get('timezone') or 'Asia/Shanghai'
    time_identifier = _clickhouse_identifier(time_field, 'time field')
    time_filter = (
        f'{time_identifier} >= {_clickhouse_time_expression(start_ms, timezone_name)} '
        f'AND {time_identifier} <= {_clickhouse_time_expression(end_ms, timezone_name)}'
    )
    return {
        'collection': collection,
        'table': table_ref,
        'time_field': time_identifier,
        'time_filter': time_filter,
        'filters': _native_clickhouse_filters(variant, request_data),
    }


def _native_render_clickhouse_sql(template, context):
    return template.format(
        table=context['table'],
        time_field=context['time_field'],
        time_filter=context['time_filter'],
        filters=context['filters'],
    )


def _native_clickhouse_panel(panel, config, context):
    from .log_views import _clickhouse_data_rows, _clickhouse_request

    sql = _native_render_clickhouse_sql(panel['sql'], context)
    response = _clickhouse_request(config, sql)
    rows = _clickhouse_data_rows(response)
    panel_type = panel.get('type')
    if panel_type == 'stat':
        first = rows[0] if rows else {}
        return {'value': _native_number(first.get('value') if isinstance(first, dict) else None), 'rows': rows}
    if panel_type == 'timeseries':
        series_map = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get('name') or row.get('level') or row.get('status') or 'value')
            value = _native_number(row.get('value') or row.get('count()') or row.get('count'))
            if value is None:
                continue
            point_time = row.get('time') or row.get('t')
            try:
                timestamp_ms = int(datetime.fromisoformat(str(point_time).replace('Z', '+00:00')).timestamp() * 1000)
            except (TypeError, ValueError):
                timestamp_ms = _native_now_ms()
            series_map.setdefault(name, []).append([timestamp_ms, value])
        return {'series': [{'name': name, 'points': points, 'value': points[-1][1] if points else None} for name, points in series_map.items()]}
    if panel_type == 'bar':
        return {'rows': [{'name': str(row.get('name') or ''), 'value': _native_number(row.get('value')) or 0} for row in rows if isinstance(row, dict)]}
    if panel_type in {'table', 'logs'}:
        return {'rows': rows}
    return {'rows': rows}


def _native_log_dashboard(request_data, start_ms, end_ms):
    from .log_views import ProviderError, _merge_config

    datasource_id = request_data.get('log_datasource_id') or request_data.get('datasource_id')
    if not datasource_id:
        datasource = LogDataSource.objects.filter(provider='clickhouse', is_enabled=True).order_by('-is_default', 'name').first()
    else:
        datasource = LogDataSource.objects.get(pk=datasource_id)
    if not datasource or datasource.provider != 'clickhouse':
        raise ProviderError('请选择 ClickHouse 日志数据源')
    config = _merge_config('clickhouse', datasource.config)
    variant = str(request_data.get('log_dashboard') or request_data.get('variant') or '').strip().lower()
    if variant not in NATIVE_LOG_DASHBOARDS:
        variant = 'container'
    definition = NATIVE_LOG_DASHBOARDS[variant]
    context = _native_clickhouse_context(config, request_data, variant, start_ms, end_ms)

    panels = []
    for panel in definition['panels']:
        try:
            panels.append(_native_panel_response(panel, _native_clickhouse_panel(panel, config, context)))
        except Exception as exc:
            panels.append(_native_panel_response(panel, {}, 'warning', str(exc)))
    return {
        'dashboard': {
            'key': 'logs',
            'variant': variant,
            'title': definition['title'],
            'description': definition['description'],
            'source_type': 'clickhouse',
            'collection': context['collection'],
        },
        'log_datasource': {'id': datasource.id, 'name': datasource.name, 'provider': datasource.provider},
        'panels': panels,
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def native_dashboard(request):
    denied = _deny_if_missing_any(request, ['ops.monitor.dashboard.view', 'ops.metric.query', 'ops.log.query'])
    if denied:
        return denied
    request_data = dict(request.data or {})
    dashboard = str(request_data.get('dashboard') or 'kubernetes').strip().lower()
    dashboard = NATIVE_DASHBOARD_ALIASES.get(dashboard, dashboard)
    start_ms, end_ms = _native_time_range(request_data)
    try:
        if dashboard == 'logs':
            payload = _native_log_dashboard(request_data, start_ms, end_ms)
        else:
            if dashboard not in NATIVE_PROMETHEUS_DASHBOARDS:
                dashboard = 'kubernetes'
            request_data['dashboard'] = dashboard
            payload = _native_prometheus_dashboard(request_data, start_ms, end_ms)
    except LogDataSource.DoesNotExist:
        return Response({'detail': '日志数据源不存在'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    payload['time_range'] = {
        'start_ms': start_ms,
        'end_ms': end_ms,
        'step': _normalize_promql_step(request_data.get('step') or 60),
    }
    return Response(payload)


def _dashboard_panel_options(panel):
    return panel.options if isinstance(panel.options, dict) else {}


def _dashboard_panel_target(panel):
    targets = panel.targets if isinstance(panel.targets, list) else []
    return targets[0] if targets and isinstance(targets[0], dict) else {}


def _dashboard_prometheus_panel(panel, request_data, start_ms, end_ms):
    options = _dashboard_panel_options(panel)
    target = _dashboard_panel_target(panel)
    native_panel = {
        'key': panel.key,
        'title': panel.title,
        'type': panel.chart_type,
        'unit': options.get('unit') or '',
        'decimals': options.get('decimals', 0),
        'query': target.get('query') or target.get('promql') or '',
        'label': target.get('label') or options.get('label') or '',
    }
    return _native_panel_response(native_panel, _native_prometheus_panel(native_panel, request_data, start_ms, end_ms))


def _dashboard_clickhouse_context(config, request_data, collection_key, start_ms, end_ms):
    from .log_views import _clickhouse_identifier, _clickhouse_time_expression, _resolve_clickhouse_collection

    collection = _resolve_clickhouse_collection(config, {**request_data, 'collection': collection_key})
    table_ref = f'{_clickhouse_identifier(collection["database"], "database")}.{_clickhouse_identifier(collection["table"], "table")}'
    time_field = request_data.get('time_field') or collection.get('time_field') or config.get('time_field') or 'timestamp'
    timezone_name = request_data.get('timezone') or collection.get('timezone') or config.get('timezone') or 'Asia/Shanghai'
    time_identifier = _clickhouse_identifier(time_field, 'time field')
    time_filter = (
        f'{time_identifier} >= {_clickhouse_time_expression(start_ms, timezone_name)} '
        f'AND {time_identifier} <= {_clickhouse_time_expression(end_ms, timezone_name)}'
    )
    return {
        'collection': collection,
        'table': table_ref,
        'time_field': time_identifier,
        'time_filter': time_filter,
        'filters': '',
    }


def _dashboard_clickhouse_panel(panel, request_data, start_ms, end_ms):
    from .log_views import ProviderError, _merge_config

    datasource_id = request_data.get('log_datasource_id') or request_data.get('datasource_id')
    if datasource_id:
        datasource = LogDataSource.objects.get(pk=datasource_id)
    else:
        datasource = LogDataSource.objects.filter(provider='clickhouse', is_enabled=True).order_by('-is_default', 'name').first()
    if not datasource or datasource.provider != 'clickhouse':
        raise ProviderError('请选择 ClickHouse 日志数据源')
    target = _dashboard_panel_target(panel)
    options = _dashboard_panel_options(panel)
    config = _merge_config('clickhouse', datasource.config)
    context = _dashboard_clickhouse_context(config, request_data, target.get('collection') or 'container-logs', start_ms, end_ms)
    native_panel = {
        'key': panel.key,
        'title': panel.title,
        'type': panel.chart_type,
        'unit': options.get('unit') or '',
        'decimals': options.get('decimals', 0),
        'sql': target.get('sql') or 'SELECT count() AS value FROM {table} WHERE {time_filter}',
    }
    return _native_panel_response(native_panel, _native_clickhouse_panel(native_panel, config, context))


def _dashboard_sla_panel(panel):
    target = _dashboard_panel_target(panel)
    options = _dashboard_panel_options(panel)
    summary = build_sla_summary()
    metric = target.get('metric') or 'month_sla'
    value = summary.get(metric)
    native_panel = {
        'key': panel.key,
        'title': panel.title,
        'type': panel.chart_type,
        'unit': options.get('unit') or '',
        'decimals': options.get('decimals', 0),
    }
    return _native_panel_response(native_panel, {'value': value, 'summary': summary})


def _query_dashboard_definition(dashboard, request_data):
    request_data = dict(request_data or {})
    start_ms, end_ms = _native_time_range(request_data)
    panels = []
    for panel in dashboard.panels.all().order_by('sort_order', 'id'):
        try:
            if panel.datasource_type == 'prometheus':
                panels.append(_dashboard_prometheus_panel(panel, request_data, start_ms, end_ms))
            elif panel.datasource_type == 'clickhouse':
                panels.append(_dashboard_clickhouse_panel(panel, request_data, start_ms, end_ms))
            elif panel.datasource_type == 'sla':
                panels.append(_dashboard_sla_panel(panel))
            else:
                panels.append(_native_panel_response({'key': panel.key, 'title': panel.title, 'type': panel.chart_type}, {}, 'warning', 'unsupported datasource type'))
        except Exception as exc:
            panels.append(_native_panel_response({'key': panel.key, 'title': panel.title, 'type': panel.chart_type}, {}, 'warning', str(exc)))
    return {
        'dashboard': {
            'id': dashboard.id,
            'title': dashboard.title,
            'description': dashboard.description,
            'tags': dashboard.tags,
            'layout': dashboard.layout,
            'source': 'json',
        },
        'panels': panels,
        'time_range': {
            'start_ms': start_ms,
            'end_ms': end_ms,
            'step': _normalize_promql_step(request_data.get('step') or 60),
        },
    }


class ObservabilityDashboardViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = ObservabilityDashboardSerializer
    pagination_class = None
    event_module = 'ops'
    event_resource_type = 'observability_dashboard'
    event_resource_label = '可观测看板'
    event_resource_name_fields = ('title',)
    rbac_permissions = {
        'list': ['ops.monitor.dashboard.view'],
        'retrieve': ['ops.monitor.dashboard.view'],
        'create': ['ops.monitor.dashboard.manage'],
        'update': ['ops.monitor.dashboard.manage'],
        'partial_update': ['ops.monitor.dashboard.manage'],
        'destroy': ['ops.monitor.dashboard.manage'],
        'query': ['ops.monitor.dashboard.view'],
        'export': ['ops.monitor.dashboard.view'],
        'import_definition': ['ops.monitor.dashboard.manage'],
    }

    def get_queryset(self):
        ensure_builtin_dashboards()
        queryset = ObservabilityDashboard.objects.prefetch_related('panels').all()
        is_enabled = self.request.query_params.get('is_enabled')
        if is_enabled in ('true', 'false'):
            queryset = queryset.filter(is_enabled=is_enabled == 'true')
        return queryset.order_by('-is_builtin', 'title')

    @action(detail=True, methods=['post'])
    def query(self, request, pk=None):
        dashboard = self.get_object()
        return Response(_query_dashboard_definition(dashboard, request.data or {}))

    @action(detail=True, methods=['get'])
    def export(self, request, pk=None):
        dashboard = self.get_object()
        return Response(self.get_serializer(dashboard).data)

    @action(detail=False, methods=['post'], url_path='import')
    def import_definition(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dashboard = serializer.save(is_builtin=False)
        return Response(self.get_serializer(dashboard).data, status=status.HTTP_201_CREATED)


class MetricDataSourceViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = MetricDataSource.objects.all().order_by('environment', '-is_default', 'name')
    serializer_class = MetricDataSourceSerializer
    pagination_class = None
    event_module = 'ops'
    event_resource_type = 'metric_datasource'
    event_resource_label = '指标数据源'
    event_resource_name_fields = ('name',)
    event_exclude_fields = ('config',)
    rbac_permissions = {
        'list': ['ops.metric.datasource.view'],
        'retrieve': ['ops.metric.datasource.view'],
        'create': ['ops.metric.datasource.manage'],
        'update': ['ops.metric.datasource.manage'],
        'partial_update': ['ops.metric.datasource.manage'],
        'destroy': ['ops.metric.datasource.manage'],
        'test_connection': ['ops.metric.datasource.manage'],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        provider = self.request.query_params.get('provider')
        environment = self.request.query_params.get('environment')
        is_enabled = self.request.query_params.get('is_enabled')
        if provider:
            queryset = queryset.filter(provider=provider)
        if environment not in (None, ''):
            queryset = queryset.filter(environment=environment)
        if is_enabled in ('true', 'false'):
            queryset = queryset.filter(is_enabled=is_enabled == 'true')
        return queryset.order_by('environment', '-is_default', 'name')

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        datasource = self.get_object()
        try:
            client = _resolve_metric_datasource_client(metric_datasource_id=datasource.id)
            if not client or not client.get('ready'):
                raise RuntimeError((client or {}).get('warning') or '指标数据源未就绪')
            results = _prometheus_query(client, request.data.get('query') or 'up')
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_metric_datasource',
                title='测试指标数据源连通性',
                summary=f'指标数据源 {datasource.name} 连通性测试成功',
                resource_type='metric_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'metric-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'series_count': len(results or [])},
            )
            return Response({
                'success': True,
                'message': f'{datasource.name} 连接成功',
                'series_count': len(results or []),
                'sample': _promql_result_sample(results),
                'metric_datasource': _metric_datasource_payload(datasource),
            })
        except Exception as exc:
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_metric_datasource',
                title='测试指标数据源连通性',
                summary=f'指标数据源 {datasource.name} 连通性测试失败',
                result=EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING,
                resource_type='metric_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'metric-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'error': str(exc)},
            )
            return Response({'success': False, 'message': '连接测试失败', 'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)




@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.metric.query')])
def metrics_promql_query(request):
    query = request.data.get('query') or request.data.get('promql') or ''
    range_query = str(request.data.get('range') or request.data.get('query_type') or '').lower() in {'1', 'true', 'range', 'query_range'}
    if request.data.get('range_query') is not None:
        range_query = bool(request.data.get('range_query'))
    try:
        payload = execute_promql_query(
            query,
            range_query=range_query,
            start_time=request.data.get('start') or request.data.get('start_time'),
            end_time=request.data.get('end') or request.data.get('end_time'),
            step=request.data.get('step') or 60,
            metric_datasource_id=request.data.get('metric_datasource_id') or request.data.get('datasource_id') or '',
            environment=request.data.get('environment') or '',
            prefer_metric_datasource=True,
        )
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    return Response(payload)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.metric.query')])
def metrics_series_names(request):
    keyword = str(request.query_params.get('q') or request.query_params.get('keyword') or '').strip()
    limit = max(1, min(_config_int(request.query_params.get('limit'), 80), 200))
    lowered = keyword.lower()
    match_expr = ''
    if keyword:
        escaped_keyword = re.escape(keyword)
        match_expr = f'{{__name__=~".*{escaped_keyword}.*"}}'
    try:
        client = _resolve_metric_datasource_client(
            metric_datasource_id=request.query_params.get('metric_datasource_id') or request.query_params.get('datasource_id') or '',
            environment=request.query_params.get('environment') or '',
        )
        if not client or not client.get('ready'):
            raise RuntimeError((client or {}).get('warning') or '指标数据源未就绪')
        values = _prometheus_label_values(client, '__name__', match_expr=match_expr, limit=max(5000, limit * 20))
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    if lowered:
        values = [item for item in values if lowered in item.lower()]
    values = sorted(values, key=lambda item: (
        0 if lowered and item.lower().startswith(lowered) else 1,
        len(item),
        item,
    ))[:limit]
    return Response({
        'metrics': values,
        'keyword': keyword,
        'source': client.get('source') or 'metric_datasource',
        'metric_datasource': client.get('metric_datasource'),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sla_summary(request):
    denied = _deny_if_missing_any(request, ['ops.monitor.dashboard.view', 'ops.alert.view'])
    if denied:
        return denied
    summary = build_sla_summary()
    summary.pop('_monthly_alerts', None)
    return Response(summary)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def observability_overview(request):
    access = _observability_access(request)
    denied = _deny_if_missing_any(
        request,
        ['ops.monitor.dashboard.view', 'ops.metric.query', 'ops.metric.datasource.view', 'ops.log.query', 'ops.log.datasource.view', 'ops.alert.view'],
    )
    if denied:
        return denied

    if access['monitor_dashboard']:
        ensure_builtin_dashboards()
    dashboards = _native_dashboard_summary() if access['monitor_dashboard'] else None
    logs = _log_module_summary() if (access['log_query'] or access['log_datasource']) else None
    alerts = _alert_module_summary() if access['alerts'] else None
    datasource_health = datasource_health_payload() if (access['metric_datasource'] or access['log_datasource'] or access['metric_query'] or access['log_query']) else None
    if access['alerts']:
        from .alert_engine.scheduler import engine_status
        rule_engine = engine_status()
    else:
        rule_engine = None

    navigation = []
    if access['monitor_dashboard']:
        navigation.append({'title': '监控看板', 'path': '/observability/dashboards', 'description': '查看服务器、K8S、日志等原生看板', 'tone': 'accent'})
    if access['metric_query'] or access['metric_datasource']:
        navigation.append({'title': '指标查询', 'path': '/observability/metrics', 'description': '用 PromQL 查询 Prometheus 指标数据', 'tone': 'success'})
    if access['log_query'] or access['log_datasource']:
        navigation.append({'title': '日志中心', 'path': '/logs', 'description': '检索容器日志、集群事件和应用日志', 'tone': 'info'})
    if access['alerts']:
        navigation.append({'title': '告警中心', 'path': '/alerts', 'description': '查看告警、研判结论和处理状态', 'tone': 'danger'})

    return Response({
        'modules': {
            'dashboards': dashboards,
            'metrics': ({
                'datasource_count': MetricDataSource.objects.count(),
                'enabled_count': MetricDataSource.objects.filter(is_enabled=True).count(),
            } if access['metric_query'] or access['metric_datasource'] else None),
            'logs': logs,
            'alerts': alerts,
        },
        'summary': {
            'dashboard_count': dashboards['dashboard_count'] if dashboards else 0,
            'metric_datasource_count': MetricDataSource.objects.count() if access['metric_query'] or access['metric_datasource'] else 0,
            'datasource_count': logs['datasource_count'] if logs else 0,
            'unacknowledged_alerts': alerts['unacknowledged'] if alerts else 0,
        },
        'datasource_health': datasource_health,
        'rule_engine': rule_engine,
        'navigation': navigation,
        'recent_alerts': alerts['recent'] if alerts else [],
        'tips': [],
    })


