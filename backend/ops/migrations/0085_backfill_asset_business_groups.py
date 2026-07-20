from django.db import migrations


def backfill_business_groups(apps, schema_editor):
    TaskResource = apps.get_model('ops', 'TaskResource')
    MiddlewareAsset = apps.get_model('ops', 'MiddlewareAsset')
    for resource in TaskResource.objects.exclude(environment_id=None).iterator():
        resource.business_groups.add(resource.environment_id)
    for asset in MiddlewareAsset.objects.exclude(task_resource_environment_id=None).iterator():
        asset.business_groups.add(asset.task_resource_environment_id)


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0084_middlewareasset_business_groups_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_business_groups, migrations.RunPython.noop),
    ]
