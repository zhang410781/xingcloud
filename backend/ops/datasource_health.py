import time
from collections import Counter

from django.utils import timezone

from .models import LogDataSource, MetricDataSource


STATUS_OK = 'ok'
STATUS_ERROR = 'error'
STATUS_NOT_CONFIGURED = 'not_configured'
STATUS_UNKNOWN = 'unknown'
REQUIRED_CLICKHOUSE_COLLECTIONS = ['container-logs', 'k8s-events', 'ingress-access']


def _metric_query_url(config):
    if not isinstance(config, dict):
        return ''
    for key in ['query_url', 'addr', 'prometheus.addr', 'internal_addr', 'prometheus.internal_addr']:
        value = str(config.get(key) or '').strip()
        if value:
            return value
    basic = config.get('prometheus.basic') if isinstance(config.get('prometheus.basic'), dict) else {}
    for key in ['addr', 'prometheus.addr', 'internal_addr', 'prometheus.internal_addr']:
        value = str(basic.get(key) or '').strip()
        if value:
            return value
    return ''


def _log_endpoint(config):
    return str((config or {}).get('endpoint') or '').strip() if isinstance(config, dict) else ''


def _update_health(datasource, status, message='', latency_ms=None):
    datasource.last_check_at = timezone.now()
    datasource.last_check_status = status
    datasource.last_check_message = str(message or '')[:500]
    datasource.last_check_latency_ms = latency_ms
    datasource.save(update_fields=[
        'last_check_at',
        'last_check_status',
        'last_check_message',
        'last_check_latency_ms',
        'updated_at',
    ])
    return datasource


def check_metric_datasource(datasource, query=None):
    started = time.perf_counter()
    config = datasource.config if isinstance(datasource.config, dict) else {}
    health_query = query or config.get('health_query') or 'up'
    if not datasource.is_enabled or not _metric_query_url(config):
        return _update_health(datasource, STATUS_NOT_CONFIGURED, 'Prometheus datasource is not configured', None)
    try:
        from .observability_views import _prometheus_query, _resolve_metric_datasource_client

        client = _resolve_metric_datasource_client(metric_datasource_id=datasource.id)
        if not client or not client.get('ready'):
            raise RuntimeError((client or {}).get('warning') or 'Prometheus datasource is not ready')
        results = _prometheus_query(client, health_query)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _update_health(datasource, STATUS_OK, f'{health_query} returned {len(results or [])} series', latency_ms)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _update_health(datasource, STATUS_ERROR, str(exc), latency_ms)


def _validate_clickhouse_collections(config):
    from .log_views import _clickhouse_collections, _resolve_clickhouse_collection

    configured = {item.get('key') for item in _clickhouse_collections(config)}
    missing = [key for key in REQUIRED_CLICKHOUSE_COLLECTIONS if key not in configured]
    if missing:
        raise RuntimeError(f'Missing ClickHouse collections: {", ".join(missing)}')
    for key in REQUIRED_CLICKHOUSE_COLLECTIONS:
        _resolve_clickhouse_collection(config, {'collection': key})


