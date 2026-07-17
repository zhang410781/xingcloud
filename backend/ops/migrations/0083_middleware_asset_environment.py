from django.db import migrations, models
import django.db.models.deletion


def backfill_asset_environment(apps, schema_editor):
    MiddlewareAsset = apps.get_model('ops', 'MiddlewareAsset')
    TaskResourceGroup = apps.get_model('ops', 'TaskResourceGroup')

    groups_by_code = {}
    for group in TaskResourceGroup.objects.filter(group_type='environment').iterator():
        code = str(group.code or '').strip()
        if code:
            groups_by_code.setdefault(code, []).append(group.id)

    for asset in MiddlewareAsset.objects.filter(task_resource_environment__isnull=True).iterator():
        candidates = groups_by_code.get(str(asset.environment or '').strip(), [])
        if len(candidates) == 1:
            asset.task_resource_environment_id = candidates[0]
            asset.save(update_fields=['task_resource_environment'])


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0082_alert_business_context'),
    ]

    operations = [
        migrations.AddField(
            model_name='middlewareasset',
            name='task_resource_environment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='middleware_assets',
                to='ops.taskresourcegroup',
                verbose_name='资产环境分组',
            ),
        ),
        migrations.RunPython(backfill_asset_environment, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='middlewareasset',
            index=models.Index(
                fields=['task_resource_environment', 'asset_type', 'status'],
                name='ops_middle_task_re_5d0b70_idx',
            ),
        ),
    ]
