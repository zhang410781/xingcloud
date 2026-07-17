from django.db import migrations, models
import django.db.models.deletion


def backfill_alert_context(apps, schema_editor):
    Alert = apps.get_model('ops', 'Alert')
    Environment = apps.get_model('aiops', 'AIOpsKnowledgeEnvironment')
    environment_ids = dict(Environment.objects.values_list('code', 'id'))
    for code, environment_id in environment_ids.items():
        Alert.objects.filter(environment=code, knowledge_environment__isnull=True).update(
            knowledge_environment_id=environment_id,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('aiops', '0025_business_context_bindings'),
        ('ops', '0081_remove_deployment_uniq_ops_curr_biz_app_docker_host_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='alert',
            name='knowledge_environment',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='alerts', to='aiops.aiopsknowledgeenvironment', verbose_name='业务上下文'),
        ),
        migrations.RunPython(backfill_alert_context, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='alert',
            index=models.Index(fields=['knowledge_environment', 'status', 'level'], name='ops_alert_ctx_status_level_idx'),
        ),
    ]
