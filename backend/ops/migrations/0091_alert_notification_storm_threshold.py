from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ops', '0090_alert_quality_and_inspection_diff')]

    operations = [
        migrations.AddField(
            model_name='alertnotificationpolicy',
            name='storm_threshold',
            field=models.PositiveIntegerField(default=3, verbose_name='告警风暴阈值'),
        ),
    ]
