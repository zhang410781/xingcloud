from django.db import migrations


def canonicalize_alert_environment_codes(apps, schema_editor):
    KnowledgeEnvironment = apps.get_model('aiops', 'AIOpsKnowledgeEnvironment')
    AlertRule = apps.get_model('ops', 'AlertRule')
    AlertRuleState = apps.get_model('ops', 'AlertRuleState')
    Alert = apps.get_model('ops', 'Alert')

    grouped = {}
    contexts = list(
        KnowledgeEnvironment.objects.filter(
            is_enabled=True,
            metric_datasource__isnull=False,
        ).order_by('id')
    )
    for context in contexts:
        grouped.setdefault(context.metric_datasource_id, []).append(context)

    for datasource_id, matches in grouped.items():
        if len(matches) != 1:
            continue
        context = matches[0]

        rules = AlertRule.objects.filter(metric_datasource_id=datasource_id)
        for rule in rules.iterator():
            labels = dict(rule.labels or {})
            labels['environment'] = context.code
            labels['environment_display_name'] = context.name
            rule.labels = labels
            rule.save(update_fields=['labels', 'updated_at'])

        for state in AlertRuleState.objects.filter(rule__metric_datasource_id=datasource_id).iterator():
            labels = dict(state.labels or {})
            labels['environment'] = context.code
            labels['environment_display_name'] = context.name
            state.labels = labels
            state.save(update_fields=['labels', 'updated_at'])

        for alert in Alert.objects.exclude(status='closed').iterator():
            labels = dict(alert.labels or {})
            alert_datasource_id = str(labels.get('metric_datasource_id') or '')
            if alert.knowledge_environment_id != context.id and alert_datasource_id != str(datasource_id):
                continue
            labels['environment'] = context.code
            labels['environment_display_name'] = context.name
            alert.environment = context.code
            alert.knowledge_environment_id = context.id
            alert.labels = labels
            alert.save(update_fields=['environment', 'knowledge_environment', 'labels', 'updated_at'])


class Migration(migrations.Migration):
    dependencies = [
        ('aiops', '0027_alter_aiopsknowledgeenvironment_k8s_cluster_and_more'),
        ('ops', '0094_use_registered_cluster_names'),
    ]

    operations = [
        migrations.RunPython(canonicalize_alert_environment_codes, migrations.RunPython.noop),
    ]
