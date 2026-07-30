import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0103_alertnotificationroute_alertsource_alertsourceowner_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='alertnotificationpolicy',
            name='alert_source',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='notification_policies',
                to='ops.alertsource',
                verbose_name='告警源',
            ),
        ),
    ]
