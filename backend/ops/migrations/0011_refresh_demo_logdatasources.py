from django.db import migrations


def noop(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0010_seed_demo_logdatasources'),
    ]

    operations = [
        migrations.RunPython(noop, noop),
    ]
