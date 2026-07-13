from .models import ObservabilityDashboard, ObservabilityDashboardPanel


def prom_panel(key, title, chart_type, query, sort_order, unit='', label='', decimals=0):
    target = {'query': query}
    if label:
        target['label'] = label
    return {
        'key': key,
        'title': title,
        'chart_type': chart_type,
        'datasource_type': 'prometheus',
        'targets': [target],
        'options': {'unit': unit, 'decimals': decimals},
        'sort_order': sort_order,
    }


def ch_panel(key, title, chart_type, collection, sql, sort_order, unit='', decimals=0):
    return {
        'key': key,
        'title': title,
        'chart_type': chart_type,
        'datasource_type': 'clickhouse',
        'targets': [{'collection': collection, 'sql': sql}],
        'options': {'unit': unit, 'decimals': decimals},
        'sort_order': sort_order,
    }


BUILTIN_DASHBOARDS = [
    {
        'title': 'K8S Cluster Health',
        'description': 'Cluster nodes, pods, resource usage, restarts, storage, network, and API server request rate.',
        'tags': ['k8s', 'prometheus', 'cluster'],
        'panels': [
            prom_panel('k8s-node-total', 'Nodes', 'stat', 'count(kube_node_info)', 1, 'nodes'),
            prom_panel('k8s-running-pods', 'Running Pods', 'stat', 'count(kube_pod_status_phase{phase="Running"} == 1)', 2, 'pods'),
            prom_panel('k8s-cpu-usage', 'Cluster CPU Usage', 'stat', 'sum(rate(container_cpu_usage_seconds_total{container!="",image!=""}[5m])) / sum(kube_node_status_allocatable{resource="cpu"}) * 100', 3, '%', decimals=1),
            prom_panel('k8s-memory-usage', 'Cluster Memory Usage', 'stat', 'sum(container_memory_working_set_bytes{container!="",image!=""}) / sum(kube_node_status_allocatable{resource="memory"}) * 100', 4, '%', decimals=1),
            prom_panel('k8s-pod-restart-top', 'Pod Restarts Top', 'bar', 'topk(10, sum by(namespace,pod) (increase(kube_pod_container_status_restarts_total[24h])))', 10, 'times', 'pod'),
            prom_panel('k8s-pod-phase', 'Pod Phase Distribution', 'bar', 'sum by(phase) (kube_pod_status_phase == 1)', 11, 'pods', 'phase'),
            prom_panel('k8s-namespace-pods', 'Pods By Namespace', 'bar', 'topk(20, count by(namespace) (kube_pod_info))', 12, 'pods', 'namespace'),
            prom_panel('k8s-node-cpu-top', 'Node CPU Top', 'bar', 'topk(10, 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100))', 13, '%', 'instance', 1),
            prom_panel('k8s-node-memory-top', 'Node Memory Top', 'bar', 'topk(10, (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100)', 14, '%', 'instance', 1),
            prom_panel('k8s-pod-cpu-top', 'Pod CPU Top', 'bar', 'topk(10, sum by(namespace,pod) (rate(container_cpu_usage_seconds_total{container!="",image!=""}[5m])))', 15, 'cores', 'pod', 3),
            prom_panel('k8s-pod-memory-top', 'Pod Memory Top', 'bar', 'topk(10, sum by(namespace,pod) (container_memory_working_set_bytes{container!="",image!=""}))', 16, 'bytes', 'pod'),
            prom_panel('k8s-node-disk-usage', 'Node Disk Usage', 'bar', 'topk(10, (1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"}) * 100)', 17, '%', 'instance', 1),
            prom_panel('k8s-network-rx', 'Network Receive', 'timeseries', 'sum by(instance) (rate(node_network_receive_bytes_total{device!~"lo|veth.*|cni.*|flannel.*"}[5m]))', 20, 'B/s', 'instance'),
            prom_panel('k8s-network-tx', 'Network Transmit', 'timeseries', 'sum by(instance) (rate(node_network_transmit_bytes_total{device!~"lo|veth.*|cni.*|flannel.*"}[5m]))', 21, 'B/s', 'instance'),
            prom_panel('k8s-disk-io-read', 'Disk Read', 'timeseries', 'sum by(instance) (rate(node_disk_read_bytes_total[5m]))', 22, 'B/s', 'instance'),
            prom_panel('k8s-disk-io-write', 'Disk Write', 'timeseries', 'sum by(instance) (rate(node_disk_written_bytes_total[5m]))', 23, 'B/s', 'instance'),
            prom_panel('k8s-apiserver-rate', 'APIServer Requests', 'timeseries', 'sum by(verb) (rate(apiserver_request_total[5m]))', 24, 'req/s', 'verb'),
            prom_panel('k8s-pvc-usage', 'PVC Usage Top', 'bar', 'topk(10, kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes * 100)', 25, '%', 'persistentvolumeclaim', 1),
        ],
    },
    {
        'title': 'Linux Server Resources',
        'description': 'Server CPU, memory, disk, load, and network throughput.',
        'tags': ['server', 'prometheus', 'linux'],
        'panels': [
            prom_panel('server-cpu-usage', 'CPU Usage', 'stat', '(1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))) * 100', 1, '%', decimals=1),
            prom_panel('server-memory-usage', 'Memory Usage', 'stat', '(1 - sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)) * 100', 2, '%', decimals=1),
            prom_panel('server-disk-usage-top', 'Disk Usage Top', 'bar', 'topk(10, (1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"}) * 100)', 3, '%', 'instance', 1),
            prom_panel('server-load-top', 'Load Top', 'bar', 'topk(10, node_load1)', 4, '', 'instance', 2),
            prom_panel('server-network-rx', 'Network Receive', 'timeseries', 'sum by(instance) (rate(node_network_receive_bytes_total{device!~"lo|veth.*"}[5m]))', 5, 'B/s', 'instance'),
            prom_panel('server-network-tx', 'Network Transmit', 'timeseries', 'sum by(instance) (rate(node_network_transmit_bytes_total{device!~"lo|veth.*"}[5m]))', 6, 'B/s', 'instance'),
        ],
    },
    {
        'title': 'ClickHouse Container Logs',
        'description': 'Kubernetes container log volume, error spikes, level distribution, namespace trends, and recent samples.',
        'tags': ['logs', 'clickhouse', 'container'],
        'panels': [
            ch_panel('container-log-total', 'Total Logs', 'stat', 'container-logs', 'SELECT count() AS value FROM {table} WHERE {time_filter}', 1, 'logs'),
            ch_panel('container-error-total', 'Error Logs', 'stat', 'container-logs', "SELECT countIf(upper(toString(log_level)) IN ('ERROR','FATAL','CRITICAL')) AS value FROM {table} WHERE {time_filter}", 2, 'logs'),
            ch_panel('container-unknown-total', 'Unknown Level Logs', 'stat', 'container-logs', "SELECT countIf(empty(toString(log_level)) OR upper(toString(log_level)) = 'UNKNOWN') AS value FROM {table} WHERE {time_filter}", 3, 'logs'),
            ch_panel('container-level-trend', 'Log Level Trend', 'timeseries', 'container-logs', 'SELECT toStartOfMinute({time_field}) AS time, toString(log_level) AS name, count() AS value FROM {table} WHERE {time_filter} GROUP BY time, name ORDER BY time', 10, 'logs'),
            ch_panel('container-namespace-trend', 'Namespace Trend', 'timeseries', 'container-logs', 'SELECT toStartOfMinute({time_field}) AS time, toString(namespace) AS name, count() AS value FROM {table} WHERE {time_filter} GROUP BY time, name ORDER BY time', 11, 'logs'),
            ch_panel('container-node-top', 'Logs By Node', 'bar', 'container-logs', 'SELECT toString(node_name) AS name, count() AS value FROM {table} WHERE {time_filter} GROUP BY name ORDER BY value DESC LIMIT 20', 12, 'logs'),
            ch_panel('container-pod-top', 'Logs By Pod', 'bar', 'container-logs', 'SELECT toString(pod_name) AS name, count() AS value FROM {table} WHERE {time_filter} GROUP BY name ORDER BY value DESC LIMIT 20', 13, 'logs'),
            ch_panel('container-namespace-top', 'Logs By Namespace', 'bar', 'container-logs', 'SELECT toString(namespace) AS name, count() AS value FROM {table} WHERE {time_filter} GROUP BY name ORDER BY value DESC LIMIT 20', 14, 'logs'),
            ch_panel('container-error-samples', 'Recent Error Samples', 'logs', 'container-logs', "SELECT timestamp, namespace, pod_name, container_name, node_name, log_level, message, log_message FROM {table} WHERE {time_filter} AND upper(toString(log_level)) IN ('ERROR','FATAL','CRITICAL') ORDER BY timestamp DESC LIMIT 100", 20),
            ch_panel('container-recent-logs', 'Recent Container Logs', 'logs', 'container-logs', 'SELECT timestamp, namespace, pod_name, container_name, node_name, log_level, message, log_message FROM {table} WHERE {time_filter} ORDER BY timestamp DESC LIMIT 100', 21),
        ],
    },
    {
        'title': 'ClickHouse K8S Events',
        'description': 'Kubernetes event volume, warning reasons, namespaces, and recent abnormal events.',
        'tags': ['k8s', 'events', 'clickhouse'],
        'panels': [
            ch_panel('k8s-events-total', 'Total Events', 'stat', 'k8s-events', 'SELECT count() AS value FROM {table} WHERE {time_filter}', 1, 'events'),
            ch_panel('k8s-events-warning-total', 'Warning Events', 'stat', 'k8s-events', "SELECT countIf(upper(toString(event_type)) IN ('WARNING','ERROR')) AS value FROM {table} WHERE {time_filter}", 2, 'events'),
            ch_panel('k8s-events-reason-top', 'Reason Top', 'bar', 'k8s-events', 'SELECT toString(reason) AS name, count() AS value FROM {table} WHERE {time_filter} GROUP BY name ORDER BY value DESC LIMIT 20', 10, 'events'),
            ch_panel('k8s-events-namespace-top', 'Namespace Top', 'bar', 'k8s-events', 'SELECT toString(namespace) AS name, count() AS value FROM {table} WHERE {time_filter} GROUP BY name ORDER BY value DESC LIMIT 20', 11, 'events'),
            ch_panel('k8s-events-trend', 'Event Trend', 'timeseries', 'k8s-events', 'SELECT toStartOfMinute({time_field}) AS time, toString(event_type) AS name, count() AS value FROM {table} WHERE {time_filter} GROUP BY time, name ORDER BY time', 12, 'events'),
            ch_panel('k8s-events-recent-warning', 'Recent Warning Events', 'table', 'k8s-events', "SELECT timestamp, namespace, pod_name, event_type, reason, message, source_component, source_host, count FROM {table} WHERE {time_filter} AND upper(toString(event_type)) IN ('WARNING','ERROR') ORDER BY timestamp DESC LIMIT 100", 20),
        ],
    },
    {
        'title': 'Ingress Access Logs',
        'description': 'Ingress request volume, 5XX spikes, response latency, path/domain/upstream/client breakdown, and recent 5XX samples.',
        'tags': ['ingress', 'clickhouse', 'nginx'],
        'panels': [
            ch_panel('ingress-request-total', 'Total Requests', 'stat', 'ingress-access', 'SELECT count() AS value FROM {table} WHERE {time_filter}', 1, 'req'),
            ch_panel('ingress-5xx-total', '5XX Requests', 'stat', 'ingress-access', 'SELECT countIf(status >= 500) AS value FROM {table} WHERE {time_filter}', 2, 'req'),
            ch_panel('ingress-5xx-ratio', '5XX Ratio', 'stat', 'ingress-access', 'SELECT if(count() = 0, 0, countIf(status >= 500) / count() * 100) AS value FROM {table} WHERE {time_filter}', 3, '%', 2),
            ch_panel('ingress-avg-rt', 'Avg Response Time', 'stat', 'ingress-access', 'SELECT avg(responsetime) * 1000 AS value FROM {table} WHERE {time_filter}', 4, 'ms', 1),
            ch_panel('ingress-qps', 'QPS', 'timeseries', 'ingress-access', "SELECT toStartOfMinute({time_field}) AS time, 'QPS' AS name, count() / 60 AS value FROM {table} WHERE {time_filter} GROUP BY time ORDER BY time", 10, 'req/s', 2),
            ch_panel('ingress-latency-quantile', 'Latency P90/P95/P99', 'timeseries', 'ingress-access', "SELECT toStartOfMinute({time_field}) AS time, 'p90' AS name, quantileExact(0.90)(responsetime) * 1000 AS value FROM {table} WHERE {time_filter} GROUP BY time UNION ALL SELECT toStartOfMinute({time_field}) AS time, 'p95' AS name, quantileExact(0.95)(responsetime) * 1000 AS value FROM {table} WHERE {time_filter} GROUP BY time UNION ALL SELECT toStartOfMinute({time_field}) AS time, 'p99' AS name, quantileExact(0.99)(responsetime) * 1000 AS value FROM {table} WHERE {time_filter} GROUP BY time ORDER BY time", 11, 'ms', 1),
            ch_panel('ingress-5xx-path-top', '5XX Path Top', 'bar', 'ingress-access', "SELECT concat(toString(domain), ':', toString(path)) AS name, count() AS value FROM {table} WHERE {time_filter} AND status >= 500 GROUP BY name ORDER BY value DESC LIMIT 20", 12, 'req'),
            ch_panel('ingress-status-top', 'Status Code Top', 'bar', 'ingress-access', 'SELECT toString(status) AS name, count() AS value FROM {table} WHERE {time_filter} GROUP BY name ORDER BY value DESC LIMIT 20', 13, 'req'),
            ch_panel('ingress-upstream-top', 'Upstream Host Top', 'bar', 'ingress-access', 'SELECT toString(upstreamhost) AS name, count() AS value FROM {table} WHERE {time_filter} GROUP BY name ORDER BY value DESC LIMIT 20', 14, 'req'),
            ch_panel('ingress-client-top', 'Client IP Top', 'bar', 'ingress-access', 'SELECT toString(client_ip) AS name, count() AS value FROM {table} WHERE {time_filter} GROUP BY name ORDER BY value DESC LIMIT 20', 15, 'req'),
            ch_panel('ingress-server-top', 'Server IP Top', 'bar', 'ingress-access', 'SELECT toString(server_ip) AS name, count() AS value FROM {table} WHERE {time_filter} GROUP BY name ORDER BY value DESC LIMIT 20', 16, 'req'),
            ch_panel('ingress-slow-requests', 'Slow Requests', 'table', 'ingress-access', 'SELECT timestamp, domain, path, status, responsetime, upstreamhost, client_ip, server_ip, request_method FROM {table} WHERE {time_filter} AND responsetime > 0.5 ORDER BY responsetime DESC LIMIT 100', 20),
            ch_panel('ingress-5xx-samples', 'Recent 5XX Samples', 'table', 'ingress-access', 'SELECT timestamp, domain, path, status, responsetime, upstreamhost, client_ip, server_ip, request_method FROM {table} WHERE {time_filter} AND status >= 500 ORDER BY timestamp DESC LIMIT 100', 21),
        ],
    },
    {
        'title': 'SLA Alert Risk Cockpit',
        'description': 'Monthly SLA, annual forecast, budget, product SLA, and disaster alert risk.',
        'tags': ['sla', 'alerts'],
        'panels': [
            {'key': 'sla-month', 'title': 'Monthly SLA', 'chart_type': 'stat', 'datasource_type': 'sla', 'targets': [{'metric': 'month_sla'}], 'options': {'unit': '%', 'decimals': 4}, 'sort_order': 1},
            {'key': 'sla-annual-forecast', 'title': 'Annual Forecast', 'chart_type': 'stat', 'datasource_type': 'sla', 'targets': [{'metric': 'annual_forecast_sla'}], 'options': {'unit': '%', 'decimals': 4}, 'sort_order': 2},
            {'key': 'sla-budget-remaining', 'title': 'Budget Remaining', 'chart_type': 'stat', 'datasource_type': 'sla', 'targets': [{'metric': 'annual_budget_remaining_minutes'}], 'options': {'unit': 'min', 'decimals': 1}, 'sort_order': 3},
        ],
    },
    {
        'title': 'MySQL Overview',
        'description': 'MySQL availability, connections, slow queries, and command throughput.',
        'tags': ['mysql', 'prometheus', 'middleware'],
        'panels': [
            prom_panel('mysql-up', 'MySQL Up', 'stat', 'min(mysql_up)', 1),
            prom_panel('mysql-connections', 'Connections', 'stat', 'sum(mysql_global_status_threads_connected)', 2),
            prom_panel('mysql-running-threads', 'Running Threads', 'timeseries', 'mysql_global_status_threads_running', 3, '', 'instance'),
            prom_panel('mysql-slow-queries', 'Slow Queries', 'timeseries', 'increase(mysql_global_status_slow_queries[5m])', 4, '', 'instance'),
            prom_panel('mysql-qps', 'Questions QPS', 'timeseries', 'rate(mysql_global_status_questions[5m])', 5, 'qps', 'instance'),
        ],
    },
    {
        'title': 'Redis Overview',
        'description': 'Redis availability, clients, memory, command throughput, and keyspace hit ratio.',
        'tags': ['redis', 'prometheus', 'middleware'],
        'panels': [
            prom_panel('redis-up', 'Redis Up', 'stat', 'min(redis_up)', 1),
            prom_panel('redis-clients', 'Connected Clients', 'stat', 'sum(redis_connected_clients)', 2),
            prom_panel('redis-memory', 'Memory Usage', 'timeseries', 'redis_memory_used_bytes', 3, 'bytes', 'instance'),
            prom_panel('redis-commands', 'Commands QPS', 'timeseries', 'rate(redis_commands_processed_total[5m])', 4, 'qps', 'instance'),
            prom_panel('redis-hit-ratio', 'Hit Ratio', 'stat', 'sum(rate(redis_keyspace_hits_total[5m])) / clamp_min(sum(rate(redis_keyspace_hits_total[5m])) + sum(rate(redis_keyspace_misses_total[5m])), 1) * 100', 5, '%', decimals=2),
        ],
    },
    {
        'title': 'PostgreSQL Overview',
        'description': 'PostgreSQL availability, connections, deadlocks, transactions, and cache hit ratio.',
        'tags': ['postgresql', 'prometheus', 'middleware'],
        'panels': [
            prom_panel('postgresql-up', 'PostgreSQL Up', 'stat', 'min(pg_up)', 1),
            prom_panel('postgresql-connections', 'Connections', 'stat', 'sum(pg_stat_activity_count)', 2),
            prom_panel('postgresql-deadlocks', 'Deadlocks', 'timeseries', 'increase(pg_stat_database_deadlocks[5m])', 3, '', 'datname'),
            prom_panel('postgresql-xact-commit', 'Commits', 'timeseries', 'rate(pg_stat_database_xact_commit[5m])', 4, 'tps', 'datname'),
            prom_panel('postgresql-cache-hit', 'Cache Hit Ratio', 'stat', 'sum(pg_stat_database_blks_hit) / clamp_min(sum(pg_stat_database_blks_hit) + sum(pg_stat_database_blks_read), 1) * 100', 5, '%', decimals=2),
        ],
    },
    {
        'title': 'Kafka Overview',
        'description': 'Kafka broker count, consumer lag, offline partitions, and topic throughput.',
        'tags': ['kafka', 'prometheus', 'middleware'],
        'panels': [
            prom_panel('kafka-brokers', 'Brokers', 'stat', 'sum(kafka_brokers)', 1),
            prom_panel('kafka-consumer-lag', 'Consumer Lag', 'timeseries', 'kafka_consumergroup_lag', 2, '', 'consumergroup'),
            prom_panel('kafka-offline-partitions', 'Offline Partitions', 'stat', 'sum(kafka_controller_kafkacontroller_offlinepartitionscount)', 3),
            prom_panel('kafka-topic-in', 'Topic Bytes In', 'timeseries', 'sum by(topic) (rate(kafka_topic_partition_current_offset[5m]))', 4, '', 'topic'),
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
        desired_keys = [panel['key'] for panel in definition.get('panels') or []]
        dashboard.panels.exclude(key__in=desired_keys).delete()
        for panel in definition.get('panels') or []:
            defaults = dict(panel)
            key = defaults.pop('key')
            ObservabilityDashboardPanel.objects.update_or_create(
                dashboard=dashboard,
                key=key,
                defaults=defaults,
            )
