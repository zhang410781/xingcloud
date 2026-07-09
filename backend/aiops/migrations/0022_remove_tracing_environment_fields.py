from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('aiops', '0021_remove_aiopsknowledgeenvironment_posture_environments'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='aiopsknowledgeenvironment',
            name='tracing_datasource_ids',
        ),
        migrations.RemoveField(
            model_name='aiopsknowledgeenvironment',
            name='observability_link_ids',
        ),
    ]
