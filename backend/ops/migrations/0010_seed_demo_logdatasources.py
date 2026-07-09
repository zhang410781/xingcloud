from django.db import migrations


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0009_seed_logdatasources'),
    ]

    operations = [
        migrations.RunPython(noop, noop),
    ]
