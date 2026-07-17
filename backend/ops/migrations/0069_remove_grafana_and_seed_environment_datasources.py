from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0068_remove_sls_log_provider'),
    ]

    operations = [
        migrations.DeleteModel(
            name='GrafanaSetting',
        ),
    ]
