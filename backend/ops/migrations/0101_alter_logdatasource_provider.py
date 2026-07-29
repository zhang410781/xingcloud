from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0100_alertnotificationpolicy_level_channel_ids'),
    ]

    operations = [
        migrations.AlterField(
            model_name='logdatasource',
            name='provider',
            field=models.CharField(
                choices=[
                    ('loki', 'Loki'),
                    ('elk', 'ELK / Elasticsearch'),
                    ('clickhouse', 'ClickHouse'),
                    ('openobserve', 'OpenObserve'),
                ],
                max_length=16,
                verbose_name='日志类型',
            ),
        ),
    ]
