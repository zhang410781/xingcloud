from django.db import migrations


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


def _default_collection_for(database, table):
    for item in DEFAULT_CLICKHOUSE_COLLECTIONS:
        if item['database'] == database and item['table'] == table:
            return item
    return None


def upgrade_clickhouse_datasources(apps, schema_editor):
    LogDataSource = apps.get_model('ops', 'LogDataSource')
    for datasource in LogDataSource.objects.filter(provider='clickhouse'):
        config = dict(datasource.config or {})
        collections = list(config.get('collections') or [])

        legacy_database = config.pop('database', '')
        legacy_table = config.pop('table', '')
        legacy_time_field = config.pop('time_field', '')
        legacy_search_fields = config.pop('search_fields', '')
        legacy_message_fields = config.pop('message_fields', '')
        legacy_level_field = config.pop('level_field', '')
        legacy_source_fields = config.pop('source_fields', '')

        if legacy_database and legacy_table:
            default_collection = _default_collection_for(legacy_database, legacy_table)
            legacy_key = (
                default_collection['key']
                if default_collection
                else f'{legacy_database}-{legacy_table}'.lower().replace('_', '-')
            )
            legacy_name = (
                default_collection['name']
                if default_collection
                else f'{legacy_database}.{legacy_table}'
            )
            if not any(item.get('database') == legacy_database and item.get('table') == legacy_table for item in collections):
                collections.append({
                    'key': legacy_key,
                    'name': legacy_name,
                    'database': legacy_database,
                    'table': legacy_table,
                    'time_field': legacy_time_field or (default_collection or {}).get('time_field') or 'timestamp',
                    'message_fields': legacy_message_fields or (default_collection or {}).get('message_fields', ''),
                    'level_field': legacy_level_field or (default_collection or {}).get('level_field', ''),
                    'source_fields': legacy_source_fields or (default_collection or {}).get('source_fields', ''),
                    'search_fields': legacy_search_fields or (default_collection or {}).get('search_fields', ''),
                })

        for item in DEFAULT_CLICKHOUSE_COLLECTIONS:
            if not any(
                existing.get('key') == item['key']
                or (existing.get('database') == item['database'] and existing.get('table') == item['table'])
                for existing in collections
            ):
                collections.append(dict(item))

        config['collections'] = collections
        datasource.config = config
        datasource.save(update_fields=['config', 'updated_at'])


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0063_clickhouse_log_datasource'),
    ]

    operations = [
        migrations.RunPython(upgrade_clickhouse_datasources, noop),
    ]
