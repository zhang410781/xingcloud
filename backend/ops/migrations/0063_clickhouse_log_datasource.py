from django.db import migrations, models


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
    ]
