from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('aiops', '0022_remove_tracing_environment_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='aiopsknowledgeenvironment',
            name='grafana_folder_keys',
        ),
    ]
