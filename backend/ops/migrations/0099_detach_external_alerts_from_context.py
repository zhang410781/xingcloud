from django.db import migrations


def detach_external_alerts(apps, schema_editor):
    Alert = apps.get_model('ops', 'Alert')
    ExternalAlertSource = apps.get_model('ops', 'ExternalAlertSource')

    Alert.objects.filter(source_type__in=['alertmanager', 'zabbix']).update(
        knowledge_environment_id=None,
        binding_status='not_applicable',
    )
    ExternalAlertSource.objects.update(
        default_knowledge_environment_id=None,
        mapping_rules=[],
    )


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0098_alertnotificationpolicy_external_alert_source_and_more'),
    ]

    operations = [
        migrations.RunPython(detach_external_alerts, migrations.RunPython.noop),
    ]
