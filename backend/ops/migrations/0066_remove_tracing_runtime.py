from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0065_alert_rules'),
    ]

    operations = [
        migrations.DeleteModel(
            name='ObservabilityDataSourceLink',
        ),
        migrations.DeleteModel(
            name='TracingDataSource',
        ),
    ]
