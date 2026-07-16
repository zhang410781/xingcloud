from copy import deepcopy

from django.db import transaction

from .models import AlertRule, MetricDataSource


def _template(category, code, name, source_type, level, query_config, condition,
              default_labels=None, annotations=None, interval_seconds=60, duration_seconds=0,
              notify_enabled=True, auto_analyze=False, description='', sort_order=100):
    return {
        'category': category,
        'code': code,
        'name': name,
        'source_type': source_type,
        'level': level,
        'query_config': query_config,
        'condition': condition,
        'default_labels': default_labels or {},
        'annotations': annotations or {},
        'interval_seconds': interval_seconds,
        'duration_seconds': duration_seconds,
        'notify_enabled': notify_enabled,
        'auto_analyze': auto_analyze,
        'description': description,
        'sort_order': sort_order,
    }


BUILTIN_ALERT_RULE_TEMPLATES = [
    # =========================================================================
    # 服务器 (server) — 基于 node_exporter 的系统指标
    # =========================================================================
    _template('server', 'linux-node-down', 'Linux 节点离线',
              'prometheus', 'critical',
              {'query': 'up{job=~".*node.*"} == 0', 'value_path': 'value'},
              {'operator': '>', 'threshold': 0},
              {'integration': 'linux', 'service': 'linux'},
              {'summary': 'Linux 节点 exporter 目标不可达'},
              duration_seconds=60, notify_enabled=True, auto_analyze=True,
              description='服务器节点可用性监控。', sort_order=100),

    _template('server', 'linux-high-cpu', 'CPU 使用率过高',
              'prometheus', 'warning',
              {'query': '(1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) by (instance)) * 100', 'value_path': 'value'},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 80, 'duration_seconds': 300},
                  {'level': 'critical', 'operator': '>', 'threshold': 90, 'duration_seconds': 120},
              ]},
              {'integration': 'linux', 'service': 'linux'},
              {'summary': 'CPU 使用率持续过高'},
              duration_seconds=300, notify_enabled=True, auto_analyze=False,
              description='CPU 使用率双阈值监控：>80% 持续5分钟警告，>90% 持续2分钟严重。', sort_order=110),

    _template('server', 'linux-high-memory', '内存使用率过高',
              'prometheus', 'warning',
              {'query': '(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100', 'value_path': 'value'},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 80, 'duration_seconds': 300},
                  {'level': 'critical', 'operator': '>', 'threshold': 92, 'duration_seconds': 120},
              ]},
              {'integration': 'linux', 'service': 'linux'},
              {'summary': '内存使用率持续过高'},
              duration_seconds=300, notify_enabled=True, auto_analyze=False,
              description='内存使用率双阈值监控：>80% 持续5分钟警告，>92% 持续2分钟严重。', sort_order=120),

    _template('server', 'linux-high-disk', '磁盘使用率过高',
              'prometheus', 'warning',
              {'query': '(1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"}) * 100', 'value_path': 'value'},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 85, 'duration_seconds': 300},
                  {'level': 'critical', 'operator': '>', 'threshold': 93, 'duration_seconds': 120},
              ]},
              {'integration': 'linux', 'service': 'linux'},
              {'summary': '磁盘使用率持续过高'},
              duration_seconds=300, notify_enabled=True, auto_analyze=False,
              description='磁盘使用率双阈值监控：>85% 持续5分钟警告，>93% 持续2分钟严重。', sort_order=130),

    _template('server', 'linux-high-load', '系统负载过高',
              'prometheus', 'warning',
              {'query': 'node_load15 / count by(instance)(node_cpu_seconds_total{mode="idle"}) * 100', 'value_path': 'value'},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 80, 'duration_seconds': 300},
                  {'level': 'critical', 'operator': '>', 'threshold': 95, 'duration_seconds': 120},
              ]},
              {'integration': 'linux', 'service': 'linux'},
              {'summary': '系统 15 分钟负载超过 CPU 核心数的指定百分比'},
              duration_seconds=300, notify_enabled=True, auto_analyze=False,
              description='系统负载双阈值监控。', sort_order=140),

    _template('server', 'linux-high-io-wait', '磁盘 IO 等待过高',
              'prometheus', 'warning',
              {'query': 'avg(rate(node_cpu_seconds_total{mode="iowait"}[5m])) by (instance) * 100', 'value_path': 'value'},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 30, 'duration_seconds': 300},
                  {'level': 'critical', 'operator': '>', 'threshold': 60, 'duration_seconds': 120},
              ]},
              {'integration': 'linux', 'service': 'linux'},
              {'summary': '磁盘 IO 等待百分比持续过高'},
              duration_seconds=300, notify_enabled=True, auto_analyze=False,
              description='磁盘 IO 等待时间双阈值监控。', sort_order=150),

    _template('server', 'linux-network-errors', '网络错误过多',
              'prometheus', 'warning',
              {'query': 'increase(node_network_receive_errors_total[1h]) > 0 or increase(node_network_transmit_errors_total[1h]) > 0', 'value_path': 'value'},
              {'operator': '>', 'threshold': 0},
              {'integration': 'linux', 'service': 'linux'},
              {'summary': '网络接口在过去一小时内出现错误'},
              duration_seconds=0, notify_enabled=True, auto_analyze=True,
              description='网络接口错误监控规则。', sort_order=160),

    # =========================================================================
    # K8S — 基于 kube_state_metrics 的集群资源监控
    # =========================================================================
    _template('k8s', 'k8s-node-not-ready', 'K8S 节点不可用',
              'prometheus', 'critical',
              {'query': 'sum(kube_node_status_condition{condition="Ready",status!="true"})', 'value_path': 'value'},
              {'operator': '>', 'threshold': 0},
              {'integration': 'kubernetes', 'service': 'kubernetes'},
              {'summary': 'Kubernetes 集群中存在 NotReady 状态的节点'},
              duration_seconds=120, notify_enabled=True, auto_analyze=True,
              description='K8S 节点状态监控。', sort_order=200),

    _template('k8s', 'k8s-abnormal-pods', 'K8S 异常 Pod',
              'prometheus', 'warning',
              {'query': 'count(kube_pod_status_phase{phase=~"Pending|Failed|Unknown"} == 1)', 'value_path': 'value'},
              {'operator': '>', 'threshold': 0},
              {'integration': 'kubernetes', 'service': 'kubernetes'},
              {'summary': 'Kubernetes 中有 Pending/Failed/Unknown 状态的 Pod'},
              duration_seconds=120, notify_enabled=True, auto_analyze=True,
              description='K8S 异常 Pod 数量监控。', sort_order=210),

    _template('k8s', 'k8s-pod-restarts', 'Pod 重启频繁',
              'prometheus', 'warning',
              {'query': 'sum by(pod, namespace) (increase(kube_pod_container_status_restarts_total[15m]))', 'value_path': 'value'},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 3, 'duration_seconds': 0},
                  {'level': 'critical', 'operator': '>', 'threshold': 10, 'duration_seconds': 0},
              ]},
              {'integration': 'kubernetes', 'service': 'kubernetes'},
              {'summary': 'Pod 在近 15 分钟内重启次数过高'},
              duration_seconds=0, notify_enabled=True, auto_analyze=True,
              description='K8S Pod 重启次数双阈值监控。', sort_order=220),

    _template('k8s', 'k8s-events-warning', 'K8S 警告事件激增',
              'clickhouse', 'warning',
              {'collection': 'k8s-events', 'window_minutes': 5, 'levels': ['Warning']},
              {'operator': '>', 'threshold': 10},
              {'integration': 'kubernetes', 'service': 'kubernetes-events'},
              {'summary': 'Kubernetes Warning 事件在近 5 分钟内激增'},
              duration_seconds=0, notify_enabled=True, auto_analyze=True,
              description='ClickHouse K8S 事件激增监控。', sort_order=230),

    _template('k8s', 'k8s-high-cpu-pod', 'K8S Pod CPU 使用率过高',
              'prometheus', 'warning',
              {'query': 'sum(rate(container_cpu_usage_seconds_total{container!=""}[5m])) by (pod, namespace) / sum(container_spec_cpu_quota{container!=""} / 100000) by (pod,namespace) * 100', 'value_path': 'value'},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 85, 'duration_seconds': 300},
                  {'level': 'critical', 'operator': '>', 'threshold': 95, 'duration_seconds': 120},
              ]},
              {'integration': 'kubernetes', 'service': 'kubernetes'},
              {'summary': 'Pod CPU 使用率超过限制'},
              duration_seconds=300, notify_enabled=True, auto_analyze=False,
              description='K8S Pod CPU 使用率双阈值监控。', sort_order=240),

    _template('k8s', 'k8s-high-memory-pod', 'K8S Pod 内存使用率过高',
              'prometheus', 'warning',
              {'query': 'sum(container_memory_working_set_bytes{container!=""}) by (pod, namespace) / sum(container_spec_memory_limit_bytes{container!=""}) by (pod,namespace) * 100', 'value_path': 'value'},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 85, 'duration_seconds': 300},
                  {'level': 'critical', 'operator': '>', 'threshold': 95, 'duration_seconds': 120},
              ]},
              {'integration': 'kubernetes', 'service': 'kubernetes'},
              {'summary': 'Pod 内存使用率超过限制'},
              duration_seconds=300, notify_enabled=True, auto_analyze=False,
              description='K8S Pod 内存使用率双阈值监控。', sort_order=250),

    _template('k8s', 'k8s-pvc-usage', 'PVC 存储使用率过高',
              'prometheus', 'warning',
              {'query': 'kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes * 100', 'value_path': 'value'},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 85, 'duration_seconds': 300},
                  {'level': 'critical', 'operator': '>', 'threshold': 95, 'duration_seconds': 120},
              ]},
              {'integration': 'kubernetes', 'service': 'kubernetes'},
              {'summary': 'PVC 存储使用率持续过高'},
              duration_seconds=300, notify_enabled=True, auto_analyze=False,
              description='K8S PVC 存储使用率双阈值监控。', sort_order=260),

    # =========================================================================
    # 数据库 (database)
    # =========================================================================
    _template('database', 'redis-down', 'Redis 不可用',
              'prometheus', 'critical',
              {'query': 'redis_up == 0', 'value_path': 'value'},
              {'operator': '>', 'threshold': 0},
              {'integration': 'redis', 'service': 'redis'},
              {'summary': 'Redis 实例离线或 exporter 不可达'},
              duration_seconds=60, notify_enabled=True, auto_analyze=True,
              description='Redis 可用性监控。', sort_order=300),

    _template('database', 'redis-high-memory', 'Redis 内存使用率过高',
              'prometheus', 'warning',
              {'query': 'redis_memory_used_bytes / redis_memory_max_bytes * 100', 'value_path': 'value'},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 80, 'duration_seconds': 120},
                  {'level': 'critical', 'operator': '>', 'threshold': 90, 'duration_seconds': 60},
              ]},
              {'integration': 'redis', 'service': 'redis'},
              {'summary': 'Redis 内存使用率持续过高'},
              duration_seconds=120, notify_enabled=True, auto_analyze=False,
              description='Redis 内存使用率双阈值监控。', sort_order=310),

    _template('database', 'mysql-down', 'MySQL 不可用',
              'prometheus', 'critical',
              {'query': 'mysql_up == 0', 'value_path': 'value'},
              {'operator': '>', 'threshold': 0},
              {'integration': 'mysql', 'service': 'mysql'},
              {'summary': 'MySQL 实例离线或 exporter 不可达'},
              duration_seconds=60, notify_enabled=True, auto_analyze=True,
              description='MySQL 可用性监控。', sort_order=320),

    _template('database', 'mysql-high-connections', 'MySQL 连接数过高',
              'prometheus', 'warning',
              {'query': 'mysql_global_status_threads_connected / mysql_global_variables_max_connections * 100', 'value_path': 'value'},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 80, 'duration_seconds': 120},
                  {'level': 'critical', 'operator': '>', 'threshold': 92, 'duration_seconds': 60},
              ]},
              {'integration': 'mysql', 'service': 'mysql'},
              {'summary': 'MySQL 连接使用率持续过高'},
              duration_seconds=120, notify_enabled=True, auto_analyze=False,
              description='MySQL 连接使用率双阈值监控。', sort_order=330),

    _template('database', 'mysql-slow-queries', 'MySQL 慢查询激增',
              'prometheus', 'warning',
              {'query': 'increase(mysql_global_status_slow_queries[5m])', 'value_path': 'value'},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 20, 'duration_seconds': 0},
                  {'level': 'critical', 'operator': '>', 'threshold': 100, 'duration_seconds': 0},
              ]},
              {'integration': 'mysql', 'service': 'mysql'},
              {'summary': 'MySQL 慢查询在近 5 分钟内激增'},
              duration_seconds=0, notify_enabled=True, auto_analyze=False,
              description='MySQL 慢查询双阈值监控。', sort_order=340),

    _template('database', 'redis-evicted-keys', 'Redis 逐出键激增',
              'prometheus', 'warning',
              {'query': 'increase(redis_evicted_keys_total[5m])', 'value_path': 'value'},
              {'operator': '>', 'threshold': 0},
              {'integration': 'redis', 'service': 'redis'},
              {'summary': 'Redis 在近 5 分钟内发生了键逐出'},
              duration_seconds=0, notify_enabled=True, auto_analyze=False,
              description='Redis 键逐出事件监控。', sort_order=350),

    # =========================================================================
    # 存储 (storage) — 暂以 Kafka / 存储相关内容占位
    # =========================================================================
    _template('storage', 'kafka-broker-down', 'Kafka Broker 离线',
              'prometheus', 'critical',
              {'query': 'kafka_brokers < 1', 'value_path': 'value'},
              {'operator': '>', 'threshold': 0},
              {'integration': 'kafka', 'service': 'kafka'},
              {'summary': 'Kafka Broker 数量低于预期'},
              duration_seconds=60, notify_enabled=True, auto_analyze=True,
              description='Kafka Broker 可用性监控。', sort_order=400),

    _template('storage', 'kafka-consumer-lag', 'Kafka 消费者积压过高',
              'prometheus', 'warning',
              {'query': 'kafka_consumergroup_lag', 'value_path': 'value'},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 1000, 'duration_seconds': 120},
                  {'level': 'critical', 'operator': '>', 'threshold': 10000, 'duration_seconds': 60},
              ]},
              {'integration': 'kafka', 'service': 'kafka'},
              {'summary': 'Kafka 消费者组积压过高'},
              duration_seconds=120, notify_enabled=True, auto_analyze=False,
              description='Kafka 消费者积压双阈值监控。', sort_order=410),

    _template('storage', 'kafka-offline-partitions', 'Kafka 离线分区',
              'prometheus', 'critical',
              {'query': 'kafka_controller_kafkacontroller_offlinepartitionscount', 'value_path': 'value'},
              {'operator': '>', 'threshold': 0},
              {'integration': 'kafka', 'service': 'kafka'},
              {'summary': 'Kafka 存在离线分区'},
              duration_seconds=60, notify_enabled=True, auto_analyze=True,
              description='Kafka 离线分区监控。', sort_order=420),

    # =========================================================================
    # 通用平台 (平台内置)
    # =========================================================================
    _template('server', 'container-error-spike', '容器 ERROR 日志激增',
              'clickhouse', 'warning',
              {'collection': 'container-logs', 'window_minutes': 5, 'level': ['ERROR', 'FATAL', 'CRITICAL']},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 50, 'duration_seconds': 0},
                  {'level': 'critical', 'operator': '>', 'threshold': 200, 'duration_seconds': 0},
              ]},
              {'integration': 'clickhouse-logs', 'service': 'container-logs'},
              {'summary': '容器 ERROR 日志在近 5 分钟内激增'},
              duration_seconds=0, notify_enabled=True, auto_analyze=False,
              description='容器日志 ERROR 等级激增双阈值监控。', sort_order=500),

    _template('server', 'ingress-5xx-spike', 'Ingress 5XX 错误激增',
              'clickhouse', 'warning',
              {'collection': 'ingress-access', 'window_minutes': 5, 'status_min': 500},
              {'levels': [
                  {'level': 'warning', 'operator': '>', 'threshold': 50, 'duration_seconds': 0},
                  {'level': 'critical', 'operator': '>', 'threshold': 200, 'duration_seconds': 0},
              ]},
              {'integration': 'ingress-access', 'service': 'ingress'},
              {'summary': 'Ingress 5XX 错误在近 5 分钟内激增'},
              duration_seconds=0, notify_enabled=True, auto_analyze=False,
              description='Ingress 5XX 错误双阈值监控。', sort_order=510),
]


