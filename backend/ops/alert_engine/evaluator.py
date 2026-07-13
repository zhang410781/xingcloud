from django.utils import timezone

from ops.log_views import (
    _clickhouse_data_rows,
    _clickhouse_identifier,
    _clickhouse_request,
    _merge_config,
    _resolve_clickhouse_collection,
)
from ops.models import AlertRuleTemplate, LogDataSource
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


def _labels(rule, extra=None):
    labels = {}
    labels.update(_dict(rule.labels))
    labels.update(_dict(extra))
    return {str(key): value for key, value in labels.items() if value not in (None, '')}


def _prometheus_results(rule):
    query_config = _dict(rule.query_config)
    condition = _dict(rule.condition)
    query = str(query_config.get('promql') or query_config.get('query') or query_config.get('metric') or '').strip()
    rule_labels = _dict(rule.labels)
    payload = execute_promql_query(
        query,
        range_query=False,
        metric_datasource_id=query_config.get('metric_datasource_id') or query_config.get('datasource_id') or '',
        environment=query_config.get('environment') or rule_labels.get('environment') or '',
        prefer_metric_datasource=True,
    )
    results = []
    for item in payload.get('result') or []:
        metric = _dict(item.get('metric'))
        value = _latest_prom_value(item)
        labels = _labels(rule, metric)
        resource = labels.get('pod') or labels.get('instance') or labels.get('node') or labels.get('job') or ''
        matched = _compare(value, condition)
        results.append({
            'source_type': AlertRuleTemplate.SOURCE_PROMETHEUS,
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
            'source_type': AlertRuleTemplate.SOURCE_CLICKHOUSE,
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
        'source_type': AlertRuleTemplate.SOURCE_SLA,
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
    if not rule.is_enabled and not dry_run:
        raise ValueError('alert rule is disabled')
    try:
        if rule.source_type == AlertRuleTemplate.SOURCE_PROMETHEUS:
            results = _prometheus_results(rule)
        elif rule.source_type == AlertRuleTemplate.SOURCE_CLICKHOUSE:
            results = _clickhouse_results(rule)
        elif rule.source_type == AlertRuleTemplate.SOURCE_SLA:
            results = _sla_results(rule)
        elif rule.source_type == AlertRuleTemplate.SOURCE_K8S:
            results = _k8s_results(rule)
        else:
            results = []
        processed = process_rule_results(rule, results, dry_run=dry_run, request=request)
        processed.update({
            'success': True,
            'rule_id': rule.id,
            'rule_code': rule.code,
            'source_type': rule.source_type,
            'evaluated_at': timezone.now().isoformat(),
        })
        return processed
    except Exception as exc:
        if not dry_run:
            mark_rule_error(rule, exc)
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
