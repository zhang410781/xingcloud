from django.conf import settings
from django.db import migrations, models


DEFAULT_CLICKHOUSE_COLLECTIONS = [
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


def seed_clickhouse_log_datasource(apps, schema_editor):
    LogDataSource = apps.get_model('ops', 'LogDataSource')
    configs = getattr(settings, 'LOG_PROVIDER_CONFIGS', {}) or {}
    config = dict(configs.get('clickhouse') or {})
    config.setdefault('endpoint', 'http://10.132.46.52:30812')
    config.setdefault('username', 'xinghai')
    config.setdefault('password', 'Aws_kkk')
    config.setdefault('timezone', 'Asia/Shanghai')
    config.setdefault('collections', DEFAULT_CLICKHOUSE_COLLECTIONS)

    datasource, _ = LogDataSource.objects.update_or_create(
        name='Zhengzhou Production ClickHouse',
        defaults={
            'provider': 'clickhouse',
            'description': 'Ingress access logs stored in ClickHouse',
            'config': config,
            'is_enabled': True,
            'is_default': True,
        },
    )
    LogDataSource.objects.exclude(pk=datasource.pk).filter(is_default=True).update(is_default=False)


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0062_remove_dirty_task_notification_data'),
    ]

    operations = [
        migrations.AlterField(
            model_name='logdatasource',
            name='provider',
            field=models.CharField(
                choices=[
                    ('loki', 'Loki'),
                    ('elk', 'ELK / Elasticsearch'),
                    ('sls', '阿里云 SLS'),
                    ('clickhouse', 'ClickHouse'),
                ],
                max_length=16,
                verbose_name='日志类型',
            ),
        ),
        migrations.RunPython(seed_clickhouse_log_datasource, noop),
    ]
