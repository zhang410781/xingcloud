from dataclasses import dataclass, field


@dataclass(frozen=True)
class ObservabilityIntegration:
    key: str
    title: str
    category: str
    source_types: list[str]
    tags: list[str]
    icon: str
    guide_path: str
    template_codes: list[str] = field(default_factory=list)
    dashboard_titles: list[str] = field(default_factory=list)
    metric_probe_queries: list[str] = field(default_factory=list)
    log_collections: list[str] = field(default_factory=list)


INTEGRATIONS = [
    ObservabilityIntegration(
        key='mysql',
        title='MySQL',
        category='middleware',
        source_types=['prometheus'],
        tags=['database', 'mysql'],
        icon='DataBase',
        guide_path='docs/监控告警/中间件监控教学/2. 部署mysql服务并监控mysql.md',
        template_codes=['mysql-down', 'mysql-high-connections', 'mysql-high-running-threads', 'mysql-slow-queries'],
        dashboard_titles=['MySQL Overview'],
        metric_probe_queries=['mysql_up', 'mysql_global_status_threads_connected'],
    ),
    ObservabilityIntegration(
        key='redis',
        title='Redis',
        category='middleware',
        source_types=['prometheus'],
        tags=['cache', 'redis'],
        icon='Coin',
        guide_path='docs/监控告警/中间件监控教学/',
        template_codes=['redis-down', 'redis-high-clients', 'redis-high-memory', 'redis-evicted-keys'],
        dashboard_titles=['Redis Overview'],
        metric_probe_queries=['redis_up', 'redis_connected_clients'],
    ),
    ObservabilityIntegration(
        key='postgresql',
        title='PostgreSQL',
        category='middleware',
        source_types=['prometheus'],
        tags=['database', 'postgresql'],
        icon='DataBase',
        guide_path='docs/监控告警/中间件监控教学/4. 部署postgresql服务并监控postgresql.md',
        template_codes=['postgresql-down', 'postgresql-high-connections'],
        dashboard_titles=['PostgreSQL Overview'],
        metric_probe_queries=['pg_up'],
    ),
    ObservabilityIntegration(
        key='kafka',
        title='Kafka',
        category='middleware',
        source_types=['prometheus'],
        tags=['queue', 'kafka'],
        icon='Connection',
        guide_path='docs/监控告警/中间件监控教学/',
        template_codes=['kafka-broker-down', 'kafka-consumer-lag', 'kafka-offline-partitions'],
        dashboard_titles=['Kafka Overview'],
        metric_probe_queries=['kafka_brokers', 'kafka_consumergroup_lag'],
    ),
    ObservabilityIntegration(
        key='kubernetes',
        title='Kubernetes',
        category='platform',
        source_types=['prometheus', 'clickhouse'],
        tags=['k8s', 'cluster'],
        icon='Histogram',
        guide_path='docs/监控告警/方案设计/',
        template_codes=['k8s-node-not-ready', 'k8s-abnormal-pods', 'k8s-pod-restarts', 'k8s-events-warning'],
        dashboard_titles=['Kubernetes Cluster Health', 'ClickHouse K8S Events'],
        metric_probe_queries=['kube_node_info', 'kube_pod_info'],
        log_collections=['k8s-events'],
    ),
    ObservabilityIntegration(
        key='linux',
        title='Linux Server',
        category='infrastructure',
        source_types=['prometheus'],
        tags=['server', 'linux'],
        icon='Monitor',
        guide_path='docs/监控告警/方案设计/',
        template_codes=['linux-node-down', 'linux-high-cpu', 'linux-high-memory', 'linux-high-disk'],
        dashboard_titles=['Linux Server Resources'],
        metric_probe_queries=['node_uname_info', 'node_cpu_seconds_total'],
    ),
    ObservabilityIntegration(
        key='clickhouse-logs',
        title='ClickHouse Logs',
        category='logs',
        source_types=['clickhouse'],
        tags=['logs', 'clickhouse', 'container'],
        icon='Search',
        guide_path='docs/监控告警/方案设计/',
        template_codes=['container-error-spike'],
        dashboard_titles=['ClickHouse Container Logs'],
        log_collections=['container-logs'],
    ),
    ObservabilityIntegration(
        key='ingress-access',
        title='Ingress Access Logs',
        category='logs',
        source_types=['clickhouse'],
        tags=['ingress', 'web'],
        icon='TrendCharts',
        guide_path='docs/监控告警/方案设计/',
        template_codes=['ingress-5xx-spike', 'ingress-latency-high'],
        dashboard_titles=['Ingress Access Logs'],
        log_collections=['ingress-access'],
    ),
    ObservabilityIntegration(
        key='sla-risk',
        title='SLA Risk',
        category='sla',
        source_types=['sla'],
        tags=['sla', 'risk'],
        icon='Odometer',
        guide_path='docs/监控告警/方案设计/可观测告警引擎设计方案.md',
        template_codes=['sla-monthly-risk'],
        dashboard_titles=['SLA Risk Cockpit'],
    ),
]


def list_integrations():
    return INTEGRATIONS


def get_integration(key):
    return next((item for item in INTEGRATIONS if item.key == key), None)