def ensure_builtin_alert_rule_templates():
    """确保所有内置模板存在于数据库中（有则更新、无则创建）。"""
    rules = []
    for item in BUILTIN_ALERT_RULE_TEMPLATES:
        payload = dict(item)
        payload['labels'] = payload.pop('default_labels', {})
        payload['source'] = item['code']
        payload['is_template'] = True
        payload['is_enabled'] = False
        payload.pop('sort_order', None)
        # Seed the catalog once; subsequent edits/deletions are user-owned data.
        rule, _ = AlertRule.objects.get_or_create(code=item['code'], defaults=payload)
        rules.append(rule)
    k8s_templates = [item for item in rules if item.is_template and item.source_type == 'prometheus' and item.category == 'k8s']
    for datasource in MetricDataSource.objects.filter(provider=MetricDataSource.PROVIDER_PROMETHEUS, is_enabled=True):
        for template in k8s_templates:
            instantiate_rule_from_template(template, datasource=datasource)
    return rules


INSTANCE_FIELDS = {
    'name', 'category', 'level', 'query_config', 'condition', 'labels', 'annotations',
    'interval_seconds', 'duration_seconds', 'notify_enabled', 'auto_analyze',
    'group_window', 'repeat_interval', 'mute_schedule', 'escalation_minutes',
    'description', 'is_enabled',
}


