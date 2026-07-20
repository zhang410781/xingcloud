from django.db import migrations


def use_derived_level_for_k8s_elk(apps, schema_editor):
    LogDataSource = apps.get_model('ops', 'LogDataSource')
    for datasource in LogDataSource.objects.filter(provider='elk').iterator():
        config = dict(datasource.config or {})
        if not str(config.get('index_pattern') or '').startswith('k8s-'):
            continue
        changed = False
        field_map = config.get('field_map') if isinstance(config.get('field_map'), dict) else {}
        if field_map.get('level') == 'log.level':
            field_map = dict(field_map)
            field_map['level'] = '__derived__'
            config['field_map'] = field_map
            changed = True
        collections = config.get('collections') if isinstance(config.get('collections'), list) else []
        for collection in collections:
            if not isinstance(collection, dict) or not str(collection.get('index_pattern') or '').startswith('k8s-'):
                continue
            collection_map = collection.get('field_map') if isinstance(collection.get('field_map'), dict) else {}
            if collection_map.get('level') == 'log.level':
                collection_map = dict(collection_map)
                collection_map['level'] = '__derived__'
                collection['field_map'] = collection_map
                changed = True
        if changed:
            datasource.config = config
            datasource.save(update_fields=['config'])


class Migration(migrations.Migration):
    dependencies = [('ops', '0088_backfill_k8s_elk_field_maps')]

    operations = [migrations.RunPython(use_derived_level_for_k8s_elk, migrations.RunPython.noop)]
