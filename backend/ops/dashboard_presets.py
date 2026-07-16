from .models import ObservabilityDashboard, ObservabilityDashboardPanel


def prom_panel(key, title, chart_type, query, sort_order, unit='', label='', decimals=0, grid=None, targets=None, options_extra=None):
    target = {'query': query}
    if label:
        target['label'] = label
    panel_targets = targets or [target]
    options = {'unit': unit, 'decimals': decimals, 'grid': grid or {}}
    options.update(options_extra or {})
    return {
        'key': key,
        'title': title,
        'chart_type': chart_type,
        'datasource_type': 'prometheus',
        'targets': panel_targets,
        'options': options,
        'sort_order': sort_order,
    }


def ch_panel(key, title, chart_type, collection, sql, sort_order, unit='', decimals=0):
    return {
        'key': key,
        'title': title,
        'chart_type': chart_type,
        'datasource_type': 'clickhouse',
        'targets': [{'collection': collection, 'sql': sql}],
        'options': {'unit': unit, 'decimals': decimals, 'grid': {}},
        'sort_order': sort_order,
    }


def log_panel(key, title, chart_type, metric=None, field='', sort_order=1, unit='', grid=None, limit=200):
    return {
        'key': key,
        'title': title,
        'chart_type': chart_type,
        'datasource_type': 'log',
        'targets': [{'metric': metric or 'total', 'field': field, 'limit': limit}],
        'options': {'unit': unit, 'decimals': 1 if unit == 'percent' else 0, 'grid': grid or {}},
        'sort_order': sort_order,
    }


