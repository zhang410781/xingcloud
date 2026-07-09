# Generated for XingCloud asset registration fields.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0060_remove_seeded_demo_data'),
    ]

    operations = [
        migrations.AddField(
            model_name='taskresource',
            name='asset_environment',
            field=models.CharField(blank=True, default='', max_length=32, verbose_name='资产环境'),
        ),
        migrations.AddField(
            model_name='taskresource',
            name='project_owner',
            field=models.CharField(blank=True, default='', max_length=64, verbose_name='项目负责人'),
        ),
    ]
