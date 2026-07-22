from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0092_alertanalysis_cancelled_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='alertrulestate',
            name='consecutive_misses',
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
