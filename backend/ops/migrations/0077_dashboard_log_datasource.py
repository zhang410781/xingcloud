from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ops', '0076_alert_models_simplification')]

    operations = [
        migrations.AlterField(
            model_name='observabilitydashboardpanel',
            name='datasource_type',
            field=models.CharField(
                choices=[
                    ('prometheus', 'Prometheus'),
                    ('clickhouse', 'ClickHouse'),
                    ('log', 'Logs'),
                    ('sla', 'SLA'),
                ],
                default='prometheus',
                max_length=32,
                verbose_name='数据源类型',
            ),
        ),
    ]
