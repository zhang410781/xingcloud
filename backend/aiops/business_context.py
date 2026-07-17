from datetime import timedelta

from django.db.models import Q

from .models import AIOpsKnowledgeEnvironment


def resolve_business_context(value, *, enabled_only=True):
    if isinstance(value, AIOpsKnowledgeEnvironment):
        return value if (value.is_enabled or not enabled_only) else None
    queryset = AIOpsKnowledgeEnvironment.objects.select_related(
        'metric_datasource', 'log_datasource', 'k8s_cluster', 'task_resource_environment',
    )
    if enabled_only:
        queryset = queryset.filter(is_enabled=True)
    text = str(value or '').strip()
    if not text:
        return None
    if text.isdigit():
        matched = queryset.filter(pk=int(text)).first()
        if matched:
            return matched
    return queryset.filter(Q(code=text) | Q(name=text)).first()


def context_payload(context):
    if not context:
        return None
    return {
        'id': context.id,
        'name': context.name,
        'code': context.code,
        'business_line': context.business_line,
        'environment_type': context.environment_type,
        'owner': context.owner,
        'metric_datasource_id': context.metric_datasource_id,
        'log_datasource_id': context.log_datasource_id,
        'k8s_cluster_id': context.k8s_cluster_id,
        'task_resource_environment_id': context.task_resource_environment_id,
    }


def assign_alert_context(alert):
    environment_code = str(alert.environment or '').strip()
    context = (
        AIOpsKnowledgeEnvironment.objects
        .filter(is_enabled=True, code=environment_code)
        .first()
        if environment_code
        else None
    )
    context_id = context.id if context else None
    if alert.knowledge_environment_id != context_id:
        alert.knowledge_environment_id = context_id
    return context


def discover_context_bindings(code):
    from ops.models import K8sCluster, LogDataSource, MetricDataSource, TaskResourceGroup

    code = str(code or '').strip().lower()
    metrics = list(MetricDataSource.objects.filter(environment=code, is_enabled=True).values('id', 'name', 'environment', 'cluster_name'))
    logs = []
    for item in LogDataSource.objects.filter(is_enabled=True).order_by('name'):
        config = item.config if isinstance(item.config, dict) else {}
        configured_environment = str(config.get('environment') or config.get('environment_code') or '').strip().lower()
        if configured_environment == code:
            logs.append({'id': item.id, 'name': item.name, 'provider': item.provider})
    cluster_names = {str(item.get('cluster_name') or '').strip() for item in metrics if item.get('cluster_name')}
    clusters = list(K8sCluster.objects.filter(name__in=cluster_names).values('id', 'name', 'status')) if cluster_names else []
    assets = list(TaskResourceGroup.objects.filter(group_type='environment', code=code).values('id', 'name', 'code'))
    return {
        'code': code,
        'metric_datasources': metrics,
        'log_datasources': logs,
        'k8s_clusters': clusters,
        'asset_environments': assets,
        'unambiguous': all(len(items) <= 1 for items in (metrics, logs, clusters, assets)),
    }


