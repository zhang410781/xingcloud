from .models import ObservabilityDashboard, ObservabilityDashboardPanel


BUILTIN_DASHBOARDS = [
    {
        'title': 'K8S 集群健康',
        'description': '节点、命名空间、Pod 状态和资源使用概览',
        'tags': ['k8s', 'prometheus'],
        'panels': [
            {'key': 'cluster-node-total', 'title': '节点数', 'chart_type': 'stat', 'datasource_type': 'prometheus', 'targets': [{'query': 'count(kube_node_info)'}], 'options': {'unit': '个'}, 'sort_order': 1},
            {'key': 'cluster-abnormal-pods', 'title': '异常 Pod', 'chart_type': 'stat', 'datasource_type': 'prometheus', 'targets': [{'query': 'count(kube_pod_status_phase{phase=~"Pending|Failed|Unknown"} == 1) or vector(0)'}], 'options': {'unit': '个'}, 'sort_order': 2},
            {'key': 'pod-restarts-top', 'title': 'Pod 重启 Top', 'chart_type': 'bar', 'datasource_type': 'prometheus', 'targets': [{'query': 'topk(10, sum by(pod, namespace) (increase(kube_pod_container_status_restarts_total[24h])))', 'label': 'pod'}], 'options': {'unit': '次'}, 'sort_order': 3},
        ],
    },
    {
        'title': 'Linux/服务器资源',
        'description': '服务器 CPU、内存、磁盘和网络吞吐',
        'tags': ['server', 'prometheus'],
        'panels': [
            {'key': 'server-cpu-usage', 'title': 'CPU 使用率', 'chart_type': 'stat', 'datasource_type': 'prometheus', 'targets': [{'query': '(1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))) * 100'}], 'options': {'unit': '%', 'decimals': 1}, 'sort_order': 1},
            {'key': 'server-memory-usage', 'title': '内存使用率', 'chart_type': 'stat', 'datasource_type': 'prometheus', 'targets': [{'query': '(1 - sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)) * 100'}], 'options': {'unit': '%', 'decimals': 1}, 'sort_order': 2},
            {'key': 'server-node-cpu-top', 'title': '节点 CPU Top', 'chart_type': 'bar', 'datasource_type': 'prometheus', 'targets': [{'query': 'topk(10, sum by(instance) (rate(node_cpu_seconds_total{mode!="idle"}[5m])) / sum by(instance) (rate(node_cpu_seconds_total[5m])) * 100)', 'label': 'instance'}], 'options': {'unit': '%'}, 'sort_order': 3},
        ],
    },
    {
        'title': 'ClickHouse 容器日志',
        'description': '容器日志总量、错误数、级别趋势和最近日志',
        'tags': ['logs', 'clickhouse', 'container'],
        'panels': [
            {'key': 'container-log-total', 'title': '日志总量', 'chart_type': 'stat', 'datasource_type': 'clickhouse', 'targets': [{'collection': 'container-logs', 'sql': 'SELECT count() AS value FROM {table} WHERE {time_filter}'}], 'options': {'unit': '条'}, 'sort_order': 1},
            {'key': 'container-error-total', 'title': '错误数', 'chart_type': 'stat', 'datasource_type': 'clickhouse', 'targets': [{'collection': 'container-logs', 'sql': "SELECT countIf(log_level IN ('ERROR','FATAL','CRITICAL','error','fatal','critical')) AS value FROM {table} WHERE {time_filter}"}], 'options': {'unit': '条'}, 'sort_order': 2},
        ],
    },
    {
        'title': 'ClickHouse K8S Events',
        'description': 'K8S Events 事件量、原因分布和异常事件',
        'tags': ['k8s', 'events', 'clickhouse'],
        'panels': [
            {'key': 'k8s-events-total', 'title': '事件总量', 'chart_type': 'stat', 'datasource_type': 'clickhouse', 'targets': [{'collection': 'k8s-events', 'sql': 'SELECT count() AS value FROM {table} WHERE {time_filter}'}], 'options': {'unit': '条'}, 'sort_order': 1},
            {'key': 'k8s-events-reason-top', 'title': '事件原因 Top', 'chart_type': 'bar', 'datasource_type': 'clickhouse', 'targets': [{'collection': 'k8s-events', 'sql': 'SELECT reason AS name, count() AS value FROM {table} WHERE {time_filter} GROUP BY name ORDER BY value DESC LIMIT 20'}], 'options': {'unit': '条'}, 'sort_order': 2},
        ],
    },
    {
        'title': 'Ingress 访问日志',
        'description': 'Ingress 请求量、5XX、延迟和 URI Top',
        'tags': ['ingress', 'clickhouse'],
        'panels': [
            {'key': 'ingress-request-total', 'title': '请求总量', 'chart_type': 'stat', 'datasource_type': 'clickhouse', 'targets': [{'collection': 'ingress-access', 'sql': 'SELECT count() AS value FROM {table} WHERE {time_filter}'}], 'options': {'unit': '次'}, 'sort_order': 1},
            {'key': 'ingress-5xx-total', 'title': '5XX 请求', 'chart_type': 'stat', 'datasource_type': 'clickhouse', 'targets': [{'collection': 'ingress-access', 'sql': 'SELECT countIf(status >= 500) AS value FROM {table} WHERE {time_filter}'}], 'options': {'unit': '次'}, 'sort_order': 2},
        ],
    },
    {
        'title': 'SLA/告警风险驾驶舱',
        'description': '月度 SLA、年度预测、预算剩余和灾难级事件',
        'tags': ['sla', 'alerts'],
        'panels': [
            {'key': 'sla-month', 'title': '本月 SLA', 'chart_type': 'stat', 'datasource_type': 'sla', 'targets': [{'metric': 'month_sla'}], 'options': {'unit': '%', 'decimals': 4}, 'sort_order': 1},
            {'key': 'sla-budget-remaining', 'title': '年度预算剩余', 'chart_type': 'stat', 'datasource_type': 'sla', 'targets': [{'metric': 'annual_budget_remaining_minutes'}], 'options': {'unit': '分钟', 'decimals': 1}, 'sort_order': 2},
        ],
    },
]


def ensure_builtin_dashboards():
    for definition in BUILTIN_DASHBOARDS:
        dashboard, _ = ObservabilityDashboard.objects.update_or_create(
            title=definition['title'],
            defaults={
                'description': definition.get('description', ''),
                'tags': definition.get('tags', []),
                'layout': definition.get('layout', {'columns': 12}),
                'is_builtin': True,
                'is_enabled': True,
            },
        )
        existing_keys = set(dashboard.panels.values_list('key', flat=True))
        for panel in definition.get('panels') or []:
            if panel.get('key') in existing_keys:
                continue
            ObservabilityDashboardPanel.objects.create(dashboard=dashboard, **panel)
