from django.db import migrations
from django.db.models import Q


DEMO_HOSTNAMES = [
    'workorder-api-ecs-01',
    'workorder-api-ecs-02',
    'order-perf-test-ecs',
    'feature-x-dev-ecs',
    'airflow-worker-dev',
    'legacy-data-sync',
    'k8s-node-01',
]

DEMO_DOCKER_HOSTS = [
    'app-release-test',
    'gateway-prod',
    'member-prod',
]

DEMO_K8S_CLUSTERS = [
    'demo-k8s-cluster',
    'dev-k8s-cluster',
    'release-prod-k8s',
    'release-gray-k8s',
    'zhengzhou-production-demo-k8s',
]

DEMO_ALERT_TITLES = [
    'CPU 使用率过高',
    '内存使用率过高',
    '磁盘空间不足',
    '服务响应超时',
    'workorder-center 仓储校验超时',
    'workorder-center 下游依赖重试激增',
    'workorder-center 发布后健康检查失败',
    'quality-worker Deployment 副本不可用',
    'member-api Deployment 滚动发布卡住',
]

DEMO_LOG_SERVICES = [
    'user-service',
    'workorder-service',
    'workorder-center',
    'gateway',
    'nginx',
    'mysql',
    'redis',
]

DEMO_LOG_DATASOURCES = [
    'ELK Demo',
    'SLS Demo',
    'ELK 演示（免认证）',
    'ELK 演示（API Key 模板）',
    'SLS 演示（杭州）',
    'SLS 演示（上海）',
    'Loki 演示（免连接）',
]

LEGACY_SUGGESTED_QUESTIONS = [
    '郑州生产演示当前未确认的严重告警有哪些？',
    '郑州生产演示最近有哪些事件',
    '分析下郑州生产演示 k8s 集群的异常工作负载',
    '分析下郑州生产演示生产工单服务最近一小时有什么异常',
    '帮我生成个郑州生产演示服务器巡检任务',
    '分析下郑州生产演示生产工单服务最近一次发布后有没有异常',
    '郑州生产演示生产工单服务最近一小时 ERROR/WARN 日志有什么共同模式',
    '分析郑州生产演示最新一条告警可能原因',
]


def _safe_get_model(apps, app_label, model_name):
    """Safe model getter - returns None if model doesn't exist."""
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def remove_seeded_demo_data(apps, schema_editor):
    Host = apps.get_model('ops', 'Host')
    Alert = apps.get_model('ops', 'Alert')
    LogEntry = apps.get_model('ops', 'LogEntry')
    LogDataSource = apps.get_model('ops', 'LogDataSource')
    K8sCluster = apps.get_model('ops', 'K8sCluster')
    DockerHost = apps.get_model('ops', 'DockerHost')
    Deployment = apps.get_model('ops', 'Deployment')
    DeploymentApprovalFlow = apps.get_model('ops', 'DeploymentApprovalFlow')
    HostTask = apps.get_model('ops', 'HostTask')
    HostTaskSchedule = apps.get_model('ops', 'HostTaskSchedule')
    TransactionTicket = apps.get_model('ops', 'TransactionTicket')
    AIOpsAgentConfig = _safe_get_model(apps, 'aiops', 'AIOpsAgentConfig')
    AIOpsModelProvider = _safe_get_model(apps, 'aiops', 'AIOpsModelProvider')
    User = apps.get_model('auth', 'User')

    # Clean up ops data
    LogDataSource.objects.filter(Q(name__in=DEMO_LOG_DATASOURCES) | Q(config__demo_mode=True)).delete()
    demo_hosts = Host.objects.filter(hostname__in=DEMO_HOSTNAMES)
    Alert.objects.filter(
        Q(title__in=DEMO_ALERT_TITLES)
        | Q(host__in=demo_hosts)
        | Q(source__in=['APM', 'Prometheus', 'Zabbix'], title__in=DEMO_ALERT_TITLES)
        | Q(business_line__in=['郑州生产', '郑州生产线'])
        | Q(environment__in=['郑州生产演示', 'zhengzhou-production-demo'])
    ).delete()
    LogEntry.objects.filter(Q(host__in=demo_hosts) | Q(service__in=DEMO_LOG_SERVICES)).delete()
    Deployment.objects.filter(
        Q(image__startswith='registry.demo.local/')
        | Q(submitter__in=['ops-demo', 'dev-demo'])
        | Q(deployer__in=['ops-demo', 'dev-demo'])
        | Q(change_summary__icontains='演示')
    ).delete()
    DeploymentApprovalFlow.objects.filter(Q(created_by='ops-demo') | Q(name__startswith='事务工单 · ')).delete()
    HostTask.objects.filter(Q(created_by='ops_demo') | Q(created_by='ops-demo')).delete()
    HostTaskSchedule.objects.filter(Q(created_by='ops_demo') | Q(created_by='ops-demo')).delete()
    TransactionTicket.objects.filter(Q(applicant='ops-demo') | Q(title__startswith='示例 · ')).delete()
    K8sCluster.objects.filter(name__in=DEMO_K8S_CLUSTERS).delete()
    DockerHost.objects.filter(name__in=DEMO_DOCKER_HOSTS).delete()
    Host.objects.filter(hostname__in=DEMO_HOSTNAMES).delete()

    # Clean up deleted modules (safe wrappers)
    service_deployment = _safe_get_model(apps, 'marketplace', 'ServiceDeployment')
    if service_deployment:
        service_deployment.objects.filter(
            Q(deployer__in=['ops-demo', 'dev-demo'])
            | Q(release_name__icontains='demo')
            | Q(deploy_dir__icontains='demo')
        ).delete()

    for model_path in [
        ('eventwall', 'EventRecord'),
        ('eventwall', 'EventEnvironment'),
        ('cmdb', 'ConfigItem'),
        ('cmdb', 'CIRelation'),
        ('cmdb', 'CostRecord'),
        ('cmdb', 'ResourceNode'),
        ('cmdb', 'ResourceRequest'),
        ('sqlaudit', 'DataSource'),
        ('sqlaudit', 'SqlOrder'),
        ('sqlaudit', 'QueryOrder'),
        ('multicloud', 'CloudCredential'),
        ('multicloud', 'CloudEnvironment'),
        ('multicloud', 'CloudAsset'),
        ('multicloud', 'CloudSyncTask'),
    ]:
        model = _safe_get_model(apps, *model_path)
        if model:
            model.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0059_k8scluster_user_type'),
    ]

    operations = [
        migrations.RunPython(remove_seeded_demo_data, migrations.RunPython.noop),
    ]