def check_log_datasource(datasource):
    started = time.perf_counter()
    config = datasource.config if isinstance(datasource.config, dict) else {}
    if not datasource.is_enabled or not _log_endpoint(config):
        return _update_health(datasource, STATUS_NOT_CONFIGURED, 'log datasource is not connected', None)
    try:
        from .log_views import _clickhouse_request, _elk_request, _merge_config

        if datasource.provider == 'clickhouse':
            merged = _merge_config('clickhouse', config)
            _clickhouse_request(merged, 'SELECT 1')
            _validate_clickhouse_collections(merged)
            message = 'ClickHouse SELECT 1 and collections parsed'
        elif datasource.provider in ('elk', 'elasticsearch'):
            merged = _merge_config('elk', config)
            try:
                health = _elk_request('GET', merged['endpoint'], '/_cluster/health', merged)
                cluster_status = str(health.get('status') or 'unknown').lower()
                if cluster_status == 'red':
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    return _update_health(datasource, STATUS_ERROR, 'Elasticsearch cluster status is red', latency_ms)
                message = f'Elasticsearch cluster status: {cluster_status}'
            except Exception:
                # A log reader often has index-read permission but not cluster-monitor permission.
                # Verify the configured index pattern in that least-privilege case.
                pattern = merged.get('index_pattern') or '*'
                _elk_request('POST', merged['endpoint'], f'/{pattern}/_search', merged, body={'size': 0, 'track_total_hits': False})
                message = f'Elasticsearch index read succeeded: {pattern}'
        else:
            return _update_health(datasource, STATUS_UNKNOWN, f'{datasource.provider} health check is not supported', None)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _update_health(datasource, STATUS_OK, message, latency_ms)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _update_health(datasource, STATUS_ERROR, str(exc), latency_ms)


def run_datasource_health_checks():
    checked = {'metrics': 0, 'logs': 0, 'errors': 0}
    for datasource in MetricDataSource.objects.all().order_by('environment', '-is_default', 'name'):
        check_metric_datasource(datasource)
        checked['metrics'] += 1
        if datasource.last_check_status == STATUS_ERROR:
            checked['errors'] += 1
    for datasource in LogDataSource.objects.all().order_by('provider', '-is_default', 'name'):
        check_log_datasource(datasource)
        checked['logs'] += 1
        if datasource.last_check_status == STATUS_ERROR:
            checked['errors'] += 1
    return checked


def _health_status(datasource):
    status = datasource.last_check_status or ''
    if status:
        return status
    config = datasource.config if isinstance(datasource.config, dict) else {}
    if isinstance(datasource, MetricDataSource):
        configured = bool(_metric_query_url(config))
    else:
        configured = bool(_log_endpoint(config))
    if not datasource.is_enabled or not configured:
        return STATUS_NOT_CONFIGURED
    return STATUS_UNKNOWN


def _metric_payload(datasource):
    status = _health_status(datasource)
    return {
        'id': datasource.id,
        'name': datasource.name,
        'provider': datasource.provider,
        'environment': datasource.environment,
        'cluster_name': datasource.cluster_name,
        'is_enabled': datasource.is_enabled,
        'is_default': datasource.is_default,
        'last_check_at': datasource.last_check_at.isoformat() if datasource.last_check_at else None,
        'last_check_status': status,
        'last_check_message': datasource.last_check_message,
        'last_check_latency_ms': datasource.last_check_latency_ms,
    }


def _log_payload(datasource):
    status = _health_status(datasource)
    contexts = [
        {'id': item.id, 'name': item.name, 'code': item.code}
        for item in datasource.aiops_knowledge_environments.all()
    ]
    return {
        'id': datasource.id,
        'name': datasource.name,
        'provider': datasource.provider,
        'business_contexts': contexts,
        'environment': ' / '.join(item['name'] for item in contexts),
        'is_enabled': datasource.is_enabled,
        'is_default': datasource.is_default,
        'last_check_at': datasource.last_check_at.isoformat() if datasource.last_check_at else None,
        'last_check_status': status,
        'last_check_message': datasource.last_check_message,
        'last_check_latency_ms': datasource.last_check_latency_ms,
    }


def datasource_health_payload():
    metrics = [_metric_payload(item) for item in MetricDataSource.objects.all().order_by('environment', '-is_default', 'name')]
    logs = [_log_payload(item) for item in LogDataSource.objects.all().prefetch_related('aiops_knowledge_environments').order_by('provider', '-is_default', 'name')]
    counts = Counter(item['last_check_status'] for item in metrics + logs)
    for key in [STATUS_OK, STATUS_ERROR, STATUS_NOT_CONFIGURED, STATUS_UNKNOWN]:
        counts.setdefault(key, 0)
    return {
        'summary': dict(counts),
        'metrics': metrics,
        'logs': logs,
    }