def instantiate_rule_from_template(template, datasource=None, overrides=None):
    if not template.is_template:
        raise ValueError('所选规则不是模板')
    if template.source_type == 'prometheus' and datasource is None:
        raise ValueError('Prometheus 规则必须选择指标数据源')
    if datasource is not None and not datasource.is_enabled:
        raise ValueError('指标数据源已停用')

    existing = AlertRule.objects.filter(template=template, metric_datasource=datasource).first()
    if existing:
        return existing, False

    payload = {
        'name': f'{template.name} · {datasource.cluster_name or datasource.name}' if datasource else template.name,
        'category': template.category,
        'source': template.code,
        'is_template': False,
        'template': template,
        'metric_datasource': datasource,
        'source_type': template.source_type,
        'level': template.level,
        'query_config': deepcopy(template.query_config or {}),
        'condition': deepcopy(template.condition or {}),
        'labels': deepcopy(template.labels or {}),
        'annotations': deepcopy(template.annotations or {}),
        'interval_seconds': template.interval_seconds,
        'duration_seconds': template.duration_seconds,
        'notify_enabled': template.notify_enabled,
        'auto_analyze': template.auto_analyze,
        'group_window': template.group_window,
        'repeat_interval': template.repeat_interval,
        'mute_schedule': deepcopy(template.mute_schedule or {}),
        'escalation_minutes': template.escalation_minutes,
        'description': template.description,
        'is_enabled': False,
    }
    if datasource:
        if datasource.environment:
            payload['labels']['environment'] = datasource.environment
        if datasource.cluster_name:
            payload['labels']['cluster'] = datasource.cluster_name
        payload['labels']['metric_datasource_id'] = str(datasource.id)
    for key, value in (overrides or {}).items():
        if key in INSTANCE_FIELDS:
            payload[key] = deepcopy(value)
    return AlertRule.objects.create(**payload), True


