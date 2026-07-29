from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0099_detach_external_alerts_from_context'),
    ]

    operations = [
        migrations.AddField(
            model_name='alertnotificationpolicy',
            name='level_channel_ids',
            field=models.JSONField(blank=True, default=dict, verbose_name='分级通知渠道'),
        ),
    ]