def validate_context_bindings(context, *, live=False):
    from ops.models import AlertRule, MiddlewareAsset, TaskResource

    checks = []

    def add(code, title, ok, detail='', blocking=True):
        checks.append({'code': code, 'title': title, 'status': 'ready' if ok else 'missing', 'detail': detail, 'blocking': blocking})

    metric = context.metric_datasource
    add('metric_datasource', 'Prometheus 指标源', bool(metric and metric.is_enabled), getattr(metric, 'name', '') or '未绑定')
    if metric:
        add('metric_environment', '指标源环境编码', metric.environment == context.code, metric.environment or '未设置')
    log = context.log_datasource
    add('log_datasource', '日志数据源', bool(log and log.is_enabled), getattr(log, 'name', '') or '未绑定')
    if log:
        log_config = log.config if isinstance(log.config, dict) else {}
        field_map = log_config.get('field_map') if isinstance(log_config.get('field_map'), dict) else {}
        required_log_fields = {'timestamp', 'message', 'level', 'service', 'namespace', 'pod'}
        missing_log_fields = sorted(required_log_fields - {key for key, value in field_map.items() if value})
        add(
            'log_field_map',
            '日志字段映射',
            not missing_log_fields,
            '已配置' if not missing_log_fields else f"缺少 {', '.join(missing_log_fields)}",
            blocking=False,
        )
    cluster = context.k8s_cluster
    add('k8s_cluster', 'K8s 集群', bool(cluster), getattr(cluster, 'name', '') or '未绑定')
    asset_environment = context.task_resource_environment
    add(
        'asset_environment', '资产环境分组',
        bool(asset_environment and asset_environment.group_type == 'environment'),
        getattr(asset_environment, 'name', '') or '未绑定',
    )
    asset_count = TaskResource.objects.filter(environment=asset_environment).count() if asset_environment else 0
    checks.append({'code': 'asset_count', 'title': '已登记资产', 'status': 'ready', 'detail': str(asset_count), 'blocking': False})
    middleware_count = MiddlewareAsset.objects.filter(task_resource_environment=asset_environment).count() if asset_environment else 0
    checks.append({'code': 'middleware_asset_count', 'title': '已登记中间件与数据库', 'status': 'ready', 'detail': str(middleware_count), 'blocking': False})
    mismatched_alerts = context.alerts.exclude(environment=context.code).count()
    add('alert_environment', '告警环境编码', mismatched_alerts == 0, f'{mismatched_alerts} 条不一致')
    checks.append({'code': 'rule_scope', 'title': '当前指标源规则', 'status': 'ready', 'detail': str(AlertRule.objects.filter(metric_datasource=metric).count() if metric else 0), 'blocking': False})

    k8s_node_names = set()
    prometheus_node_names = set()
    if live and cluster:
        try:
            from ops.k8s_views import get_k8s_nodes_snapshot
            nodes = get_k8s_nodes_snapshot(cluster)
            k8s_node_names = {str(item.get('name') or '').strip() for item in nodes if item.get('name')}
            add('k8s_nodes', 'K8s 节点读取', bool(nodes), f'{len(nodes)} 个节点')
        except Exception as exc:
            add('k8s_nodes', 'K8s 节点读取', False, str(exc)[:200])
    if live and metric:
        try:
            from ops.observability_views import execute_promql_query
            result = execute_promql_query('kube_node_info', metric_datasource_id=metric.id, environment=context.code, prefer_metric_datasource=True)
            prometheus_node_names = {
                str((series.get('metric') or {}).get('node') or '').strip()
                for series in result.get('result') or []
                if (series.get('metric') or {}).get('node')
            }
            add('prometheus_query', 'Prometheus 查询', True, f"{result.get('series_count', 0)} 个序列")
        except Exception as exc:
            add('prometheus_query', 'Prometheus 查询', False, str(exc)[:200])
    if live and k8s_node_names and prometheus_node_names:
        missing_in_metrics = sorted(k8s_node_names - prometheus_node_names)
        extra_in_metrics = sorted(prometheus_node_names - k8s_node_names)
        add(
            'node_consistency',
            'K8s 与 Prometheus 节点一致性',
            not missing_in_metrics and not extra_in_metrics,
            f'K8s {len(k8s_node_names)} / Prometheus {len(prometheus_node_names)}；'
            f'指标缺少 {missing_in_metrics[:5]}；额外 {extra_in_metrics[:5]}',
        )
    if live and log:
        try:
            from django.utils import timezone
            from ops.log_views import _merge_config, _run_query

            now = timezone.now()
            payload = {
                'query': '*',
                'start_ms': int((now - timedelta(minutes=5)).timestamp() * 1000),
                'end_ms': int(now.timestamp() * 1000),
                'limit': 1,
            }
            if log.provider == 'clickhouse':
                payload['collection'] = log_config.get('default_collection') or 'container-logs'
            result = _run_query(log.provider, _merge_config(log.provider, log.config), payload)
            add('log_query', '日志源查询', True, f"返回 {len(result.get('logs') or [])} 条样本")
        except Exception as exc:
            add('log_query', '日志源查询', False, str(exc)[:200])

    blocking_failures = [item for item in checks if item['blocking'] and item['status'] != 'ready']
    return {
        'context': context_payload(context),
        'status': 'ready' if not blocking_failures else 'incomplete',
        'ready': not blocking_failures,
        'checks': checks,
        'binding_conflicts': 0,
    }
