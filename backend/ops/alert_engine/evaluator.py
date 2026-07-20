import time

from django.utils import timezone

from ops.log_views import (
    _clickhouse_data_rows,
    _clickhouse_identifier,
    _clickhouse_request,
    _merge_config,
    _resolve_clickhouse_collection,
)
from ops.models import AlertRule, LogDataSource
from ops.observability_views import execute_promql_query
from ops.sla import build_sla_summary

from .evidence import result_evidence
from .pipeline import mark_rule_error, process_rule_results


def _dict(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    if isinstance(value, (int, float)):
        return float(value)
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_prom_value(item):
    value = item.get('value') if isinstance(item, dict) else None
    values = item.get('values') if isinstance(item, dict) else None
    point = values[-1] if values else value
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return _number(point[1])
    return _number(point)


def _compare(value, condition):
    value = _number(value)
    if value is None:
        return False
    operator = str(condition.get('operator') or condition.get('op') or '>').strip()
    threshold = _number(condition.get('threshold') if condition.get('threshold') is not None else condition.get('value'))
    if threshold is None:
        threshold = 0
    if operator in {'>', 'gt'}:
        return value > threshold
    if operator in {'>=', 'gte'}:
        return value >= threshold
    if operator in {'<', 'lt'}:
        return value < threshold
    if operator in {'<=', 'lte'}:
        return value <= threshold
    if operator in {'==', '=', 'eq'}:
        return value == threshold
    if operator in {'!=', '<>', 'ne'}:
        return value != threshold
    return value > threshold


def _apply_condition_levels(rule, results):
    condition = _dict(rule.condition)
    levels = condition.get('levels')
    if not isinstance(levels, list):
        return results

    priority = {'critical': 3, 'warning': 2, 'info': 1}
    for result in results:
        matched_levels = [
            level for level in levels
            if isinstance(level, dict) and _compare(result.get('value'), level)
        ]
        selected = max(matched_levels, key=lambda item: priority.get(item.get('level'), 0), default=None)
        result['matched'] = selected is not None
        if selected:
            result['level'] = selected.get('level') or rule.level
            result['duration_seconds'] = selected.get('duration_seconds', rule.duration_seconds)
            result['title'] = result.get('title') or rule.name
    return results


def _labels(rule, extra=None):
    labels = {}
    labels.update(_dict(rule.labels))
    labels.update(_dict(extra))
    return {str(key): value for key, value in labels.items() if value not in (None, '')}


def _prometheus_results(rule):
    query_config = _dict(rule.query_config)
    condition = _dict(rule.condition)
    query = str(query_config.get('promql') or query_config.get('query') or query_config.get('metric') or '').strip()
    if not rule.metric_datasource_id:
        raise ValueError('Prometheus 规则尚未绑定指标数据源')
    if not rule.metric_datasource or not rule.metric_datasource.is_enabled:
        raise ValueError('Prometheus 规则绑定的指标数据源已停用或不存在')
    rule_labels = _dict(rule.labels)
    payload = execute_promql_query(
        query,
        range_query=False,
        metric_datasource_id=rule.metric_datasource_id,
        environment=rule.metric_datasource.environment or query_config.get('environment') or rule_labels.get('environment') or '',
        prefer_metric_datasource=True,
    )
    results = []
    for item in payload.get('result') or []:
        metric = _dict(item.get('metric'))
        value = _latest_prom_value(item)
        labels = _labels(rule, metric)
        labels['metric_datasource_id'] = str(rule.metric_datasource_id)
        labels['metric_datasource_name'] = rule.metric_datasource.name
        if rule.metric_datasource.environment:
            labels.setdefault('environment', rule.metric_datasource.environment)
        if rule.metric_datasource.cluster_name:
            labels.setdefault('cluster', rule.metric_datasource.cluster_name)
        resource = labels.get('pod') or labels.get('instance') or labels.get('node') or labels.get('job') or ''
        matched = _compare(value, condition)
        results.append({
            'source_type': 'prometheus',
            'matched': matched,
            'value': value,
            'labels': labels,
            'resource': resource,
            'resource_type': labels.get('resource_type') or 'metric',
            'metric_name': labels.get('__name__') or query,
            'title': rule.name if matched else '',
            'message': f'{query} value {value}',
            'evidence': result_evidence('prometheus', query=query, value=value, labels=labels, raw=item),
        })
    return results


def _sql_literal(value):
    return "'" + str(value or '').replace('\\', '\\\\').replace("'", "\\'") + "'"


def _window_minutes(value, default=5):
    text = str(value or '').strip().lower()
    if not text:
        return default
    try:
        if text.endswith('m'):
            return int(float(text[:-1]))
        if text.endswith('h'):
            return int(float(text[:-1]) * 60)
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _clickhouse_datasource(query_config):
    datasource_id = query_config.get('log_datasource_id') or query_config.get('datasource_id')
    if datasource_id:
        return LogDataSource.objects.get(pk=datasource_id)
    return LogDataSource.objects.filter(provider='clickhouse', is_enabled=True).order_by('-is_default', 'name').first()


def _clickhouse_sql(rule, datasource, collection):
    query_config = _dict(rule.query_config)
    condition = _dict(rule.condition)
    database = _clickhouse_identifier(collection['database'], 'database')
    table = _clickhouse_identifier(collection['table'], 'table')
    time_field = _clickhouse_identifier(collection.get('time_field') or 'timestamp', 'time field')
    level_field = collection.get('level_field') or 'log_level'
    level_identifier = _clickhouse_identifier(level_field, 'level field')
    group_by = str(query_config.get('group_by') or condition.get('group_by') or '').strip()
    group_identifier = _clickhouse_identifier(group_by, 'group by') if group_by else "''"
    window_minutes = _window_minutes(query_config.get('window_minutes') or query_config.get('window') or condition.get('window_minutes') or 5)
    filters = [f'{time_field} >= now() - INTERVAL {max(window_minutes, 1)} MINUTE']

    levels = query_config.get('levels') or query_config.get('level') or query_config.get('log_level') or condition.get('levels') or condition.get('level') or condition.get('log_level')
    if isinstance(levels, (list, tuple, set)):
        normalized_levels = [str(item).strip().upper() for item in levels if str(item or '').strip()]
        if normalized_levels:
            level_values = ','.join(_sql_literal(item) for item in normalized_levels)
            filters.append(f'upper(toString({level_identifier})) IN ({level_values})')
    else:
        level = str(levels or '').strip()
        if level:
            filters.append(f'upper(toString({level_identifier})) = upper({_sql_literal(level)})')

    status_min = query_config.get('status_min')
    if status_min is None:
        status_min = condition.get('status_min')
    status_max = query_config.get('status_max')
    if status_max is None:
        status_max = condition.get('status_max')
    try:
        if status_min is not None and str(status_min).strip() != '':
            filters.append(f'{level_identifier} >= {int(status_min)}')
        if status_max is not None and str(status_max).strip() != '':
            filters.append(f'{level_identifier} <= {int(status_max)}')
    except (TypeError, ValueError):
        pass

    keyword = str(condition.get('keyword') or query_config.get('keyword') or '').strip()
    message_fields = [item.strip() for item in str(collection.get('message_fields') or 'message,log_message').split(',') if item.strip()]
    if keyword and message_fields:
        keyword_clauses = [
            f'positionCaseInsensitive(toString({_clickhouse_identifier(field, "message field")}), {_sql_literal(keyword)}) > 0'
            for field in message_fields
        ]
        filters.append('(' + ' OR '.join(keyword_clauses) + ')')

    where_clause = ' AND '.join(filters)
    if group_by:
        return (
            f'SELECT {group_identifier} AS name, count() AS value '
            f'FROM {database}.{table} WHERE {where_clause} '
            f'GROUP BY name ORDER BY value DESC LIMIT 50'
        )
    return f'SELECT count() AS value FROM {database}.{table} WHERE {where_clause}'


def _clickhouse_results(rule, *, collection_key=None):
    query_config = _dict(rule.query_config)
    condition = _dict(rule.condition)
    datasource = _clickhouse_datasource(query_config)
    if not datasource:
        raise RuntimeError('ClickHouse log datasource is not connected')
    config = _merge_config('clickhouse', datasource.config)
    collection = _resolve_clickhouse_collection(config, {'collection': collection_key or query_config.get('collection') or 'container-logs'})
    sql = _clickhouse_sql(rule, datasource, collection)
    response = _clickhouse_request(config, sql)
    rows = _clickhouse_data_rows(response)
    results = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        value = _number(row.get('value') if row.get('value') is not None else row.get('count'))
        labels = _labels(rule, {
            'collection': collection.get('key'),
            'resource': row.get('name') or row.get('resource') or '',
        })
        matched = _compare(value, condition)
        results.append({
            'source_type': 'clickhouse',
            'matched': matched,
            'value': value,
            'labels': labels,
            'resource': labels.get('resource') or '',
            'resource_type': 'log',
            'title': rule.name if matched else '',
            'message': f'ClickHouse {collection.get("key")} count {value}',
            'evidence': result_evidence('clickhouse', sql=sql, value=value, labels=labels, raw=row),
        })
    return results


def _sla_results(rule):
    condition = _dict(rule.condition)
    summary = build_sla_summary()
    metric = str(_dict(rule.query_config).get('metric') or 'month_sla')
    value = _number(summary.get(metric))
    if value is None and metric == 'monthly_risk':
        value = 1 if summary['month_status'] != '达标' else 0
    matched = _compare(value, condition)
    labels = _labels(rule, {'resource': 'sla', 'metric': metric, 'severity': 'disaster-risk'})
    return [{
        'source_type': 'sla',
        'matched': matched,
        'value': value,
        'labels': labels,
        'resource': 'sla-monthly-risk',
        'resource_type': 'sla',
        'metric_name': metric,
        'title': rule.name if matched else '',
        'message': f'SLA {metric}={value}, status={summary["month_status"]}',
        'evidence': result_evidence('sla', query=metric, value=value, labels=labels, raw=summary),
    }]


def _k8s_results(rule):
    query_config = _dict(rule.query_config)
    if query_config.get('promql') or query_config.get('query'):
        return _prometheus_results(rule)
    return _clickhouse_results(rule, collection_key=query_config.get('collection') or 'k8s-events')


def evaluate_rule(rule, *, dry_run=False, request=None):
    if rule.is_template:
        raise ValueError('规则模板不能直接执行，请先创建规则实例')
    if not rule.is_enabled and not dry_run:
        raise ValueError('alert rule is disabled')
    started = time.perf_counter()
    try:
        if rule.source_type == 'prometheus':
            results = _prometheus_results(rule)
        elif rule.source_type == 'clickhouse':
            results = _clickhouse_results(rule)
        elif rule.source_type == 'sla':
            results = _sla_results(rule)
        elif rule.source_type == 'k8s':
            results = _k8s_results(rule)
        else:
            results = []
        results = _apply_condition_levels(rule, results)
        processed = process_rule_results(rule, results, dry_run=dry_run, request=request)
        processed.update({
            'success': True,
            'rule_id': rule.id,
            'rule_code': rule.code,
            'source_type': rule.source_type,
            'evaluated_at': timezone.now().isoformat(),
        })
        if not dry_run:
            matched = int(processed.get('matched_count') or 0)
            fired = int(processed.get('would_fire_count') or 0)
            resources = [
                item.get('resource') or (item.get('labels') or {}).get('pod') or (item.get('labels') or {}).get('instance')
                for item in processed.get('results') or []
            ]
            rule.last_evaluation_duration_ms = int((time.perf_counter() - started) * 1000)
            rule.last_result_count = len(processed.get('results') or [])
            rule.last_matched_count = matched
            rule.last_matched_resource = str(next((item for item in resources if item), '') or '')[:256]
            rule.consecutive_error_count = 0
            rule.last_evaluation_error = ''
            if not matched:
                rule.no_data_count += 1
            if fired:
                rule.trigger_count += fired
            if processed.get('resolved_count'):
                rule.flap_count += int(processed['resolved_count'])
            rule.save(update_fields=[
                'last_evaluation_duration_ms', 'last_result_count', 'last_matched_count', 'last_matched_resource',
                'consecutive_error_count', 'last_evaluation_error', 'no_data_count', 'trigger_count', 'flap_count', 'updated_at',
            ])
        return processed
    except Exception as exc:
        if not dry_run:
            mark_rule_error(rule, exc)
            rule.last_evaluation_duration_ms = int((time.perf_counter() - started) * 1000)
            rule.evaluation_error_count += 1
            rule.consecutive_error_count += 1
            rule.last_evaluation_error = str(exc)[:2000]
            rule.save(update_fields=[
                'last_evaluation_duration_ms', 'evaluation_error_count', 'consecutive_error_count',
                'last_evaluation_error', 'updated_at',
            ])
        return {
            'success': False,
            'dry_run': dry_run,
            'rule_id': rule.id,
            'rule_code': rule.code,
            'source_type': rule.source_type,
            'matched_count': 0,
            'would_fire_count': 0,
            'results': [],
            'error': str(exc),
            'evaluated_at': timezone.now().isoformat(),
        }


ROOT_CAUSE_MAP = {
    'cpu_usage': (
        'CPU 使用率达到 {value:.1f}%，可能存在大量慢查询或连接数过多',
        '建议检查慢查询日志，优化 SQL 语句，或考虑扩容',
    ),
    'memory_usage': (
        '内存使用率达到 {value:.1f}%，可能存在内存泄漏或缓存过大',
        '建议检查内存占用进程，优化缓存配置，或考虑扩容',
    ),
    'disk_usage': (
        '磁盘使用率达到 {value:.1f}%，磁盘空间不足',
        '建议清理日志文件，扩容磁盘，或迁移历史数据',
    ),
    'connection_ratio': (
        '连接数使用率达到 {value:.1f}%，接近最大连接数限制',
        '建议增加 max_connections 配置，或检查连接泄漏',
    ),
    'replication_lag': (
        '主从复制延迟 {value:.1f} 秒，从库同步落后',
        '建议检查从库 IO/SQL 线程状态，检查网络带宽和主库写入压力',
    ),
    'slow_queries': (
        '慢查询数达到 {value:.0f}，SQL 执行效率低下',
        '建议分析慢查询日志，添加合适索引，优化查询语句',
    ),
    'qps': (
        'QPS 达到 {value:.0f}，查询压力过大',
        '建议检查热点查询，添加缓存层，或进行读写分离',
    ),
    'node_load': (
        '节点负载达到 {value:.2f}，CPU 负载过高',
        '建议检查系统进程，迁移部分服务到其他节点，或扩容',
    ),
    'pod_restarts': (
        'Pod 重启次数达到 {value:.0f}，可能存在稳定性问题',
        '建议检查 Pod 日志，排查 OOMKill、配置错误或依赖服务不可用',
    ),
    'pod_cpu': (
        'Pod CPU 使用率达到 {value:.1f}%，可能存在计算密集任务',
        '建议调整资源请求/限制，优化代码逻辑，或水平扩容',
    ),
    'pod_memory': (
        'Pod 内存使用率达到 {value:.1f}%，接近内存限制',
        '建议检查内存泄漏，调整资源请求/限制，或扩容',
    ),
}


def _analyze_root_cause(metric_name, value, resource=''):
    """根据指标名和值提供智能根因分析和建议。参考 database-monitor-main 设计。"""
    text_value = f'{value:.2f}' if isinstance(value, (int, float)) else str(value)
    entry = ROOT_CAUSE_MAP.get(metric_name)
    if entry:
        cause_template, suggestion_template = entry
        cause = cause_template.format(value=float(value)) if isinstance(value, (int, float)) else cause_template.format(value=0)
        suggestion = suggestion_template
        if resource:
            suggestion = f'资源: {resource}。{suggestion}'
        return cause, suggestion
    return f'指标 {metric_name} 异常，当前值 {text_value}', f'请检查 {metric_name} 指标详情，排查异常原因'


def build_alert_with_root_cause(rule, result, status='active'):
    """构建带根因分析的告警载荷。参考 database-monitor-main alert_service.py"""
    metric_name = result.get('metric_name') or rule.query_config.get('metric') or rule.query_config.get('promql') or ''
    value = result.get('value')
    resource = result.get('resource') or ''
    root_cause, suggestion = _analyze_root_cause(metric_name, value, resource)
    return {
        'root_cause': root_cause,
        'suggestion': suggestion,
    }
