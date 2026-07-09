from django.db import migrations, models


def remove_sls_datasources(apps, schema_editor):
    LogDataSource = apps.get_model('ops', 'LogDataSource')
    LogDataSource.objects.filter(provider='sls').delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0067_remove_alert_webhook_integrations'),
    ]

    operations = [
        migrations.RunPython(remove_sls_datasources, noop),
        migrations.AlterField(
            model_name='logdatasource',
            name='provider',
            field=models.CharField(
                choices=[
                    ('loki', 'Loki'),
                    ('elk', 'ELK / Elasticsearch'),
                    ('clickhouse', 'ClickHouse'),
                ],
                max_length=16,
                verbose_name='日志类型',
            ),
        ),
    ]
