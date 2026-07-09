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


def _delete_if_model_exists(apps, app_label, model_name, query=None):
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        return
    queryset = model.objects.all()
    if query is not None:
        queryset = queryset.filter(query)
    queryset.delete()


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
    AIOpsAgentConfig = apps.get_model('aiops', 'AIOpsAgentConfig')
    AIOpsModelProvider = apps.get_model('aiops', 'AIOpsModelProvider')
    User = apps.get_model('auth', 'User')
    UserGroup = apps.get_model('rbac', 'UserGroup')
    EventRecord = apps.get_model('eventwall', 'EventRecord')
    EventEnvironment = apps.get_model('eventwall', 'EventEnvironment')
    ServiceDeployment = apps.get_model('marketplace', 'ServiceDeployment')
    ConfigItem = apps.get_model('cmdb', 'ConfigItem')
    CIRelation = apps.get_model('cmdb', 'CIRelation')
    CostRecord = apps.get_model('cmdb', 'CostRecord')
    ResourceNode = apps.get_model('cmdb', 'ResourceNode')
    ResourceRequest = apps.get_model('cmdb', 'ResourceRequest')
    DataSource = apps.get_model('sqlaudit', 'DataSource')
    SqlOrder = apps.get_model('sqlaudit', 'SqlOrder')
    QueryOrder = apps.get_model('sqlaudit', 'QueryOrder')
    CloudCredential = apps.get_model('multicloud', 'CloudCredential')
    CloudEnvironment = apps.get_model('multicloud', 'CloudEnvironment')
    CloudAsset = apps.get_model('multicloud', 'CloudAsset')
    CloudSyncTask = apps.get_model('multicloud', 'CloudSyncTask')

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

    ServiceDeployment.objects.filter(
        Q(deployer__in=['ops-demo', 'dev-demo'])
        | Q(release_name__icontains='demo')
        | Q(deploy_dir__icontains='demo')
    ).delete()

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

    DockerHost.objects.filter(name__in=DEMO_DOCKER_HOSTS).delete()
    K8sCluster.objects.filter(Q(name__in=DEMO_K8S_CLUSTERS) | Q(kubeconfig='demo')).delete()
    demo_hosts.delete()

    QueryOrder.objects.filter(submitter__in=['audit_demo', 'dev_demo', 'ops_demo']).delete()
    SqlOrder.objects.filter(submitter__in=['audit_demo', 'dev_demo', 'ops_demo']).delete()
    DataSource.objects.filter(
        Q(password='demo-secret')
        | Q(remark__icontains='演示')
        | Q(name__in=['工单核心库', '会员归档库'])
    ).delete()

    EventRecord.objects.filter(Q(is_demo=True) | Q(source_type='seed')).delete()
    EventEnvironment.objects.filter(
        Q(code__in=['zhengzhou-prod', 'zhengzhou-production-demo', 'zhengzhou-dev'])
        | Q(name__in=['郑州生产环境', '郑州生产演示', '郑州开发环境'])
    ).delete()

    cloud_credentials = CloudCredential.objects.filter(Q(demo_mode=True) | Q(auth_mode='demo') | Q(created_by='seed'))
    cloud_environments = CloudEnvironment.objects.filter(Q(credential__in=cloud_credentials) | Q(created_by='seed'))
    CloudAsset.objects.filter(environment__in=cloud_environments).delete()
    CloudSyncTask.objects.filter(Q(environment__in=cloud_environments) | Q(credential__in=cloud_credentials)).delete()
    cloud_environments.delete()
    cloud_credentials.delete()

    demo_business_lines = ['郑州生产线', '数据平台', '基础架构']
    demo_config_items = ConfigItem.objects.filter(Q(business_line__in=demo_business_lines) | Q(name__in=DEMO_HOSTNAMES))
    CostRecord.objects.filter(ci__in=demo_config_items).delete()
    CIRelation.objects.filter(Q(source__in=demo_config_items) | Q(target__in=demo_config_items)).delete()
    demo_config_items.delete()
    ResourceRequest.objects.filter(Q(business_line__in=demo_business_lines) | Q(applicant__in=['ops-demo', 'dev_demo', 'ops_demo'])).delete()
    demo_resource_roots = ResourceNode.objects.filter(name__in=demo_business_lines)
    ResourceNode.objects.filter(parent__in=demo_resource_roots).delete()
    demo_resource_roots.delete()

    User.objects.filter(username__in=['ops_demo', 'dev_demo', 'audit_demo', 'viewer_demo', 'demo']).delete()
    UserGroup.objects.filter(code__in=['ops-team', 'dev-team', 'audit-team', 'visitors']).delete()

    for config in AIOpsAgentConfig.objects.all():
        questions = [
            str(item).strip()
            for item in (config.suggested_questions or [])
            if str(item).strip() and str(item).strip() not in LEGACY_SUGGESTED_QUESTIONS and '郑州生产演示' not in str(item)
        ]
        if questions != (config.suggested_questions or []):
            config.suggested_questions = questions
            config.save(update_fields=['suggested_questions'])

    AIOpsModelProvider.objects.filter(name='智能助手体验版').update(
        provider_preset='sail_cloud',
        base_url='https://api.sail-cloud.com/v1',
        default_model='Qwen2.5-72B-Instruct',
        backup_model='',
        api_key_encrypted='',
        price_currency='CNY',
        last_test_status='unknown',
        last_test_message='预置 Sail Cloud 配置，需填写 API Key 后使用',
    )


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0059_k8scluster_user_type'),
        ('aiops', '0021_remove_aiopsknowledgeenvironment_posture_environments'),
        ('cmdb', '0004_resourcerequest_approval_comment_and_more'),
        ('eventwall', '0006_eventenvironment'),
        ('marketplace', '0004_add_more_marketplace_templates'),
        ('multicloud', '0002_rename_business_line_verbose_to_system'),
        ('rbac', '0002_system_module_setting'),
        ('sqlaudit', '0002_datasource_db_type'),
    ]

    operations = [
        migrations.RunPython(remove_seeded_demo_data, migrations.RunPython.noop),
    ]
