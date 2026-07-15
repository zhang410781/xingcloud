# Migration to replace eventwall FK with simple ID field
# Generated manually after eventwall module removal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0057_delete_system_posture_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='taskresourcegroup',
            name='event_environment',
            field=models.IntegerField(
                blank=True,
                null=True,
                verbose_name='事件中心环境',
            ),
        ),
    ]