BUILTIN_DASHBOARDS = [
    {
        'title': 'K8S Cluster Health',
        'description': 'Cluster nodes, pods, resource usage, restarts, storage, network, and API server request rate.',
        'tags': ['k8s', 'prometheus', 'cluster'],
        'layout': {'columns': 24, 'row_height': 26, 'theme': 'flashcat-light'},
        'panels': [
            prom_panel('k8s-node-total', '集群节点总数', 'stat', 'count(kube_node_info)', 1, 'short', '节点总数', grid={'x': 0, 'y': 0, 'w': 4, 'h': 4}),
            prom_panel('k8s-running-pods', '运行中 Pod 数', 'stat', 'count(kube_pod_status_phase{phase="Running"} == 1) or vector(0)', 2, 'short', '运行中 Pod', grid={'x': 4, 'y': 0, 'w': 4, 'h': 4}),
            prom_panel('k8s-namespace-total', '命名空间总数', 'stat', 'count(count by(namespace)(kube_pod_info))', 3, 'short', '命名空间', grid={'x': 8, 'y': 0, 'w': 4, 'h': 4}),
            prom_panel('k8s-abnormal-pods', '异常 Pod 数', 'stat', 'count(kube_pod_status_phase{phase=~"Pending|Failed|Unknown"} == 1) or vector(0)', 4, 'short', '异常 Pods', grid={'x': 12, 'y': 0, 'w': 4, 'h': 4}),
            prom_panel('k8s-cpu-usage', '集群 CPU 使用率', 'stat', '(1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))) * 100', 5, 'percent', 'CPU%', 1, grid={'x': 16, 'y': 0, 'w': 4, 'h': 4}),
            prom_panel('k8s-memory-usage', '集群内存使用率', 'stat', '(1 - sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)) * 100', 6, 'percent', '内存%', 1, grid={'x': 20, 'y': 0, 'w': 4, 'h': 4}),
            prom_panel('k8s-node-cpu-trend', '节点 CPU 使用率', 'timeseries', 'sum by(instance) (rate(node_cpu_seconds_total{mode!="idle"}[5m])) / sum by(instance) (rate(node_cpu_seconds_total[5m])) * 100', 10, 'percent', '{{instance}}', grid={'x': 0, 'y': 4, 'w': 12, 'h': 8}),
            prom_panel('k8s-node-memory-trend', '节点内存使用率', 'timeseries', '(1 - sum by(instance) (node_memory_MemAvailable_bytes) / sum by(instance) (node_memory_MemTotal_bytes)) * 100', 11, 'percent', '{{instance}}', grid={'x': 12, 'y': 4, 'w': 12, 'h': 8}),
            prom_panel('k8s-node-status', '节点状态列表', 'table', 'max by(node)(kube_node_status_condition{condition="Ready",status="true"})', 12, 'short', 'node', grid={'x': 0, 'y': 12, 'w': 24, 'h': 8}, targets=[
                {'ref_id': 'S', 'query': 'max by(node)(kube_node_status_condition{condition="Ready",status="true"})'},
                {'ref_id': 'G', 'query': 'sum by(node)(kube_node_status_allocatable{resource="cpu"})'},
                {'ref_id': 'D', 'query': 'label_replace(sum by(instance)(rate(node_cpu_seconds_total{mode!="idle"}[5m])) / sum by(instance)(rate(node_cpu_seconds_total[5m])) * 100, "node","$1","instance","([^:]+).*")'},
                {'ref_id': 'B', 'query': 'sum by(node)(kube_node_status_allocatable{resource="memory"})'},
                {'ref_id': 'E', 'query': 'label_replace((1 - sum by(instance)(node_memory_MemAvailable_bytes) / sum by(instance)(node_memory_MemTotal_bytes)) * 100, "node","$1","instance","([^:]+).*")'},
                {'ref_id': 'L', 'query': 'label_replace(max by(instance)(node_load1), "node","$1","instance","([^:]+).*")'},
                {'ref_id': 'C', 'query': 'count by(node)(kube_pod_info)'},
                {'ref_id': 'P', 'query': 'sum by(node)(kube_node_status_allocatable{resource="pods"})'},
                {'ref_id': 'A', 'query': 'label_replace(sum by(instance)(node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs"}), "node","$1","instance","([^:]+).*")'},
                {'ref_id': 'T', 'query': 'label_replace(time() - max by(instance)(node_boot_time_seconds), "node","$1","instance","([^:]+).*")'},
            ], options_extra={'table': {'join_by': ['node'], 'label_columns': ['node'], 'columns': {'S': 'Ready', 'G': 'CPU核数', 'D': 'CPU使用率', 'B': '可用内存', 'E': '内存使用率', 'L': '1分钟负载', 'C': 'Pod数', 'P': 'Pod容量', 'A': '根盘可用', 'T': '运行秒数'}}}),
            prom_panel('k8s-pod-restart-top', 'Pod 重启次数 Top 10', 'bargauge', 'topk(10, sum by(pod, namespace) (increase(kube_pod_container_status_restarts_total[24h])))', 20, 'short', '{{namespace}}/{{pod}}', grid={'x': 0, 'y': 20, 'w': 12, 'h': 8}),
            prom_panel('k8s-pod-phase', 'Pod 状态分布', 'pie', 'count by(phase) (kube_pod_status_phase == 1)', 21, 'short', '{{phase}}', grid={'x': 12, 'y': 20, 'w': 6, 'h': 8}),
            prom_panel('k8s-namespace-pods', '命名空间 Pod 数量', 'bargauge', 'sort_desc(count by(namespace) (kube_pod_info))', 22, 'short', '{{namespace}}', grid={'x': 18, 'y': 20, 'w': 6, 'h': 8}),
            prom_panel('k8s-pod-cpu-top', 'CPU 使用量 Top 10 Pod', 'timeseries', 'topk(10, sum by(pod, namespace) (rate(container_cpu_usage_seconds_total{pod!=""}[5m])))', 30, 'cores', '{{namespace}}/{{pod}}', grid={'x': 0, 'y': 28, 'w': 12, 'h': 8}),
            prom_panel('k8s-pod-memory-top', '内存使用量 Top 10 Pod', 'timeseries', 'topk(10, sum by(pod, namespace) (container_memory_working_set_bytes{pod!=""}))', 31, 'bytes', '{{namespace}}/{{pod}}', grid={'x': 12, 'y': 28, 'w': 12, 'h': 8}),
            prom_panel('k8s-pod-details', 'Pod 详细信息列表', 'table', 'max by(pod, namespace, phase, node)(kube_pod_status_phase{phase!="Succeeded"} == 1)', 32, 'short', 'pod', grid={'x': 0, 'y': 36, 'w': 24, 'h': 12}, targets=[
                {'ref_id': 'A', 'query': 'max by(pod, namespace, phase, node, pod_ip, host_ip)((kube_pod_status_phase{phase!="Succeeded"} == 1) * on(pod, namespace) group_left(node, pod_ip, host_ip) max by(pod, namespace, node, pod_ip, host_ip)(kube_pod_info))'},
                {'ref_id': 'B', 'query': 'max by(pod, namespace)(kube_pod_container_resource_limits{resource="memory"})'},
                {'ref_id': 'C', 'query': '(sum by(pod, namespace)(rate(container_cpu_usage_seconds_total{pod!=""}[5m])) / on(pod, namespace) max by(pod, namespace)(kube_pod_container_resource_limits{resource="cpu"})) * 100'},
                {'ref_id': 'D', 'query': 'max by(pod, namespace)(kube_pod_container_resource_limits{resource="cpu"})'},
                {'ref_id': 'E', 'query': 'time() - max by(pod, namespace)(kube_pod_start_time)'},
            ], options_extra={'table': {'join_by': ['namespace', 'pod'], 'label_columns': ['namespace', 'pod', 'phase', 'node'], 'columns': {'A': '状态', 'B': '内存Limit', 'C': 'CPU使用率', 'D': 'CPU Limit', 'E': '运行秒数'}}}),
            prom_panel('k8s-disk-usage', '节点磁盘使用率', 'timeseries', '(1 - sum by(instance) (node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs"}) / sum by(instance) (node_filesystem_size_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs"})) * 100', 40, 'percent', '{{instance}}', grid={'x': 0, 'y': 48, 'w': 12, 'h': 8}),
            prom_panel('k8s-network-rates', '节点网络收发速率', 'timeseries', 'sum by(instance) (rate(node_network_receive_bytes_total{device!~"lo|veth.*|cali.*|flannel.*|vxlan.*"}[5m]))', 41, 'Bps', '{{instance}} 接收', grid={'x': 12, 'y': 48, 'w': 12, 'h': 8}, targets=[{'ref_id': 'A', 'query': 'sum by(instance) (rate(node_network_receive_bytes_total{device!~"lo|veth.*|cali.*|flannel.*|vxlan.*"}[5m]))', 'label': '{{instance}} 接收'}, {'ref_id': 'B', 'query': 'sum by(instance) (rate(node_network_transmit_bytes_total{device!~"lo|veth.*|cali.*|flannel.*|vxlan.*"}[5m]))', 'label': '{{instance}} 发送'}]),
            prom_panel('k8s-disk-io', '节点磁盘 I/O 吞吐', 'timeseries', 'sum by(instance) (rate(node_disk_read_bytes_total{device=~"vda|sda|nvme.*"}[5m]))', 42, 'Bps', '{{instance}} 读', grid={'x': 0, 'y': 56, 'w': 12, 'h': 8}, targets=[{'ref_id': 'A', 'query': 'sum by(instance) (rate(node_disk_read_bytes_total{device=~"vda|sda|nvme.*"}[5m]))', 'label': '{{instance}} 读'}, {'ref_id': 'B', 'query': 'sum by(instance) (rate(node_disk_written_bytes_total{device=~"vda|sda|nvme.*"}[5m]))', 'label': '{{instance}} 写'}]),
            prom_panel('k8s-network-packets', '节点网络数据包收发速率', 'timeseries', 'sum by(instance) (rate(node_network_receive_packets_total{device!~"lo|veth.*|cali.*|flannel.*|vxlan.*"}[5m]))', 43, 'pps', '{{instance}} 接收包', grid={'x': 12, 'y': 56, 'w': 12, 'h': 8}, targets=[{'ref_id': 'A', 'query': 'sum by(instance) (rate(node_network_receive_packets_total{device!~"lo|veth.*|cali.*|flannel.*|vxlan.*"}[5m]))', 'label': '{{instance}} 接收包'}, {'ref_id': 'B', 'query': 'sum by(instance) (rate(node_network_transmit_packets_total{device!~"lo|veth.*|cali.*|flannel.*|vxlan.*"}[5m]))', 'label': '{{instance}} 发送包'}]),
            prom_panel('k8s-apiserver-rate', 'API Server 请求速率', 'timeseries', 'sum by(verb, code) (rate(apiserver_request_total{job="apiserver"}[5m]))', 44, 'reqps', '{{verb}} {{code}}', grid={'x': 0, 'y': 64, 'w': 12, 'h': 8}),
            prom_panel('k8s-cpu-requests-limits', 'CPU Requests/Limits vs 实际用量', 'timeseries', 'sum(kube_pod_container_resource_requests{resource="cpu"})', 45, 'cores', 'CPU Requests', grid={'x': 12, 'y': 64, 'w': 12, 'h': 8}, targets=[{'ref_id': 'A', 'query': 'sum(kube_pod_container_resource_requests{resource="cpu"})', 'label': 'CPU Requests'}, {'ref_id': 'B', 'query': 'sum(kube_pod_container_resource_limits{resource="cpu"})', 'label': 'CPU Limits'}, {'ref_id': 'C', 'query': 'sum(rate(container_cpu_usage_seconds_total{pod!=""}[5m]))', 'label': 'CPU 实际使用'}]),
            prom_panel('k8s-memory-requests-limits', 'Memory Requests/Limits vs 实际用量', 'timeseries', 'sum(kube_pod_container_resource_requests{resource="memory"})', 46, 'bytes', 'Memory Requests', grid={'x': 0, 'y': 72, 'w': 12, 'h': 8}, targets=[{'ref_id': 'A', 'query': 'sum(kube_pod_container_resource_requests{resource="memory"})', 'label': 'Memory Requests'}, {'ref_id': 'B', 'query': 'sum(kube_pod_container_resource_limits{resource="memory"})', 'label': 'Memory Limits'}, {'ref_id': 'C', 'query': 'sum(container_memory_usage_bytes{pod!=""})', 'label': '内存实际使用'}]),
            prom_panel('k8s-pvc-usage', 'PVC 存储使用率', 'table', 'kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes * 100', 47, 'percent', 'persistentvolumeclaim', grid={'x': 12, 'y': 72, 'w': 12, 'h': 8}),
            prom_panel('k8s-namespace-memory', '命名空间内存用量对比', 'timeseries', 'sort_desc(sum by(namespace) (container_memory_usage_bytes{pod!=""}))', 48, 'bytes', '{{namespace}}', grid={'x': 0, 'y': 80, 'w': 12, 'h': 8}),
            prom_panel('k8s-namespace-cpu', '命名空间 CPU 用量对比', 'timeseries', 'sort_desc(sum by(namespace) (rate(container_cpu_usage_seconds_total{pod!=""}[5m])))', 49, 'cores', '{{namespace}}', grid={'x': 12, 'y': 80, 'w': 12, 'h': 8}),
        ],
    },
    {
        'title': 'Linux Server Resources',
        'description': '集中查看服务器 CPU、内存、负载、磁盘与网络吞吐。',
        'tags': ['server', 'prometheus', 'linux'],
        'panels': [
            prom_panel('server-cpu-usage', 'CPU 使用率', 'stat', '(1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))) * 100', 1, '%', decimals=1),
            prom_panel('server-memory-usage', '内存使用率', 'stat', '(1 - sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)) * 100', 2, '%', decimals=1),
            prom_panel('server-load-1m', '1 分钟负载', 'stat', 'avg(node_load1)', 3, '', decimals=2),
            prom_panel('server-disk-usage', '磁盘使用率', 'stat', 'max((1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"}) * 100)', 4, '%', decimals=1),
            prom_panel('server-network-rx-rate', '网络接收速率', 'stat', 'sum(rate(node_network_receive_bytes_total{device!~"lo|veth.*"}[5m]))', 5, 'B/s', decimals=1),
            prom_panel('server-network-tx-rate', '网络发送速率', 'stat', 'sum(rate(node_network_transmit_bytes_total{device!~"lo|veth.*"}[5m]))', 6, 'B/s', decimals=1),
            prom_panel('server-disk-usage-top', '磁盘使用率 Top', 'bar', 'topk(10, (1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"}) * 100)', 10, '%', 'instance', 1),
            prom_panel('server-load-top', '节点负载 Top', 'bar', 'topk(10, node_load1)', 11, '', 'instance', 2),
            prom_panel('server-network-rx', '网络接收趋势', 'timeseries', 'sum by(instance) (rate(node_network_receive_bytes_total{device!~"lo|veth.*"}[5m]))', 20, 'B/s', 'instance'),
            prom_panel('server-network-tx', '网络发送趋势', 'timeseries', 'sum by(instance) (rate(node_network_transmit_bytes_total{device!~"lo|veth.*"}[5m]))', 21, 'B/s', 'instance'),
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
        'title': 'Observability Logs Overview',
        'description': 'Flashcat-style log volume, severity, source distribution, and abnormal samples.',
        'tags': ['logs', 'observability'],
        'layout': {'columns': 24, 'row_height': 26, 'theme': 'flashcat-light'},
        'panels': [
            log_panel('logs-total', '日志总量', 'stat', 'total', sort_order=1, unit='logs', grid={'x': 0, 'y': 0, 'w': 6, 'h': 4}),
            log_panel('logs-errors', '错误日志', 'stat', 'errors', sort_order=2, unit='logs', grid={'x': 6, 'y': 0, 'w': 6, 'h': 4}),
            log_panel('logs-error-rate', '错误率', 'stat', 'error_rate', sort_order=3, unit='percent', grid={'x': 12, 'y': 0, 'w': 6, 'h': 4}),
            log_panel('logs-services', '活跃服务数', 'stat', 'services', sort_order=4, unit='services', grid={'x': 18, 'y': 0, 'w': 6, 'h': 4}),
            log_panel('logs-level-trend', '日志级别趋势', 'timeseries', field='level', sort_order=10, grid={'x': 0, 'y': 4, 'w': 12, 'h': 8}),
            log_panel('logs-source-trend', '服务日志趋势', 'timeseries', field='service', sort_order=11, grid={'x': 12, 'y': 4, 'w': 12, 'h': 8}),
            log_panel('logs-level-distribution', '日志级别分布', 'pie', field='level', sort_order=20, grid={'x': 0, 'y': 12, 'w': 8, 'h': 8}),
            log_panel('logs-source-top', '服务日志量 Top', 'bargauge', field='service', sort_order=21, grid={'x': 8, 'y': 12, 'w': 8, 'h': 8}),
            log_panel('logs-namespace-top', '命名空间 Top', 'bargauge', field='namespace', sort_order=22, grid={'x': 16, 'y': 12, 'w': 8, 'h': 8}),
            log_panel('logs-pod-top', 'Pod Top', 'bargauge', field='pod', sort_order=23, grid={'x': 0, 'y': 20, 'w': 8, 'h': 8}),
            log_panel('logs-host-top', '主机 Top', 'bargauge', field='host', sort_order=24, grid={'x': 8, 'y': 20, 'w': 8, 'h': 8}),
            log_panel('logs-abnormal', '最近异常日志', 'logs', 'errors', sort_order=25, grid={'x': 16, 'y': 20, 'w': 8, 'h': 8}, limit=100),
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
        'description': '集中查看 MySQL 可用性、连接、慢查询与查询吞吐。',
        'tags': ['mysql', 'prometheus', 'middleware'],
        'panels': [
            prom_panel('mysql-up', '可用状态', 'stat', 'min(mysql_up)', 1),
            prom_panel('mysql-connections', '当前连接数', 'stat', 'sum(mysql_global_status_threads_connected)', 2),
            prom_panel('mysql-connection-usage', '连接使用率', 'stat', 'sum(mysql_global_status_threads_connected) / clamp_min(sum(mysql_global_variables_max_connections), 1) * 100', 3, '%', decimals=1),
            prom_panel('mysql-running-threads-stat', '运行线程数', 'stat', 'sum(mysql_global_status_threads_running)', 4),
            prom_panel('mysql-qps-stat', '查询 QPS', 'stat', 'sum(rate(mysql_global_status_questions[5m]))', 5, 'qps', decimals=1),
            prom_panel('mysql-slow-queries-stat', '慢查询数（5 分钟）', 'stat', 'sum(increase(mysql_global_status_slow_queries[5m]))', 6),
            prom_panel('mysql-connections-top', '实例连接数 Top', 'bar', 'topk(10, mysql_global_status_threads_connected)', 10, 'connections', 'instance'),
            prom_panel('mysql-running-threads', '运行线程趋势', 'timeseries', 'mysql_global_status_threads_running', 20, '', 'instance'),
            prom_panel('mysql-slow-queries', '慢查询趋势', 'timeseries', 'increase(mysql_global_status_slow_queries[5m])', 21, '', 'instance'),
            prom_panel('mysql-qps', '查询 QPS 趋势', 'timeseries', 'rate(mysql_global_status_questions[5m])', 22, 'qps', 'instance'),
        ],
    },
    {
        'title': 'Redis Overview',
        'description': '集中查看 Redis 可用性、客户端、内存、命令吞吐与缓存命中率。',
        'tags': ['redis', 'prometheus', 'middleware'],
        'panels': [
            prom_panel('redis-up', '可用状态', 'stat', 'min(redis_up)', 1),
            prom_panel('redis-clients', '已连接客户端', 'stat', 'sum(redis_connected_clients)', 2),
            prom_panel('redis-memory', '内存使用趋势', 'timeseries', 'redis_memory_used_bytes', 3, 'bytes', 'instance'),
            prom_panel('redis-commands', '命令 QPS 趋势', 'timeseries', 'rate(redis_commands_processed_total[5m])', 4, 'qps', 'instance'),
            prom_panel('redis-hit-ratio', '缓存命中率', 'stat', 'sum(rate(redis_keyspace_hits_total[5m])) / clamp_min(sum(rate(redis_keyspace_hits_total[5m])) + sum(rate(redis_keyspace_misses_total[5m])), 1) * 100', 5, '%', decimals=2),
        ],
    },
    {
        'title': 'PostgreSQL Overview',
        'description': '集中查看 PostgreSQL 可用性、连接、死锁、事务与缓存命中率。',
        'tags': ['postgresql', 'prometheus', 'middleware'],
        'panels': [
            prom_panel('postgresql-up', '可用状态', 'stat', 'min(pg_up)', 1),
            prom_panel('postgresql-connections', '当前连接数', 'stat', 'sum(pg_stat_activity_count)', 2),
            prom_panel('postgresql-deadlocks', '死锁趋势', 'timeseries', 'increase(pg_stat_database_deadlocks[5m])', 3, '', 'datname'),
            prom_panel('postgresql-xact-commit', '事务提交趋势', 'timeseries', 'rate(pg_stat_database_xact_commit[5m])', 4, 'tps', 'datname'),
            prom_panel('postgresql-cache-hit', '缓存命中率', 'stat', 'sum(pg_stat_database_blks_hit) / clamp_min(sum(pg_stat_database_blks_hit) + sum(pg_stat_database_blks_read), 1) * 100', 5, '%', decimals=2),
        ],
    },
    {
        'title': 'Kafka Overview',
        'description': '集中查看 Kafka Broker、消费积压、离线分区与 Topic 吞吐。',
        'tags': ['kafka', 'prometheus', 'middleware'],
        'panels': [
            prom_panel('kafka-brokers', 'Broker 数量', 'stat', 'sum(kafka_brokers)', 1),
            prom_panel('kafka-consumer-lag', '消费积压趋势', 'timeseries', 'kafka_consumergroup_lag', 2, '', 'consumergroup'),
            prom_panel('kafka-offline-partitions', '离线分区数', 'stat', 'sum(kafka_controller_kafkacontroller_offlinepartitionscount)', 3),
            prom_panel('kafka-topic-in', 'Topic 吞吐趋势', 'timeseries', 'sum by(topic) (rate(kafka_topic_partition_current_offset[5m]))', 4, '', 'topic'),
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
