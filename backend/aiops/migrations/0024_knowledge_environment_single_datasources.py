from django.db import migrations, models
import django.db.models.deletion


def _first_valid_id(raw_ids, model):
    if not isinstance(raw_ids, list):
        return None
    for raw_id in raw_ids:
        try:
            datasource_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if model.objects.filter(pk=datasource_id).exists():
            return datasource_id
    return None


def backfill_single_datasources(apps, schema_editor):
    KnowledgeEnvironment = apps.get_model('aiops', 'AIOpsKnowledgeEnvironment')
    MetricDataSource = apps.get_model('ops', 'MetricDataSource')
    LogDataSource = apps.get_model('ops', 'LogDataSource')

    for environment in KnowledgeEnvironment.objects.all().iterator():
        metric_datasource_id = _first_valid_id(environment.metric_datasource_ids, MetricDataSource)
        log_datasource_id = _first_valid_id(environment.log_datasource_ids, LogDataSource)
        update_fields = []
        if metric_datasource_id:
            environment.metric_datasource_id = metric_datasource_id
            environment.metric_datasource_ids = [metric_datasource_id]
            update_fields.extend(['metric_datasource', 'metric_datasource_ids'])
        if log_datasource_id:
            environment.log_datasource_id = log_datasource_id
            environment.log_datasource_ids = [log_datasource_id]
            update_fields.extend(['log_datasource', 'log_datasource_ids'])
        if update_fields:
            environment.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0078_alert_rule_datasource_notification_policy'),
        ('aiops', '0023_remove_grafana_environment_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='aiopsknowledgeenvironment',
            name='log_datasource',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='aiops_knowledge_environments',
                to='ops.logdatasource',
                verbose_name='日志数据源',
            ),
        ),
        migrations.AddField(
            model_name='aiopsknowledgeenvironment',
            name='metric_datasource',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='aiops_knowledge_environments',
                to='ops.metricdatasource',
                verbose_name='指标数据源',
            ),
        ),
        migrations.RunPython(backfill_single_datasources, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='aiopsmodelinvocation',
            name='purpose',
            field=models.CharField(
                choices=[
                    ('chat_planning', '聊天规划'),
                    ('answer_formatting', '回答整形'),
                    ('parameter_extraction', '参数抽取'),
                    ('model_probe', '模型探测'),
                    ('connection_test', '连接测试'),
                    ('alert_analysis', '告警研判'),
                ],
                default='chat_planning',
                max_length=32,
                verbose_name='调用目的',
            ),
        ),
    ]
