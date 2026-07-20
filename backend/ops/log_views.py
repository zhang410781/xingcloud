import hashlib
import json
import re
from datetime import datetime, timezone as dt_timezone

import requests as http_requests
from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .eventwall_stub import EventWallModelViewSetMixin
from .eventwall_stub import EventRecord
from .eventwall_stub import record_event
from .models import LogDataSource
from .serializers import LogDataSourceSerializer
from rbac.permissions import RBACPermissionMixin, build_rbac_permission


REQUEST_TIMEOUT = 30
DEMO_LOG_BATCHES = 48
SENSITIVE_KEYS = {
    'password',
    'api_key',
    'token',
    'bearer_token',
}
TRACE_ID_KEYS = ('trace_id', 'traceId', 'traceID', 'trace.id', 'trace.trace_id', 'otelTraceID')
TRACE_ID_PATTERN = re.compile(r'(?:"?(?:trace_id|traceId|traceID|trace\.id)"?\s*[:=]\s*"?(?P<trace>[0-9a-fA-F]{16,32})"?)')
CLICKHOUSE_DEFAULT_SEARCH_FIELDS = [
    'domain',
    'path',
    'top_path',
    'query',
    'client_ip',
    'remote_ip',
    'xff',
    'status',
    'server_ip',
    'http_user_agent',
]
CLICKHOUSE_DEFAULT_COLLECTIONS = [
    {
        'key': 'container-logs',
        'name': 'K8S Container Logs',
        'database': 'container_logs',
        'table': 'logs',
        'time_field': 'timestamp',
        'message_fields': 'message,log_message',
        'level_field': 'log_level',
        'source_fields': 'namespace,pod_name,container_name',
        'search_fields': 'namespace,pod_name,node_name,container_name,log_level,message,log_message,source,log_file_path',
    },
    {
        'key': 'k8s-events',
        'name': 'K8S Events',
        'database': 'container_logs',
        'table': 'events',
        'time_field': 'timestamp',
        'message_fields': 'message,reason',
        'level_field': 'event_type',
        'source_fields': 'namespace,pod_name,source_component',
        'search_fields': 'namespace,pod_name,event_type,reason,message,source_component,source_host,count',
    },
    {
        'key': 'ingress-access',
        'name': 'Ingress Access Logs',
        'database': 'nginxlogs',
        'table': 'nginx_access',
        'time_field': 'timestamp',
        'message_fields': '',
        'level_field': 'status',
        'source_fields': 'domain,server_ip,client_ip',
        'search_fields': ','.join(CLICKHOUSE_DEFAULT_SEARCH_FIELDS),
    },
]


def _extract_trace_id(attributes, message=''):
    if isinstance(attributes, dict):
        for key in TRACE_ID_KEYS:
            value = attributes.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key, value in attributes.items():
            if str(key).lower().replace('.', '_') in {'trace_id', 'traceid'} and isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(message, str) and message.strip():
        try:
            parsed = json.loads(message)
            if isinstance(parsed, dict):
                nested = _extract_trace_id(parsed, '')
                if nested:
                    return nested
        except ValueError:
            pass
        match = TRACE_ID_PATTERN.search(message)
        if match:
            return match.group('trace')
    return ''


def _with_trace_id(attributes, message=''):
    enriched = dict(attributes or {})
    trace_id = _extract_trace_id(enriched, message)
    if trace_id and not enriched.get('trace_id'):
        enriched['trace_id'] = trace_id
    return enriched


class ProviderError(Exception):
    def __init__(self, message, status_code=status.HTTP_400_BAD_REQUEST, detail=None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or {}


def _provider_defaults():
    configured = getattr(settings, 'LOG_PROVIDER_CONFIGS', None)
    if configured:
        return configured
    return {
        'loki': {
            'endpoint': getattr(settings, 'LOKI_URL', 'http://localhost:3100'),
        },
        'elk': {
            'endpoint': '',
            'auth_type': 'none',
            'index_pattern': 'logs-*',
            'time_field': '@timestamp',
            'message_fields': 'message,log,msg',
        },
        'clickhouse': {
            'endpoint': '',
            'username': '',
            'password': '',
            'timezone': 'Asia/Shanghai',
            'collections': [],
        },
    }


def _is_demo_config(config):
    return bool((config or {}).get('demo_mode'))


def _public_config(config):
    result = {}
    for key, value in (config or {}).items():
        if key in SENSITIVE_KEYS and not _is_demo_config(config):
            result[key] = 'configured' if value else ''
        else:
            result[key] = value
    return result


def _merge_config(provider, incoming=None):
    defaults = _provider_defaults().get(provider, {})
    merged = dict(defaults)
    for key, value in (incoming or {}).items():
        if value is not None and value != '':
            merged[key] = value
    return merged


def _resolve_provider_and_config(payload):
    datasource = None
    datasource_id = payload.get('datasource_id')

    if datasource_id:
        try:
            datasource = LogDataSource.objects.get(pk=datasource_id)
        except LogDataSource.DoesNotExist as exc:
            raise ProviderError('日志数据源不存在', status.HTTP_404_NOT_FOUND) from exc
        if not datasource.is_enabled:
            raise ProviderError('日志数据源已停用', status.HTTP_400_BAD_REQUEST)

    provider = payload.get('provider') or getattr(datasource, 'provider', None)
    if not provider:
        raise ProviderError('provider is required')
    if datasource and provider != datasource.provider:
        raise ProviderError('provider 与数据源类型不一致')

    config = _merge_config(provider, getattr(datasource, 'config', None))
    config = _merge_config(provider, {**config, **(payload.get('config') or {})})
    return provider, config, datasource


def _provider_info():
    defaults = _provider_defaults()
    return [
        {
            'id': 'loki',
            'name': 'Loki',
            'description': '基于标签的日志检索与 LogQL 查询。',
            'configured': bool(defaults.get('loki', {}).get('endpoint')),
            'defaults': _public_config(defaults.get('loki', {})),
        },
        {
            'id': 'elk',
            'name': 'ELK / Elasticsearch',
            'description': '使用 Lucene 语法检索 Elasticsearch 日志。',
            'configured': bool(defaults.get('elk', {}).get('endpoint')),
            'defaults': _public_config(defaults.get('elk', {})),
        },
        {
            'id': 'clickhouse',
            'name': 'ClickHouse',
            'description': 'Query structured logs stored in ClickHouse.',
            'configured': bool(defaults.get('clickhouse', {}).get('endpoint')),
            'defaults': _public_config(defaults.get('clickhouse', {})),
        },
    ]


def _safe_json(response):
    try:
        return response.json()
    except ValueError:
        return {'raw': response.text}


def _friendly_provider_error(provider, message):
    text = str(message or '')
    if provider == 'Loki' and 'empty-compatible value' in text:
        return 'Loki 查询条件无效：标签选择器必须至少包含一个非空匹配条件，例如 app=~".+"，不能只使用 app=~".*" 或 job!="" 这类可能匹配空值的条件。'
    return text


def _raise_for_status(response, provider):
    if response.ok:
        return
    payload = _safe_json(response)
    message = payload.get('error') or payload.get('message') or f'{provider} request failed'
    message = _friendly_provider_error(provider, message)
    raise ProviderError(message, status_code=response.status_code, detail=payload)


def _pick_message(source, fields):
    for field in fields:
        value = _get_nested(source, field)
        if value not in (None, ''):
            if isinstance(value, str):
                return value
            return json.dumps(value, ensure_ascii=False)
    return json.dumps(source, ensure_ascii=False)


def _get_nested(data, path):
    current = data
    for part in path.split('.'):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _split_fields(value, fallback):
    if isinstance(value, list):
        return [item for item in value if item]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.split(',') if item.strip()]
    return fallback


def _normalize_level(value):
    if value in (None, ''):
        return ''
    normalized = str(value).strip().lower()
    normalized = re.sub(r'[^a-z0-9_\u4e00-\u9fff-]+', '', normalized)
    if normalized in {'error', 'err', 'fatal', 'critical', 'crit', 'severe', '严重', '错误', '异常'}:
        return 'error'
    if normalized in {'warning', 'warn', 'warningwarn', '警告', '告警'}:
        return 'warning'
    if normalized in {'info', 'information', 'notice', '信息'}:
        return 'info'
    if normalized in {'debug', 'dbg', 'trace', 'verbose', '调试'}:
        return 'debug'
    if normalized.startswith(('err', 'fatal', 'crit', 'severe')):
        return 'error'
    if normalized.startswith('warn'):
        return 'warning'
    if normalized.startswith('info'):
        return 'info'
    if normalized.startswith(('debug', 'dbg')):
        return 'debug'
    return ''


