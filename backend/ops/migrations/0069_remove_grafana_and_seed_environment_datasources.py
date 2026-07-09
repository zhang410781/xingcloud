from django.db import migrations


CLICKHOUSE_COLLECTIONS = [
    {
        'key': 'container-logs',
        'name': 'K8S Container Logs',
        'database': 'container_logs',
        'table': 'logs',
        'time_field': 'timestamp',
        'message_fields': 'message,log_message',
        'level_field': 'log_level',
        'source_fields': 'namespace,pod_name,container_name',
        'search_fields': 'namespace,pod_name,node_name,container_name,log_level,message,log_message,source,log_file_path',
    },
    {
        'key': 'k8s-events',
        'name': 'K8S Events',
        'database': 'container_logs',
        'table': 'events',
        'time_field': 'timestamp',
        'message_fields': 'message,reason',
        'level_field': 'event_type',
        'source_fields': 'namespace,pod_name,source_component',
        'search_fields': 'namespace,pod_name,event_type,reason,message,source_component,source_host,count',
    },
    {
        'key': 'ingress-access',
        'name': 'Ingress Access Logs',
        'database': 'nginxlogs',
        'table': 'nginx_access',
        'time_field': 'timestamp',
        'message_fields': '',
        'level_field': 'status',
        'source_fields': 'domain,server_ip,client_ip',
        'search_fields': 'domain,path,top_path,query,client_ip,remote_ip,xff,status,server_ip,http_user_agent',
    },
]


def seed_environment_datasources(apps, schema_editor):
    MetricDataSource = apps.get_model('ops', 'MetricDataSource')
    LogDataSource = apps.get_model('ops', 'LogDataSource')

    metric_sources = [
        {
            'name': '智能运维平台 Prometheus',
            'description': '智能运维平台 K8S 集群指标源',
            'environment': '智能运维平台',
            'cluster_name': 'k8s-master',
            'is_default': True,
            'query_url': 'http://10.132.46.52:30003',
        },
        {
            'name': '测试环境 Prometheus',
            'description': '测试环境 K8S 集群指标源',
            'environment': '测试环境',
            'cluster_name': 'master3',
            'is_default': False,
            'query_url': 'http://10.132.46.66:30003',
        },
    ]
    for source in metric_sources:
        MetricDataSource.objects.update_or_create(
            name=source['name'],
            defaults={
                'provider': 'prometheus',
                'description': source['description'],
                'environment': source['environment'],
                'cluster_name': source['cluster_name'],
                'tsdb_type': 'prometheus',
                'config': {
                    'query_url': source['query_url'],
                    'timeout': 6,
                },
                'is_enabled': True,
                'is_default': source['is_default'],
            },
        )

    clickhouse_config = {
        'endpoint': 'http://10.132.46.52:30812',
        'username': 'xinghai',
        'password': 'Aws_kkk',
        'timezone': 'Asia/Shanghai',
        'collections': CLICKHOUSE_COLLECTIONS,
    }
    datasource = (
        LogDataSource.objects.filter(name='智能运维平台 ClickHouse 日志').first()
        or LogDataSource.objects.filter(name='Zhengzhou Production ClickHouse').first()
        or LogDataSource.objects.filter(provider='clickhouse', config__endpoint='http://10.132.46.52:30812').first()
    )
    if datasource is None:
        datasource = LogDataSource(name='智能运维平台 ClickHouse 日志')
    datasource.name = '智能运维平台 ClickHouse 日志'
    datasource.provider = 'clickhouse'
    datasource.description = '智能运维平台 K8S 容器日志、集群事件和 Ingress 访问日志；测试环境日志源暂未接入。'
    datasource.config = clickhouse_config
    datasource.is_enabled = True
    datasource.is_default = True
    datasource.save()
    LogDataSource.objects.exclude(pk=datasource.pk).filter(is_default=True).update(is_default=False)


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0068_remove_sls_log_provider'),
    ]

    operations = [
        migrations.DeleteModel(
            name='GrafanaSetting',
        ),
        migrations.RunPython(seed_environment_datasources, noop),
    ]
