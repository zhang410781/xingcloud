from django.db import migrations

LEGACY_PERMISSION_CODES = [
    'cmdb.dashboard.view',
    'cmdb.cost.view',
    'cmdb.request.submit',
    'cmdb.request.approve',
]


def remove_legacy_permissions(apps, schema_editor):
    PermissionDefinition = apps.get_model('rbac', 'PermissionDefinition')
    PermissionDefinition.objects.filter(code__in=LEGACY_PERMISSION_CODES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('rbac', '0002_system_module_setting'),
    ]

    operations = [
        migrations.RunPython(remove_legacy_permissions, migrations.RunPython.noop),
    ]