def _detect_level(message, attributes=None):
    attributes = attributes or {}
    explicit_keys = (
        'detected_level',
        'detectedLevel',
        'level',
        'severity',
        'log.level',
        'severity_text',
        'severityText',
        'severityLabel',
        'priority',
    )
    for key in explicit_keys:
        raw_level = attributes.get(key)
        if raw_level in (None, '') and '.' in key:
            raw_level = _get_nested(attributes, key)
        level = _normalize_level(raw_level)
        if level:
            return level

    text = str(message or '')
    if text.strip().startswith(('{', '[')):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            for key in explicit_keys:
                raw_level = parsed.get(key)
                if raw_level in (None, '') and '.' in key:
                    raw_level = _get_nested(parsed, key)
                level = _normalize_level(raw_level)
                if level:
                    return level

    explicit_match = re.search(
        r'(?<![A-Za-z0-9_])["\']?(?:detected_level|detectedLevel|level|severity|log\.level)["\']?\s*[:=]\s*["\']?'
        r'(error|err|fatal|critical|crit|warn|warning|info|information|debug|trace)["\']?',
        text,
        flags=re.IGNORECASE,
    )
    if explicit_match:
        return _normalize_level(explicit_match.group(1))

    token_match = re.search(
        r'(?<![A-Za-z0-9_])(error|err|fatal|critical|crit|warn|warning|info|information|debug)\b',
        text,
        flags=re.IGNORECASE,
    )
    if token_match:
        return _normalize_level(token_match.group(1))

    lower = text.lower()
    if any(token in lower for token in ('fatal', 'panic', 'exception', 'traceback')):
        return 'error'
    if re.search(r'(?<![a-z0-9_])error(?![a-z0-9_])', lower):
        return 'error'
    if re.search(r'(?<![a-z0-9_])warn(?:ing)?(?![a-z0-9_])', lower):
        return 'warning'
    if re.search(r'(?<![a-z0-9_])debug(?![a-z0-9_])', lower):
        return 'debug'
    return 'unknown'


def _normalize_ms(value, default):
    if value in (None, ''):
        return default
    value = int(value)
    if value > 1_000_000_000_000:
        return value
    return value * 1000


def _time_bounds(payload):
    now_ms = int(datetime.now(dt_timezone.utc).timestamp() * 1000)
    default_start = now_ms - 3600 * 1000
    start_ms = _normalize_ms(payload.get('start_ms'), default_start)
    end_ms = _normalize_ms(payload.get('end_ms'), now_ms)
    if start_ms > end_ms:
        start_ms, end_ms = end_ms, start_ms
    return start_ms, end_ms


def _iso_from_ms(value):
    if value in (None, ''):
        return ''
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ''
        try:
            value = int(float(stripped))
        except ValueError:
            normalized = stripped.replace('Z', '+00:00')
            try:
                dt = datetime.fromisoformat(normalized)
            except ValueError:
                return stripped
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=dt_timezone.utc)
            return dt.astimezone(dt_timezone.utc).isoformat().replace('+00:00', 'Z')
    else:
        value = int(float(value))

    if value > 1_000_000_000_000:
        dt = datetime.fromtimestamp(value / 1000, tz=dt_timezone.utc)
    else:
        dt = datetime.fromtimestamp(value, tz=dt_timezone.utc)
    return dt.isoformat().replace('+00:00', 'Z')


def _iso_from_ns(value):
    return _iso_from_ms(int(value) / 1_000_000)


def _sanitize_limit(value, default=200, maximum=2000):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _normalize_endpoint(endpoint):
    if not endpoint:
        return ''
    endpoint = endpoint.strip()
    if endpoint.startswith('http://') or endpoint.startswith('https://'):
        return endpoint.rstrip('/')
    return f'http://{endpoint.rstrip("/")}'


def _extract_query_terms(query):
    if not query or query == '*':
        return []
    normalized = re.sub(r'[":=(){}\[\],]', ' ', str(query))
    tokens = [token for token in re.split(r'\s+', normalized) if token]
    ignored = {
        'and', 'or', 'not', 'service', 'name', 'level', 'message', 'log', 'host',
        'source', 'severity', 'status', 'app', 'env', 'query', 'topic',
    }
    return [token.lower() for token in tokens if token.lower() not in ignored and len(token) > 1]


def _matches_demo_query(message, attributes, query):
    terms = _extract_query_terms(query)
    if not terms:
        return True
    haystack = ' '.join([str(message), json.dumps(attributes or {}, ensure_ascii=False)]).lower()
    return all(term in haystack for term in terms)


def _demo_time_points(start_ms, end_ms, count):
    span = max(end_ms - start_ms, 1)
    step = max(int(span / max(count, 1)), 60_000)
    return [start_ms + step * index for index in range(count)]


