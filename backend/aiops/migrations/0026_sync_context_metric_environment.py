from django.db import migrations


def sync_context_metric_environment(apps, schema_editor):
    Environment = apps.get_model('aiops', 'AIOpsKnowledgeEnvironment')
    MetricDataSource = apps.get_model('ops', 'MetricDataSource')
    AlertRule = apps.get_model('ops', 'AlertRule')

    for context in Environment.objects.exclude(metric_datasource_id=None).iterator():
        MetricDataSource.objects.filter(pk=context.metric_datasource_id).update(environment=context.code)
        for rule in AlertRule.objects.filter(metric_datasource_id=context.metric_datasource_id).iterator():
            labels = dict(rule.labels or {})
            if labels.get('environment') == context.code:
                continue
            labels['environment'] = context.code
            rule.labels = labels
            rule.save(update_fields=['labels'])


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0083_middleware_asset_environment'),
        ('aiops', '0025_business_context_bindings'),
    ]

    operations = [
        migrations.RunPython(sync_context_metric_environment, migrations.RunPython.noop),
    ]