@transaction.atomic
def ensure_datasource_rule_instances(datasource, category='k8s'):
    templates = ensure_builtin_alert_rule_templates()
    created = []
    for template in templates:
        if template.source_type != 'prometheus' or template.category != category:
            continue
        rule, was_created = instantiate_rule_from_template(template, datasource=datasource)
        if was_created:
            created.append(rule)
    return created


def install_rules_from_templates(template_codes, metric_datasource_id=None, overrides=None):
    """从模板为指定数据源创建独立规则实例。"""
    ensure_builtin_alert_rule_templates()
    datasource = None
    if metric_datasource_id not in (None, ''):
        try:
            datasource = MetricDataSource.objects.get(pk=metric_datasource_id)
        except (MetricDataSource.DoesNotExist, TypeError, ValueError) as exc:
            raise ValueError('指标数据源不存在') from exc
    templates = AlertRule.objects.filter(is_template=True, code__in=template_codes)
    template_map = {item.code: item for item in templates}
    if datasource is None and any(item.source_type == 'prometheus' for item in template_map.values()):
        raise ValueError('安装 Prometheus 规则时必须选择指标数据源')
    created = []
    skipped = []
    for code in template_codes:
        template = template_map.get(code)
        if not template:
            skipped.append(code)
            continue
        try:
            rule, was_created = instantiate_rule_from_template(template, datasource=datasource, overrides=overrides)
        except ValueError:
            skipped.append(code)
            continue
        if was_created:
            created.append(rule)
        else:
            skipped.append(code)
    return created, skipped
