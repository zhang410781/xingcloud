from django.db import migrations


def use_registered_cluster_names(apps, schema_editor):
    AlertRule = apps.get_model('ops', 'AlertRule')
    KnowledgeEnvironment = apps.get_model('aiops', 'AIOpsKnowledgeEnvironment')

    contexts = {
        item.metric_datasource_id: item
        for item in KnowledgeEnvironment.objects.filter(
            is_enabled=True,
            metric_datasource__isnull=False,
            k8s_cluster__isnull=False,
        ).select_related('k8s_cluster').order_by('id')
    }
    queryset = AlertRule.objects.filter(
        is_template=False,
        metric_datasource__isnull=False,
        category='k8s',
    ).select_related('template')
    for rule in queryset.iterator():
        context = contexts.get(rule.metric_datasource_id)
        if not context or not context.k8s_cluster:
            continue
        display_name = context.k8s_cluster.name
        base_name = rule.template.name if rule.template_id else rule.name.split(' · ', 1)[0]
        labels = dict(rule.labels or {})
        labels['cluster_display_name'] = display_name
        rule.name = f'{base_name} · {display_name}'
        rule.labels = labels
        rule.save(update_fields=['name', 'labels', 'updated_at'])


class Migration(migrations.Migration):
    dependencies = [
        ('aiops', '0027_alter_aiopsknowledgeenvironment_k8s_cluster_and_more'),
        ('ops', '0093_alert_rule_state_misses'),
    ]

    operations = [
        migrations.RunPython(use_registered_cluster_names, migrations.RunPython.noop),
    ]