def _demo_loki_entries(start_ms, end_ms):
    base_entries = [
        {
            'stream': {
                'job': 'gateway-service',
                'app': 'gateway-service',
                'namespace': 'prod',
                'cluster': 'cn-sh-prod',
                'region': 'cn-shanghai',
                'profile': 'prod',
                'container': 'gateway',
                'level': 'info',
                'service_name': 'gateway-service',
            },
            'thread': 'reactor-http-nio-4',
            'logger': 'com.xing-cloud.gateway.filter.AccessLogFilter',
            'message': 'route matched, routeId=workorder-service, path=/api/workorders/submit, cost=18ms',
        },
        {
            'stream': {
                'job': 'gateway-service',
                'app': 'gateway-service',
                'namespace': 'prod',
                'cluster': 'cn-sh-prod',
                'region': 'cn-shanghai',
                'profile': 'prod',
                'container': 'gateway',
                'level': 'error',
                'service_name': 'gateway-service',
            },
            'thread': 'reactor-http-nio-7',
            'logger': 'com.xing-cloud.gateway.filter.ExceptionLogFilter',
            'message': 'forward request failed, uri=lb://workorder-service, reason=ReadTimeoutException: downstream timeout',
        },
        {
            'stream': {
                'job': 'gateway-service',
                'app': 'gateway-service',
                'namespace': 'prod',
                'cluster': 'cn-sh-prod',
                'region': 'cn-shanghai',
                'profile': 'prod',
                'container': 'gateway',
                'level': 'info',
                'service_name': 'gateway-service',
            },
            'thread': 'reactor-http-nio-3',
            'logger': 'com.xing-cloud.gateway.filter.GrayReleaseRouteFilter',
            'message': 'gray release route hit, routeId=quality-service-gray, tenantId=t-ob, version=gray, header[X-Gray]=true',
        },
        {
            'stream': {
                'job': 'workorder-service',
                'app': 'workorder-service',
                'namespace': 'prod',
                'cluster': 'cn-sh-prod',
                'region': 'cn-shanghai',
                'profile': 'prod',
                'container': 'order',
                'level': 'info',
                'service_name': 'workorder-service',
            },
            'thread': 'http-nio-8082-exec-3',
            'logger': 'com.xing-cloud.order.controller.OrderController',
            'message': 'create order success, orderNo=SO202603150001, userId=10086, amount=299.00',
        },
        {
            'stream': {
                'job': 'workorder-service',
                'app': 'workorder-service',
                'namespace': 'prod',
                'cluster': 'cn-sh-prod',
                'region': 'cn-shanghai',
                'profile': 'prod',
                'container': 'order',
                'level': 'error',
                'service_name': 'workorder-service',
            },
            'thread': 'http-nio-8082-exec-7',
            'logger': 'com.xing-cloud.order.service.PaymentRemoteService',
            'message': 'feign invoke quality-service failed, status=500, retry=2, msg=quality status update timeout',
        },
        {
            'stream': {
                'job': 'workorder-service',
                'app': 'workorder-service',
                'namespace': 'prod',
                'cluster': 'cn-sh-prod',
                'region': 'cn-shanghai',
                'profile': 'prod',
                'container': 'order',
                'level': 'error',
                'service_name': 'workorder-service',
            },
            'thread': 'http-nio-8082-exec-11',
            'logger': 'com.xing-cloud.order.service.impl.OrderSubmitServiceImpl',
            'message': (
                'submit order failed, orderNo=SO202603150009, tenantId=t-vip, ex=java.lang.IllegalStateException: stock lock failed\n'
                'java.lang.IllegalStateException: stock lock failed\n'
                '\tat com.xing-cloud.order.service.impl.OrderSubmitServiceImpl.lockStock(OrderSubmitServiceImpl.java:214)\n'
                '\tat com.xing-cloud.order.service.impl.OrderSubmitServiceImpl.submit(OrderSubmitServiceImpl.java:126)\n'
                '\tat com.xing-cloud.order.controller.OrderController.submit(OrderController.java:58)\n'
                '\tat org.springframework.aop.framework.ReflectiveMethodInvocation.proceed(ReflectiveMethodInvocation.java:186)'
            ),
        },
        {
            'stream': {
                'job': 'quality-service',
                'app': 'quality-service',
                'namespace': 'prod',
                'cluster': 'cn-sh-prod',
                'region': 'cn-shanghai',
                'profile': 'prod',
                'container': 'quality',
                'level': 'info',
                'service_name': 'quality-service',
            },
            'thread': 'http-nio-8091-exec-5',
            'logger': 'com.xing-cloud.quality.service.CallbackService',
            'message': 'quality callback processed successfully, channel=alipay, tradeStatus=SUCCESS',
        },
        {
            'stream': {
                'job': 'quality-service',
                'app': 'quality-service',
                'namespace': 'prod',
                'cluster': 'cn-sh-prod',
                'region': 'cn-shanghai',
                'profile': 'prod',
                'container': 'quality',
                'level': 'error',
                'service_name': 'quality-service',
            },
            'thread': 'http-nio-8091-exec-8',
            'logger': 'com.xing-cloud.quality.service.SignVerifyService',
            'message': 'signature verify failed, orderNo=SO202603150001, channel=wechat, errorCode=SIGN_MISMATCH',
        },
        {
            'stream': {
                'job': 'quality-service',
                'app': 'quality-service',
                'namespace': 'prod',
                'cluster': 'cn-sh-prod',
                'region': 'cn-shanghai',
                'profile': 'prod',
                'container': 'quality',
                'level': 'error',
                'service_name': 'quality-service',
            },
            'thread': 'http-nio-8091-exec-12',
            'logger': 'com.xing-cloud.quality.controller.PaymentCallbackController',
            'message': (
                'quality callback processing exception, requestId=cb-20260315-991, tenantId=t-ob, ex=java.lang.NullPointerException: callback payload is null\n'
                'java.lang.NullPointerException: callback payload is null\n'
                '\tat com.xing-cloud.quality.controller.PaymentCallbackController.handle(PaymentCallbackController.java:87)\n'
                '\tat com.xing-cloud.quality.controller.PaymentCallbackController.callback(PaymentCallbackController.java:52)\n'
                '\tat java.base/jdk.internal.reflect.DirectMethodHandleAccessor.invoke(DirectMethodHandleAccessor.java:104)\n'
                '\tat org.springframework.web.method.support.InvocableHandlerMethod.doInvoke(InvocableHandlerMethod.java:257)'
            ),
        },
        {
            'stream': {
                'job': 'auth-service',
                'app': 'auth-service',
                'namespace': 'prod',
                'cluster': 'cn-sh-prod',
                'region': 'cn-shanghai',
                'profile': 'prod',
                'container': 'auth',
                'level': 'warning',
                'service_name': 'auth-service',
            },
            'thread': 'http-nio-8071-exec-2',
            'logger': 'com.xing-cloud.auth.filter.JwtTokenFilter',
            'message': 'token will expire soon, userId=10086, expireIn=92s, clientIp=10.20.31.18',
        },
        {
            'stream': {
                'job': 'auth-service',
                'app': 'auth-service',
                'namespace': 'prod',
                'cluster': 'cn-sh-prod',
                'region': 'cn-shanghai',
                'profile': 'prod',
                'container': 'auth',
                'level': 'error',
                'service_name': 'auth-service',
            },
            'thread': 'http-nio-8071-exec-9',
            'logger': 'com.xing-cloud.auth.filter.JwtTokenFilter',
            'message': 'authentication failed, token verify error, reason=JwtException: token expired',
        },
        {
            'stream': {
                'job': 'user-service',
                'app': 'user-service',
                'namespace': 'prod',
                'cluster': 'cn-sh-prod',
                'region': 'cn-shanghai',
                'profile': 'prod',
                'container': 'user',
                'level': 'info',
                'service_name': 'user-service',
            },
            'thread': 'http-nio-8061-exec-4',
            'logger': 'com.xing-cloud.user.service.UserProfileService',
            'message': 'load user profile from redis cache, userId=10086, cacheHit=true, cost=6ms',
        },
        {
            'stream': {
                'job': 'warehouse-service',
                'app': 'warehouse-service',
                'namespace': 'prod',
                'cluster': 'cn-hz-prod',
                'region': 'cn-hangzhou',
                'profile': 'prod',
                'container': 'warehouse',
                'level': 'debug',
                'service_name': 'warehouse-service',
            },
            'thread': 'scheduling-1',
            'logger': 'com.xing-cloud.warehouse.job.StockSyncJob',
            'message': 'stock sync task finished, warehouseCode=HZ01, total=128, changed=5',
        },
        {
            'stream': {
                'job': 'user-service',
                'app': 'user-service',
                'namespace': 'prod',
                'cluster': 'cn-sh-prod',
                'region': 'cn-shanghai',
                'profile': 'prod',
                'container': 'user',
                'level': 'info',
                'service_name': 'user-service',
            },
            'thread': 'http-nio-8061-exec-8',
            'logger': 'com.xing-cloud.user.controller.UserPortalController',
            'message': 'tenant gray user routed to v2026.3-gray, tenantId=t-vip, feature=user-portrait-v2, percent=10',
        },
    ]
    timestamps = _demo_time_points(start_ms, end_ms, len(base_entries) * DEMO_LOG_BATCHES)
    entries = []
    for batch in range(DEMO_LOG_BATCHES):
        for offset, entry in enumerate(base_entries):
            current = batch * len(base_entries) + offset
            stream = dict(entry['stream'])
            stream['instance'] = f"{stream['app']}-{batch % 4 + 1:02d}"
            stream['pod'] = f"{stream['app']}-{batch + 1:02d}"
            stream['tenant_id'] = ['t-ob', 't-vip', 't-gov', 't-retail'][batch % 4]
            stream['tenant_name'] = ['欧泊郑州生产', 'VIP 会员中心', '政务专区', '零售平台'][batch % 4]
            stream['release'] = 'gray' if batch % 5 == 0 else 'stable'
            stream['lane'] = 'canary' if batch % 5 == 0 else 'default'
            stream['env'] = 'prod-gray' if batch % 5 == 0 else 'prod'
            stream['version'] = f"2026.3.{batch % 6 + 1}-{'gray' if batch % 5 == 0 else 'release'}"
            timestamp_text = datetime.fromtimestamp(timestamps[current] / 1000, tz=dt_timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            trace_id = hashlib.md5(f"{stream['app']}-{current}-{batch}".encode('utf-8')).hexdigest()[:16]
            span_id = hashlib.sha1(f"{entry['logger']}-{current}-{batch}".encode('utf-8')).hexdigest()[:8]
            entries.append({
                'timestamp_ns': int(timestamps[current] * 1_000_000),
                'message': (
                    f"{timestamp_text} {stream['level'].upper():<5} 1 --- "
                    f"[{entry['thread']}] [{stream['app']},{trace_id},{span_id}] "
                    f"{entry['logger']} : {entry['message']}"
                ),
                'attributes': {
                    'trace_id': trace_id,
                    'span_id': span_id,
                    'thread': entry['thread'],
                    'logger': entry['logger'],
                    'tenant_id': stream['tenant_id'],
                    'tenant_name': stream['tenant_name'],
                    'release': stream['release'],
                    'lane': stream['lane'],
                    'version': stream['version'],
                },
                'stream': stream,
            })
    entries.sort(key=lambda item: item['timestamp_ns'], reverse=True)
    return entries


def _parse_demo_loki_query(query):
    parsed = {'selectors': [], 'filters': []}
    if not query:
        return parsed

    selector_match = re.search(r'\{([^}]*)\}', query)
    if selector_match:
        for raw_item in selector_match.group(1).split(','):
            item = raw_item.strip()
            if not item:
                continue
            match = re.match(r'([A-Za-z_][A-Za-z0-9_]*)\s*(=~|!~|!=|=)\s*"([^"]*)"', item)
            if match:
                parsed['selectors'].append(match.groups())

    tail = query.split('}', 1)[1] if '}' in query else query
    for operator, value in re.findall(r'(\|=|\|~|!=|!~)\s*"([^"]*)"', tail):
        parsed['filters'].append((operator, value))
    return parsed


def _match_demo_loki_selector(actual, operator, expected):
    actual = str(actual or '')
    if operator == '=':
        return actual == expected
    if operator == '!=':
        return actual != expected
    if operator == '=~':
        return re.search(expected, actual) is not None
    if operator == '!~':
        return re.search(expected, actual) is None
    return True


def _match_demo_loki_filter(message, operator, expected):
    message = str(message or '')
    if operator == '|=':
        return expected.lower() in message.lower()
    if operator == '!=':
        return expected.lower() not in message.lower()
    if operator == '|~':
        return re.search(expected, message, flags=re.IGNORECASE) is not None
    if operator == '!~':
        return re.search(expected, message, flags=re.IGNORECASE) is None
    return True


def _matches_demo_loki_query(entry, query):
    parsed = _parse_demo_loki_query(query)
    for label, operator, expected in parsed['selectors']:
        if not _match_demo_loki_selector(entry.get('stream', {}).get(label), operator, expected):
            return False
    for operator, expected in parsed['filters']:
        if not _match_demo_loki_filter(entry.get('message', ''), operator, expected):
            return False

    normalized = re.sub(r'\{[^}]*\}', ' ', query or '')
    normalized = re.sub(r'(\|=|\|~|!=|!~)\s*"[^"]*"', ' ', normalized)
    extra_terms = _extract_query_terms(normalized)
    if not extra_terms:
        return True

    haystack = ' '.join([
        entry.get('message', ''),
        json.dumps(entry.get('stream', {}), ensure_ascii=False),
        json.dumps(entry.get('attributes', {}), ensure_ascii=False),
    ]).lower()
    return all(term in haystack for term in extra_terms)


def _demo_elk_documents(start_ms, end_ms):
    base_entries = [
        {
            'index': 'logs-demo-app-2026.03.15',
            'service': 'gateway-service',
            'logger': 'com.xing-cloud.gateway.filter.AccessLogFilter',
            'thread': 'reactor-http-nio-4',
            'message': 'route matched, routeId=workorder-service, path=/api/workorders/submit, cost=18ms',
            'host': 'gateway-01',
            'env': 'prod',
        },
        {
            'index': 'logs-demo-app-2026.03.15',
            'service': 'gateway-service',
            'logger': 'com.xing-cloud.gateway.filter.ExceptionLogFilter',
            'thread': 'reactor-http-nio-7',
            'message': 'forward request failed, uri=lb://workorder-service, reason=ReadTimeoutException: downstream timeout',
            'host': 'gateway-02',
            'env': 'prod',
        },
        {
            'index': 'logs-demo-app-2026.03.15',
            'service': 'workorder-service',
            'logger': 'com.xing-cloud.order.controller.OrderController',
            'thread': 'http-nio-8082-exec-3',
            'message': 'create order success, orderNo=SO202603160001, tenantId=t-ob, amount=299.00',
            'host': 'order-01',
            'env': 'prod',
        },
        {
            'index': 'logs-demo-app-2026.03.15',
            'service': 'workorder-service',
            'logger': 'com.xing-cloud.order.service.PaymentRemoteService',
            'thread': 'http-nio-8082-exec-7',
            'message': 'feign invoke quality-service failed, status=500, retry=2, msg=quality status update timeout',
            'host': 'order-02',
            'env': 'prod',
        },
        {
            'index': 'logs-demo-app-2026.03.15',
            'service': 'quality-service',
            'logger': 'com.xing-cloud.quality.controller.PaymentCallbackController',
            'thread': 'http-nio-8091-exec-12',
            'message': (
                'quality callback processing exception, requestId=cb-20260316-991, tenantId=t-ob, '
                'ex=java.lang.NullPointerException: callback payload is null\n'
                'java.lang.NullPointerException: callback payload is null\n'
                '\tat com.xing-cloud.quality.controller.PaymentCallbackController.handle(PaymentCallbackController.java:87)\n'
                '\tat com.xing-cloud.quality.controller.PaymentCallbackController.callback(PaymentCallbackController.java:52)'
            ),
            'host': 'quality-02',
            'env': 'prod',
        },
        {
            'index': 'logs-demo-app-2026.03.15',
            'service': 'quality-service',
            'logger': 'com.xing-cloud.quality.service.CallbackService',
            'thread': 'http-nio-8091-exec-5',
            'message': 'quality callback processed successfully, channel=alipay, tradeStatus=SUCCESS',
            'host': 'quality-01',
            'env': 'prod',
        },
        {
            'index': 'logs-demo-security-2026.03.15',
            'service': 'auth-service',
            'logger': 'com.xing-cloud.auth.filter.JwtTokenFilter',
            'thread': 'http-nio-8071-exec-9',
            'message': 'authentication failed, token verify error, reason=JwtException: token expired',
            'host': 'auth-01',
            'env': 'prod',
        },
        {
            'index': 'logs-demo-security-2026.03.15',
            'service': 'user-service',
            'logger': 'com.xing-cloud.user.controller.UserPortalController',
            'thread': 'http-nio-8061-exec-8',
            'message': 'tenant gray user routed to v2026.3-gray, tenantId=t-vip, feature=user-portrait-v2, percent=10',
            'host': 'user-01',
            'env': 'prod-gray',
        },
        {
            'index': 'logs-demo-security-2026.03.15',
            'service': 'warehouse-service',
            'logger': 'com.xing-cloud.warehouse.job.StockSyncJob',
            'thread': 'scheduling-1',
            'message': 'stock sync task finished, warehouseCode=HZ01, total=128, changed=5',
            'host': 'warehouse-01',
            'env': 'prod',
        },
        {
            'index': 'logs-demo-security-2026.03.15',
            'service': 'gateway-service',
            'logger': 'com.xing-cloud.gateway.filter.GrayReleaseRouteFilter',
            'thread': 'reactor-http-nio-3',
            'message': 'gray release route hit, routeId=quality-service-gray, tenantId=t-ob, version=gray, header[X-Gray]=true',
            'host': 'gateway-01',
            'env': 'prod-gray',
        },
    ]
    timestamps = _demo_time_points(start_ms, end_ms, len(base_entries) * DEMO_LOG_BATCHES)
    docs = []
    for batch in range(DEMO_LOG_BATCHES):
        for offset, entry in enumerate(base_entries):
            current = batch * len(base_entries) + offset
            level = _detect_level(entry['message'], {'level': 'error' if 'Exception' in entry['message'] or 'failed' in entry['message'] else 'info'})
            if 'gray' in entry['env'] and level == 'unknown':
                level = 'info'
            level_text = {'error': 'ERROR', 'warning': 'WARN', 'debug': 'DEBUG', 'info': 'INFO'}.get(level, 'INFO')
            trace_id = hashlib.md5(f"elk-{entry['service']}-{current}-{batch}".encode('utf-8')).hexdigest()[:16]
            span_id = hashlib.sha1(f"elk-{entry['logger']}-{current}-{batch}".encode('utf-8')).hexdigest()[:8]
            timestamp_text = datetime.fromtimestamp(timestamps[current] / 1000, tz=dt_timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            tenant_id = ['t-ob', 't-vip', 't-gov', 't-retail'][batch % 4]
            tenant_name = ['欧泊郑州生产', 'VIP 会员中心', '政务专区', '零售平台'][batch % 4]
            release = 'gray' if batch % 5 == 0 else 'stable'
            lane = 'canary' if batch % 5 == 0 else 'default'
            version = f"2026.3.{batch % 6 + 1}-{'gray' if release == 'gray' else 'release'}"
            docs.append({
                '_index': entry['index'],
                '_source': {
                    '@timestamp': _iso_from_ms(timestamps[current]),
                    'message': (
                        f"{timestamp_text} {level_text:<5} 1 --- "
                        f"[{entry['thread']}] [{entry['service']},{trace_id},{span_id}] "
                        f"{entry['logger']} : {entry['message']}"
                    ),
                    'level': level_text,
                    'service': {'name': entry['service']},
                    'host': {'name': entry['host']},
                    'env': entry['env'],
                    'trace_id': trace_id,
                    'span_id': span_id,
                    'thread_name': entry['thread'],
                    'logger_name': entry['logger'],
                    'tenant_id': tenant_id,
                    'tenant_name': tenant_name,
                    'release': release,
                    'lane': lane,
                    'version': version,
                    'kubernetes': {
                        'namespace': 'prod',
                        'container_name': entry['service'].replace('-service', ''),
                        'pod_name': f"{entry['service']}-{batch + 1:02d}",
                    },
                },
            })
    docs.sort(key=lambda item: item['_source']['@timestamp'], reverse=True)
    return docs


def _loki_request(endpoint, path, params):
    url = f'{_normalize_endpoint(endpoint)}{path}'
    try:
        response = http_requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except http_requests.Timeout as exc:
        raise ProviderError('Loki request timed out', status.HTTP_504_GATEWAY_TIMEOUT, {'detail': str(exc)}) from exc
    except http_requests.ConnectionError as exc:
        raise ProviderError('Unable to connect to Loki', status.HTTP_502_BAD_GATEWAY, {'detail': str(exc)}) from exc
    _raise_for_status(response, 'Loki')
    return _safe_json(response)


def _elk_auth_headers(config):
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    auth = None
    auth_type = config.get('auth_type', 'none')
    if auth_type == 'basic':
        auth = (config.get('username', ''), config.get('password', ''))
    elif auth_type == 'api_key' and config.get('api_key'):
        headers['Authorization'] = f'ApiKey {config["api_key"]}'
    elif auth_type == 'bearer' and config.get('bearer_token'):
        headers['Authorization'] = f'Bearer {config["bearer_token"]}'
    return headers, auth


def _elk_request(method, endpoint, path, config, params=None, body=None):
    url = f'{_normalize_endpoint(endpoint)}{path}'
    headers, auth = _elk_auth_headers(config)
    try:
        response = http_requests.request(
            method,
            url,
            params=params,
            json=body,
            headers=headers,
            auth=auth,
            timeout=REQUEST_TIMEOUT,
        )
    except http_requests.Timeout as exc:
        raise ProviderError('ELK request timed out', status.HTTP_504_GATEWAY_TIMEOUT, {'detail': str(exc)}) from exc
    except http_requests.ConnectionError as exc:
        raise ProviderError('Unable to connect to ELK', status.HTTP_502_BAD_GATEWAY, {'detail': str(exc)}) from exc
    _raise_for_status(response, 'ELK')
    return _safe_json(response)


def _clickhouse_identifier(value, label='identifier'):
    value = str(value or '').strip()
    if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', value):
        raise ProviderError(f'Invalid ClickHouse {label}: {value}')
    return f'`{value}`'


def _clickhouse_literal(value):
    escaped = str(value or '').replace('\\', '\\\\').replace("'", "\\'")
    return f"'{escaped}'"


def _clickhouse_json_query(sql):
    if re.search(r'\bFORMAT\s+JSON\b', sql, flags=re.IGNORECASE):
        return sql
    if re.search(r'\bFORMAT\b', sql, flags=re.IGNORECASE):
        return sql
    return f'{sql.rstrip()} FORMAT JSON'


def _clickhouse_request(config, sql):
    endpoint = config.get('endpoint')
    if not endpoint:
        raise ProviderError('ClickHouse endpoint is required')
    auth = None
    username = config.get('username', '')
    password = config.get('password', '')
    if username or password:
        auth = (username, password)
    try:
        response = http_requests.request(
            'POST',
            _normalize_endpoint(endpoint),
            data=_clickhouse_json_query(sql),
            headers={'Accept': 'application/json', 'Content-Type': 'text/plain; charset=utf-8'},
            auth=auth,
            timeout=REQUEST_TIMEOUT,
        )
    except http_requests.Timeout as exc:
        raise ProviderError('ClickHouse request timed out', status.HTTP_504_GATEWAY_TIMEOUT, {'detail': str(exc)}) from exc
    except http_requests.ConnectionError as exc:
        raise ProviderError('Unable to connect to ClickHouse', status.HTTP_502_BAD_GATEWAY, {'detail': str(exc)}) from exc
    _raise_for_status(response, 'ClickHouse')
    return _safe_json(response)


def _clickhouse_data_rows(response):
    if isinstance(response, dict):
        return response.get('data') or []
    return response if isinstance(response, list) else []


def _clickhouse_collection_key(database, table):
    raw = f'{database}-{table}'.lower()
    return re.sub(r'[^a-z0-9]+', '-', raw).strip('-') or 'clickhouse-logs'


def _normalize_clickhouse_collection(item):
    if not isinstance(item, dict):
        return None
    database = str(item.get('database') or '').strip()
    table = str(item.get('table') or '').strip()
    if not database or not table:
        return None
    key = str(item.get('key') or item.get('id') or _clickhouse_collection_key(database, table)).strip()
    name = str(item.get('name') or f'{database}.{table}').strip()
    return {
        'key': key,
        'name': name,
        'database': database,
        'table': table,
        'time_field': str(item.get('time_field') or 'timestamp').strip(),
        'timezone': str(item.get('timezone') or '').strip(),
        'message_fields': item.get('message_fields') or '',
        'level_field': str(item.get('level_field') or '').strip(),
        'source_fields': item.get('source_fields') or '',
        'search_fields': item.get('search_fields') or '',
    }


def _clickhouse_collections(config):
    raw_items = config.get('collections')
    if raw_items is None and config.get('database') and config.get('table'):
        raw_items = [{
            'key': config.get('collection') or config.get('collection_key') or _clickhouse_collection_key(config.get('database'), config.get('table')),
            'name': config.get('collection_name') or f'{config.get("database")}.{config.get("table")}',
            'database': config.get('database'),
            'table': config.get('table'),
            'time_field': config.get('time_field') or 'timestamp',
            'timezone': config.get('timezone') or '',
            'message_fields': config.get('message_fields') or '',
            'level_field': config.get('level_field') or '',
            'source_fields': config.get('source_fields') or '',
            'search_fields': config.get('search_fields') or '',
        }]
    collections = []
    for item in raw_items or []:
        normalized = _normalize_clickhouse_collection(item)
        if normalized:
            collections.append(normalized)
    return collections


def _resolve_clickhouse_collection(config, payload):
    collection_id = str(payload.get('collection') or payload.get('collection_key') or '').strip()
    collections = _clickhouse_collections(config)
    if collection_id:
        for item in collections:
            if collection_id in {item.get('key'), item.get('name'), f"{item.get('database')}.{item.get('table')}", item.get('table')}:
                return item
        raise ProviderError('ClickHouse collection is not configured')

    source = str(payload.get('source') or payload.get('table') or '').strip()
    database = str(payload.get('database') or '').strip()
    if source:
        if '.' in source:
            database, source = source.split('.', 1)
        for item in collections:
            if source in {item.get('key'), item.get('name'), item.get('table')} and (not database or database == item.get('database')):
                return item
        if not database:
            database = str(config.get('database') or '').strip()
        if database:
            return _normalize_clickhouse_collection({
                'database': database,
                'table': source,
                'time_field': payload.get('time_field') or config.get('time_field') or 'timestamp',
                'timezone': payload.get('timezone') or config.get('timezone') or '',
                'message_fields': payload.get('message_fields') or config.get('message_fields') or '',
                'level_field': payload.get('level_field') or config.get('level_field') or '',
                'source_fields': payload.get('source_fields') or config.get('source_fields') or '',
                'search_fields': payload.get('search_fields') or config.get('search_fields') or '',
            })

    if collections:
        return collections[0]

    database = str(payload.get('database') or config.get('database') or '').strip()
    table = str(payload.get('table') or config.get('table') or '').strip()
    if database and table:
        return _normalize_clickhouse_collection({
            'database': database,
            'table': table,
            'time_field': payload.get('time_field') or config.get('time_field') or 'timestamp',
            'timezone': payload.get('timezone') or config.get('timezone') or '',
            'message_fields': payload.get('message_fields') or config.get('message_fields') or '',
            'level_field': payload.get('level_field') or config.get('level_field') or '',
            'source_fields': payload.get('source_fields') or config.get('source_fields') or '',
            'search_fields': payload.get('search_fields') or config.get('search_fields') or '',
        })
    raise ProviderError('ClickHouse collection is required')


def _clickhouse_table_parts(config, payload):
    collection = _resolve_clickhouse_collection(config, payload)
    database = collection['database']
    table = collection['table']
    return database, table, f'{_clickhouse_identifier(database, "database")}.{_clickhouse_identifier(table, "table")}'


def _clickhouse_time_expression(value, timezone_name):
    return f'fromUnixTimestamp64Milli({int(value)}, {_clickhouse_literal(timezone_name or "Asia/Shanghai")})'


def _clickhouse_search_condition(query, search_fields):
    terms = _extract_query_terms(query)
    if not terms:
        return ''
    fields = _split_fields(search_fields, CLICKHOUSE_DEFAULT_SEARCH_FIELDS)
    field_exprs = [_clickhouse_identifier(field, 'field') for field in fields]
    clauses = []
    for term in terms:
        literal = _clickhouse_literal(term)
        clauses.append('(' + ' OR '.join(
            f'positionCaseInsensitive(toString({field}), {literal}) > 0'
            for field in field_exprs
        ) + ')')
    return ' AND '.join(clauses)


def _normalize_clickhouse_levels(payload):
    levels = payload.get('levels')
    if levels in (None, ''):
        levels = payload.get('level') or payload.get('log_level')
    if isinstance(levels, str):
        levels = [item.strip() for item in levels.split(',')]
    elif not isinstance(levels, (list, tuple, set)):
        levels = [levels] if levels not in (None, '') else []
    normalized = []
    for item in levels:
        text = str(item or '').strip()
        if text and text.lower() not in {'*', 'all', 'any'}:
            normalized.append(text.upper())
    return normalized


def _clickhouse_numeric_filter(value, field, operator):
    if value is None or str(value).strip() == '':
        return ''
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ''
    return f'{field} {operator} {number}'


def _clickhouse_recommend_fields(columns):
    column_map = {item.get('name'): item for item in columns if item.get('name')}
    names = list(column_map.keys())

    def first_present(candidates, type_contains=''):
        for name in candidates:
            if name not in column_map:
                continue
            if type_contains and type_contains.lower() not in str(column_map[name].get('type', '')).lower():
                continue
            return name
        return ''

    def present_many(candidates, limit=3):
        return [name for name in candidates if name in column_map][:limit]

    string_fields = [
        name for name, item in column_map.items()
        if 'string' in str(item.get('type', '')).lower()
    ]
    time_field = first_present(
        ['timestamp', '@timestamp', 'time', 'createdtime', 'created_at', 'last_timestamp', 'first_timestamp'],
        'datetime',
    ) or first_present(['timestamp', '@timestamp', 'time', 'createdtime', 'created_at', 'last_timestamp', 'first_timestamp'])
    message_fields = present_many(
        ['message', 'log_message', 'msg', 'content', '__content__', 'body', 'raw_log', 'log'],
        limit=2,
    )
    level_field = first_present(['log_level', 'level', 'severity', 'severity_text', 'event_type', 'status'])
    source_fields = present_many(
        ['namespace', 'pod_name', 'container_name', 'domain', 'server_ip', 'client_ip', 'source_component', 'source_host', 'node_name', 'source', 'host', 'service'],
        limit=3,
    )
    search_fields = [
        name for name in names
        if name in string_fields or name in {'status', 'count'}
    ]
    return {
        'time_field': time_field or 'timestamp',
        'message_fields': ','.join(message_fields),
        'level_field': level_field,
        'source_fields': ','.join(source_fields),
        'search_fields': ','.join(search_fields),
    }


def _catalog_clickhouse(config, payload):
    action = payload.get('action') or 'tables'
    if action == 'collections':
        return {'kind': 'collections', 'items': _clickhouse_collections(config)}

    if action == 'databases':
        data = _clickhouse_request(config, 'SHOW DATABASES')
        return {'kind': 'databases', 'items': [{'name': row.get('name')} for row in _clickhouse_data_rows(data) if row.get('name')]}

    if action in {'tables', 'sources'}:
        database = payload.get('database') or config.get('database') or 'default'
        data = _clickhouse_request(config, f'SHOW TABLES FROM {_clickhouse_identifier(database, "database")}')
        return {'kind': 'tables', 'items': [{'name': row.get('name')} for row in _clickhouse_data_rows(data) if row.get('name')]}

    if action == 'columns':
        _, _, table_ref = _clickhouse_table_parts(config, payload)
        data = _clickhouse_request(config, f'DESCRIBE TABLE {table_ref}')
        items = [
            {'name': row.get('name'), 'type': row.get('type') or row.get('default_type') or ''}
            for row in _clickhouse_data_rows(data)
            if row.get('name')
        ]
        return {'kind': 'columns', 'items': items}

    if action == 'recommend_fields':
        _, _, table_ref = _clickhouse_table_parts(config, payload)
        data = _clickhouse_request(config, f'DESCRIBE TABLE {table_ref}')
        columns = [
            {'name': row.get('name'), 'type': row.get('type') or row.get('default_type') or ''}
            for row in _clickhouse_data_rows(data)
            if row.get('name')
        ]
        return {
            'kind': 'field_recommendation',
            'columns': columns,
            'recommendation': _clickhouse_recommend_fields(columns),
        }

    raise ProviderError('Unsupported ClickHouse catalog action')


def _clickhouse_status_level(status_value):
    try:
        status_code = int(status_value)
    except (TypeError, ValueError):
        return ''
    if status_code >= 500:
        return 'error'
    if status_code >= 400:
        return 'warning'
    return 'info'


def _clickhouse_duration_ms(row):
    for key in ('responsetime', 'duration', 'upstreamtime'):
        value = row.get(key)
        if value in (None, ''):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number < 100:
            number *= 1000
        return int(round(number))
    return None


def _clickhouse_source(row, source_fields, fallback):
    values = []
    for field in _split_fields(source_fields, []):
        value = row.get(field)
        if value not in (None, ''):
            values.append(str(value))
    if values:
        return '/'.join(values)
    return row.get('domain') or row.get('server_ip') or row.get('client_ip') or row.get('pod_name') or fallback


def _clickhouse_level(row, level_field):
    raw_level = row.get(level_field) if level_field else None
    normalized = _normalize_level(raw_level)
    if normalized:
        return normalized
    if str(raw_level or '').strip().lower() in {'normal', 'success', 'succeeded'}:
        return 'info'
    if level_field == 'status' or row.get('status') not in (None, ''):
        status_level = _clickhouse_status_level(row.get(level_field) if level_field else row.get('status'))
        if status_level:
            return status_level
    return ''


def _clickhouse_message(row, message_fields=None):
    message = _pick_message(row, _split_fields(message_fields, []))
    if message_fields and message:
        return message
    method = row.get('request_method') or ''
    domain = row.get('domain') or row.get('server_ip') or ''
    path = row.get('path') or row.get('top_path') or ''
    query = row.get('query') or ''
    status_code = row.get('status')
    target = path
    if query and '?' not in target:
        target = f'{target}?{query}' if target else f'?{query}'
    if domain:
        target = f'{domain}{target}' if target.startswith('/') else f'{domain} {target}'.strip()
    parts = [str(item) for item in (method, target, status_code) if item not in (None, '')]
    duration = _clickhouse_duration_ms(row)
    if duration is not None:
        parts.append(f'{duration}ms')
    return ' '.join(parts) or json.dumps(row, ensure_ascii=False)


def _normalize_clickhouse_row(row, collection):
    message = _clickhouse_message(row, collection.get('message_fields'))
    level = _clickhouse_level(row, collection.get('level_field')) or _detect_level(message, row)
    attributes = dict(row)
    attributes['_database'] = collection.get('database')
    attributes['_table'] = collection.get('table')
    attributes['_collection'] = collection.get('key')
    timestamp_value = row.get(collection.get('time_field')) if collection.get('time_field') else None
    namespace = row.get('namespace') or row.get('namespace_name') or ''
    pod = row.get('pod') or row.get('pod_name') or ''
    container = row.get('container') or row.get('container_name') or ''
    host = row.get('host') or row.get('node') or row.get('node_name') or ''
    service = row.get('service') or row.get('service_name') or row.get('app') or namespace or collection.get('table')
    return {
        'timestamp': _iso_from_ms(timestamp_value or row.get('timestamp') or row.get('createdtime')) if (timestamp_value or row.get('timestamp') or row.get('createdtime')) else '',
        'message': message,
        'level': level,
        'source': _clickhouse_source(row, collection.get('source_fields'), collection.get('table')),
        'service': str(service or ''),
        'namespace': str(namespace or ''),
        'pod': str(pod or ''),
        'container': str(container or ''),
        'host': str(host or ''),
        'attributes': _with_trace_id(attributes, message),
    }


def _query_clickhouse(config, payload):
    collection = _resolve_clickhouse_collection(config, payload)
    database = collection['database']
    table = collection['table']
    table_ref = f'{_clickhouse_identifier(database, "database")}.{_clickhouse_identifier(table, "table")}'
    time_field = payload.get('time_field') or collection.get('time_field') or config.get('time_field') or 'timestamp'
    timezone_name = payload.get('timezone') or collection.get('timezone') or config.get('timezone') or 'Asia/Shanghai'
    query = (payload.get('query') or '').strip() or '*'
    start_ms, end_ms = _time_bounds(payload)
    time_identifier = _clickhouse_identifier(time_field, 'time field')
    conditions = [
        f'{time_identifier} >= {_clickhouse_time_expression(start_ms, timezone_name)}',
        f'{time_identifier} <= {_clickhouse_time_expression(end_ms, timezone_name)}',
    ]
    search_condition = _clickhouse_search_condition(query, payload.get('search_fields') or collection.get('search_fields') or config.get('search_fields'))
    if search_condition:
        conditions.append(search_condition)
    level_field = payload.get('level_field') or collection.get('level_field') or config.get('level_field') or ''
    if level_field:
        level_identifier = _clickhouse_identifier(level_field, 'level field')
        levels = _normalize_clickhouse_levels(payload)
        if levels:
            level_values = ','.join(_clickhouse_literal(item) for item in levels)
            conditions.append(f'upper(toString({level_identifier})) IN ({level_values})')
        status_min_filter = _clickhouse_numeric_filter(payload.get('status_min'), level_identifier, '>=')
        if status_min_filter:
            conditions.append(status_min_filter)
        status_max_filter = _clickhouse_numeric_filter(payload.get('status_max'), level_identifier, '<=')
        if status_max_filter:
            conditions.append(status_max_filter)

    limit = _sanitize_limit(payload.get('limit'))
    sql = (
        f'SELECT * FROM {table_ref} '
        f'WHERE {" AND ".join(conditions)} '
        f'ORDER BY {time_identifier} DESC '
        f'LIMIT {limit}'
    )
    response = _clickhouse_request(config, sql)
    rows = _clickhouse_data_rows(response)
    logs = [_normalize_clickhouse_row(row, collection) for row in rows if isinstance(row, dict)]
    statistics = response.get('statistics', {}) if isinstance(response, dict) else {}
    elapsed = statistics.get('elapsed')
    took_ms = int(float(elapsed) * 1000) if elapsed not in (None, '') else None
    total = response.get('rows_before_limit_at_least') if isinstance(response, dict) else None
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = len(logs)
    return {
        'provider': 'clickhouse',
        'query': query,
        'source': f'{database}.{table}',
        'collection': collection.get('key'),
        'collection_name': collection.get('name'),
        'total': total,
        'took_ms': took_ms,
        'logs': logs,
    }


def _catalog_loki(config, payload):
    start_ms, end_ms = _time_bounds(payload)
    action = payload.get('action', 'labels')
    if _is_demo_config(config):
        entries = _demo_loki_entries(start_ms, end_ms)
        if action == 'label_values':
            label = payload.get('label')
            if not label:
                raise ProviderError('label is required for Loki label values')
            values = sorted({item['stream'].get(label) for item in entries if item['stream'].get(label) not in (None, '')})
            return {'kind': 'label_values', 'items': values}

        labels = sorted({key for item in entries for key in item.get('stream', {}).keys()})
        return {'kind': 'labels', 'items': labels}

    params = {
        'start': str(start_ms * 1_000_000),
        'end': str(end_ms * 1_000_000),
    }
    if action == 'label_values':
        label = payload.get('label')
        if not label:
            raise ProviderError('label is required for Loki label values')
        data = _loki_request(config['endpoint'], f'/loki/api/v1/label/{label}/values', params)
        return {'kind': 'label_values', 'items': data.get('data', [])}
    data = _loki_request(config['endpoint'], '/loki/api/v1/labels', params)
    return {'kind': 'labels', 'items': data.get('data', [])}


def _catalog_elk(config, payload):
    if _is_demo_config(config):
        names = config.get('demo_indices') or ['logs-demo-app-2026.03.15', 'logs-demo-security-2026.03.15']
        return {
            'kind': 'indices',
            'items': [{'name': name, 'docs_count': '1280', 'store_size': '12mb'} for name in names],
        }

    if not config.get('endpoint'):
        raise ProviderError('ELK endpoint is required')
    pattern = payload.get('index_pattern') or config.get('index_pattern') or '*'
    if payload.get('action') == 'recommend_fields':
        sample = _elk_request(
            'POST', config.get('endpoint', ''), f'/{pattern}/_search', config,
            body={'size': 1, 'sort': [{'@timestamp': {'order': 'desc', 'unmapped_type': 'date'}}], 'query': {'match_all': {}}},
        )
        hit = ((sample.get('hits') or {}).get('hits') or [{}])[0]
        fields = sorted(_flatten_elk_fields(hit.get('_source') or {}).keys())
        return {
            'kind': 'field_recommendation',
            'items': fields,
            'recommendation': _recommend_elk_field_map(fields),
        }
    data = _elk_request('GET', config.get('endpoint', ''), f'/_cat/indices/{pattern}', config, params={'format': 'json'})
    items = []
    for row in data:
        index_name = row.get('index')
        if index_name:
            items.append({
                'name': index_name,
                'docs_count': row.get('docs.count'),
                'store_size': row.get('store.size'),
            })
    return {'kind': 'indices', 'items': items}


GENERIC_ELK_FIELD_MAP = {
    'timestamp': '@timestamp',
    'message': 'message',
    'level': 'log.level',
    'service': 'service.name',
    'namespace': 'namespace',
    'pod': 'pod',
    'container': 'container',
    'host': 'host.name',
}


K8S_ELK_FIELD_MAP = {
    'timestamp': '@timestamp',
    'message': 'message',
    'level': 'log.level',
    'service': 'kubernetes.labels.app',
    'namespace': 'kubernetes.namespace_name',
    'pod': 'kubernetes.pod_name',
    'container': 'kubernetes.container_name',
    'host': 'kubernetes.node_name',
}


def _flatten_elk_fields(value, prefix=''):
    fields = {}
    if not isinstance(value, dict):
        return fields
    for key, item in value.items():
        path = f'{prefix}.{key}' if prefix else str(key)
        if isinstance(item, dict):
            fields.update(_flatten_elk_fields(item, path))
        else:
            fields[path] = True
    return fields


def _recommend_elk_field_map(fields):
    available = set(fields or [])
    alternatives = {
        'timestamp': ['@timestamp', 'timestamp', 'time', 'event.created'],
        'message': ['message', 'log', 'log.message', 'msg'],
        'level': ['log.level', 'level', 'severity'],
        'service': ['service.name', 'kubernetes.labels.app.kubernetes.io/name', 'kubernetes.labels.app', 'kubernetes.container_name'],
        'namespace': ['kubernetes.namespace_name', 'namespace'],
        'pod': ['kubernetes.pod_name', 'pod'],
        'container': ['kubernetes.container_name', 'container'],
        'host': ['kubernetes.node_name', 'host.name', 'host'],
    }
    return {
        key: next((candidate for candidate in candidates if candidate in available), '')
        for key, candidates in alternatives.items()
    }


def _elk_field_value(source, field):
    field = str(field or '').strip()
    if not field:
        return None
    return source.get(field) if field in source else _get_nested(source, field)


def _resolve_elk_collection(config, payload):
    collections = config.get('collections') if isinstance(config.get('collections'), list) else []
    selected_key = payload.get('collection') or config.get('default_collection')
    selected = next((item for item in collections if isinstance(item, dict) and item.get('key') == selected_key), None)
    selected = selected or {}
    index_pattern = selected.get('index_pattern') or config.get('index_pattern') or 'k8s-*'
    field_map = dict(K8S_ELK_FIELD_MAP if str(index_pattern).startswith('k8s-') else GENERIC_ELK_FIELD_MAP)
    if isinstance(config.get('field_map'), dict):
        field_map.update({key: value for key, value in config['field_map'].items() if value})
    if isinstance(selected.get('field_map'), dict):
        field_map.update({key: value for key, value in selected['field_map'].items() if value})
    return {
        'index_pattern': index_pattern,
        'field_map': field_map,
    }


def _query_loki(config, payload):
    query = (payload.get('query') or '').strip()
    if not query:
        raise ProviderError('Loki query is required')
    start_ms, end_ms = _time_bounds(payload)

    if _is_demo_config(config):
        matched_logs = []
        for entry in _demo_loki_entries(start_ms, end_ms):
            if not _matches_demo_loki_query(entry, query):
                continue
            attributes = _with_trace_id({**entry['stream'], **entry.get('attributes', {})}, entry['message'])
            matched_logs.append({
                'timestamp': _iso_from_ns(entry['timestamp_ns']),
                'message': entry['message'],
                'level': _detect_level(entry['message'], entry['stream']),
                'source': entry['stream'].get('job') or entry['stream'].get('app') or 'loki',
                'attributes': attributes,
            })
        return {
            'provider': 'loki',
            'query': query,
            'source': 'LogQL',
            'total': len(matched_logs),
            'took_ms': 8,
            'logs': matched_logs[:_sanitize_limit(payload.get('limit'))],
        }

    params = {
        'query': query,
        'start': str(start_ms * 1_000_000),
        'end': str(end_ms * 1_000_000),
        'limit': _sanitize_limit(payload.get('limit')),
        'direction': payload.get('direction') or 'backward',
    }
    response = _loki_request(config['endpoint'], '/loki/api/v1/query_range', params)
    streams = response.get('data', {}).get('result', [])
    logs = []
    for stream in streams:
        labels = stream.get('stream', {})
        for timestamp, message in stream.get('values', []):
            attributes = _with_trace_id(labels, message)
            logs.append({
                'sort_key': int(timestamp),
                'timestamp': _iso_from_ns(timestamp),
                'message': message,
                'level': _detect_level(message, labels),
                'source': labels.get('job') or labels.get('app') or labels.get('service_name') or 'loki',
                'attributes': attributes,
            })
    logs.sort(key=lambda item: item['sort_key'], reverse=True)
    for item in logs:
        item.pop('sort_key', None)
    return {
        'provider': 'loki',
        'query': query,
        'source': 'LogQL',
        'total': len(logs),
        'took_ms': None,
        'logs': logs,
    }


def _query_elk(config, payload):
    collection = _resolve_elk_collection(config, payload)
    field_map = collection['field_map']
    index_pattern = payload.get('source') or payload.get('index_pattern') or collection['index_pattern']
    time_field = payload.get('time_field') or field_map.get('timestamp') or config.get('time_field') or '@timestamp'
    message_fields = _split_fields(field_map.get('message') or payload.get('message_fields') or config.get('message_fields'), ['message', 'log', 'msg'])
    query = (payload.get('query') or '').strip()
    start_ms, end_ms = _time_bounds(payload)

    if _is_demo_config(config):
        docs = []
        index_prefix = index_pattern.replace('*', '') if '*' in index_pattern else index_pattern
        for hit in _demo_elk_documents(start_ms, end_ms):
            if index_pattern not in ('*', hit['_index']) and not hit['_index'].startswith(index_prefix):
                continue
            if _matches_demo_query(hit['_source'].get('message', ''), hit['_source'], query):
                docs.append(hit)
        response = {
            'took': 12,
            'hits': {
                'total': {'value': len(docs)},
                'hits': docs[:_sanitize_limit(payload.get('limit'))],
            },
        }
    else:
        endpoint = config.get('endpoint')
        if not endpoint:
            raise ProviderError('ELK endpoint is required')

        body = {
            'size': _sanitize_limit(payload.get('limit')),
            'track_total_hits': True,
            'sort': [{time_field: {'order': 'desc', 'unmapped_type': 'date'}}],
            'query': {
                'bool': {
                    'filter': [{
                        'range': {
                            time_field: {
                                'gte': _iso_from_ms(start_ms),
                                'lte': _iso_from_ms(end_ms),
                                'format': 'strict_date_optional_time',
                            }
                        }
                    }],
                    'must': [{'match_all': {}}] if not query else [{
                        'query_string': {
                            'query': query,
                            'default_operator': 'AND',
                        }
                    }],
                }
            },
        }
        response = _elk_request('POST', endpoint, f'/{index_pattern}/_search', config, body=body)

    hits = response.get('hits', {}).get('hits', [])
    total = response.get('hits', {}).get('total', {})
    total_value = total.get('value') if isinstance(total, dict) else len(hits)
    logs = []
    for hit in hits:
        source = hit.get('_source') or {}
        timestamp = _get_nested(source, time_field) or hit.get('sort', [None])[0]
        attributes = dict(source)
        attributes['_index'] = hit.get('_index')
        namespace = _elk_field_value(source, field_map.get('namespace'))
        pod = _elk_field_value(source, field_map.get('pod'))
        container = _elk_field_value(source, field_map.get('container'))
        host = _elk_field_value(source, field_map.get('host'))
        raw_service = _elk_field_value(source, field_map.get('service'))
        service = (
            (raw_service if isinstance(raw_service, (str, int, float)) else '')
            or namespace
            or hit.get('_index')
        )
        message = _pick_message(source, message_fields)
        logs.append({
            'timestamp': _iso_from_ms(timestamp) if timestamp else '',
            'message': message,
            'level': _detect_level(_elk_field_value(source, field_map.get('level')) or '', source) if source else 'unknown',
            'source': str(service or hit.get('_index') or 'elasticsearch'),
            'service': str(service or ''),
            'namespace': str(namespace or ''),
            'pod': str(pod or ''),
            'container': str(container or ''),
            'host': str(host or ''),
            'attributes': _with_trace_id(attributes, message),
        })
        if logs[-1]['level'] == 'unknown':
            logs[-1]['level'] = _detect_level(logs[-1]['message'], source)

    return {
        'provider': 'elk',
        'query': query,
        'source': index_pattern,
        'total': total_value if total_value is not None else len(logs),
        'took_ms': response.get('took'),
        'logs': logs,
    }


def _get_catalog(provider, config, payload):
    if provider == 'loki':
        return _catalog_loki(config, payload)
    if provider == 'elk':
        return _catalog_elk(config, payload)
    if provider == 'clickhouse':
        return _catalog_clickhouse(config, payload)
    raise ProviderError('Unsupported log provider')


def _run_query(provider, config, payload):
    if provider == 'loki':
        return _query_loki(config, payload)
    if provider == 'elk':
        return _query_elk(config, payload)
    if provider == 'clickhouse':
        return _query_clickhouse(config, payload)
    raise ProviderError('Unsupported log provider')


def _error_response(exc):
    return Response({'error': str(exc), 'detail': exc.detail}, status=exc.status_code)


class LogDataSourceViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = LogDataSource.objects.all().order_by('provider', 'name')
    serializer_class = LogDataSourceSerializer
    pagination_class = None
    event_module = 'ops'
    event_resource_type = 'log_datasource'
    event_resource_label = '日志数据源'
    event_resource_name_fields = ('name',)
    event_exclude_fields = ('config',)
    rbac_permissions = {
        'list': ['ops.log.datasource.view'],
        'retrieve': ['ops.log.datasource.view'],
        'create': ['ops.log.datasource.manage'],
        'update': ['ops.log.datasource.manage'],
        'partial_update': ['ops.log.datasource.manage'],
        'destroy': ['ops.log.datasource.manage'],
        'test_connection': ['ops.log.datasource.manage'],
    }

    def get_queryset(self):
        queryset = super().get_queryset().prefetch_related('aiops_knowledge_environments')
        provider = self.request.query_params.get('provider')
        is_enabled = self.request.query_params.get('is_enabled')

        if provider:
            queryset = queryset.filter(provider=provider)
        if is_enabled in ('true', 'false'):
            queryset = queryset.filter(is_enabled=is_enabled == 'true')
        return queryset

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        datasource = self.get_object()
        try:
            if datasource.provider == 'loki':
                payload = {'action': 'labels'}
            elif datasource.provider == 'clickhouse':
                payload = {'action': 'databases'}
            else:
                payload = {'action': 'sources'}
            preview = _get_catalog(datasource.provider, _merge_config(datasource.provider, datasource.config), payload)
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_log_datasource',
                title='测试日志数据源连通性',
                summary=f'日志数据源 {datasource.name} 连通性测试成功',
                resource_type='log_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'log-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'preview_kind': preview.get('kind')},
            )
            return Response({
                'success': True,
                'message': f'{datasource.name} 连接成功',
                'preview_count': len(preview.get('items', [])),
                'preview_kind': preview.get('kind'),
            })
        except ProviderError as exc:
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_log_datasource',
                title='测试日志数据源连通性',
                summary=f'日志数据源 {datasource.name} 连通性测试失败',
                result=EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING,
                resource_type='log_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'log-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'error': str(exc)},
            )
            return Response({'success': False, 'message': str(exc), 'detail': exc.detail}, status=exc.status_code)
        except Exception as exc:
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_log_datasource',
                title='测试日志数据源连通性',
                summary=f'日志数据源 {datasource.name} 连通性测试失败',
                result=EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING,
                resource_type='log_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'log-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'error': str(exc)},
            )
            return Response(
                {'success': False, 'message': '连接测试失败', 'detail': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.log.datasource.view')])
def log_providers(request):
    return Response({'providers': _provider_info()})


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.log.query', allow_demo_write=True)])
def log_provider_catalog(request, provider):
    try:
        resolved_provider, config, _ = _resolve_provider_and_config({**request.data, 'provider': provider})
        if resolved_provider != provider:
            raise ProviderError('provider 与数据源类型不一致')
        return Response(_get_catalog(provider, config, request.data))
    except ProviderError as exc:
        return _error_response(exc)
    except Exception as exc:
        return Response(
            {'error': 'Unexpected log catalog failure', 'detail': str(exc)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.log.query', allow_demo_write=True)])
def log_query(request):
    try:
        provider, config, datasource = _resolve_provider_and_config(request.data)
        payload = dict(request.data)
        return Response(_run_query(provider, config, payload))
    except ProviderError as exc:
        return _error_response(exc)
    except Exception as exc:
        return Response(
            {'error': 'Unexpected log query failure', 'detail': str(exc)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
