from django.db import migrations


K8S_FIELD_MAP = {
    'timestamp': '@timestamp',
    'message': 'message',
    'level': 'log.level',
    'service': 'kubernetes.labels.app',
    'namespace': 'kubernetes.namespace_name',
    'pod': 'kubernetes.pod_name',
    'container': 'kubernetes.container_name',
    'host': 'kubernetes.node_name',
}


def backfill_k8s_elk_field_maps(apps, schema_editor):
    LogDataSource = apps.get_model('ops', 'LogDataSource')
    for datasource in LogDataSource.objects.filter(provider='elk').iterator():
        config = dict(datasource.config or {})
        index_pattern = str(config.get('index_pattern') or '')
        if not index_pattern.startswith('k8s-') or config.get('collections'):
            continue
        field_map = dict(K8S_FIELD_MAP)
        if isinstance(config.get('field_map'), dict):
            field_map.update({key: value for key, value in config['field_map'].items() if value})
        config.update({
            'collections': [{
                'key': 'container-logs',
                'name': 'K8S 容器日志',
                'index_pattern': index_pattern,
                'field_map': field_map,
            }],
            'default_collection': 'container-logs',
            'field_map': field_map,
            'time_field': field_map['timestamp'],
            'message_fields': field_map['message'],
        })
        datasource.config = config
        datasource.save(update_fields=['config'])


class Migration(migrations.Migration):
    dependencies = [('ops', '0087_inspection_profiles_and_recipient_channels')]

    operations = [
        migrations.RunPython(backfill_k8s_elk_field_maps, migrations.RunPython.noop),
    ]
