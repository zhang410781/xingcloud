from django.db import migrations


TEMPLATES = [
    {
        'code': 'k8s-node-not-ready',
        'name': 'K8S Node Not Ready',
        'source_type': 'k8s',
        'level': 'critical',
        'query_config': {'query': 'sum(kube_node_status_condition{condition="Ready",status!="true"})', 'value_path': 'value'},
        'condition': {'operator': '>', 'threshold': 0},
        'default_labels': {'integration': 'kubernetes', 'service': 'kubernetes'},
        'annotations': {'summary': 'Kubernetes has nodes that are not ready'},
        'interval_seconds': 60,
        'duration_seconds': 120,
        'notify_enabled': True,
        'auto_analyze': True,
        'description': 'K8S node ready condition rule.',
        'sort_order': 500,
    },
    {
        'code': 'k8s-abnormal-pods',
        'name': 'K8S Abnormal Pods',
        'source_type': 'k8s',
        'level': 'warning',
        'query_config': {'query': 'count(kube_pod_status_phase{phase=~"Pending|Failed|Unknown"} == 1)', 'value_path': 'value'},
        'condition': {'operator': '>', 'threshold': 0},
        'default_labels': {'integration': 'kubernetes', 'service': 'kubernetes'},
        'annotations': {'summary': 'Kubernetes has abnormal pods'},
        'interval_seconds': 60,
        'duration_seconds': 120,
        'notify_enabled': True,
        'auto_analyze': True,
        'description': 'K8S abnormal pod count rule.',
        'sort_order': 510,
    },
    {
        'code': 'k8s-pod-restarts',
        'name': 'K8S Pod Restarts High',
        'source_type': 'k8s',
        'level': 'warning',
        'query_config': {'query': 'sum by(pod, namespace) (increase(kube_pod_container_status_restarts_total[15m]))', 'value_path': 'value'},
        'condition': {'operator': '>', 'threshold': 5},
        'default_labels': {'integration': 'kubernetes', 'service': 'kubernetes'},
        'annotations': {'summary': 'Kubernetes pod restarts increased'},
        'interval_seconds': 60,
        'duration_seconds': 0,
        'notify_enabled': True,
        'auto_analyze': True,
        'description': 'K8S pod restart rule.',
        'sort_order': 520,
    },
    {
        'code': 'k8s-events-warning',
        'name': 'K8S Events Warning Spike',
        'source_type': 'clickhouse',
        'level': 'warning',
        'query_config': {'collection': 'k8s-events', 'window_minutes': 5, 'levels': ['Warning']},
        'condition': {'operator': '>', 'threshold': 10},
        'default_labels': {'integration': 'kubernetes', 'service': 'kubernetes-events'},
        'annotations': {'summary': 'Kubernetes Warning events increased in the last 5 minutes'},
        'interval_seconds': 60,
        'duration_seconds': 0,
        'notify_enabled': True,
        'auto_analyze': True,
        'description': 'ClickHouse K8S Events warning spike rule.',
        'sort_order': 530,
    },
    {
        'code': 'linux-node-down',
        'name': 'Linux Node Down',
        'source_type': 'prometheus',
        'level': 'critical',
        'query_config': {'query': 'up{job=~".*node.*"} == 0', 'value_path': 'value'},
        'condition': {'operator': '>', 'threshold': 0},
        'default_labels': {'integration': 'linux', 'service': 'linux'},
        'annotations': {'summary': 'Linux node exporter target is down'},
        'interval_seconds': 60,
        'duration_seconds': 60,
        'notify_enabled': True,
        'auto_analyze': True,
        'description': 'Linux node availability rule.',
        'sort_order': 600,
    },
    {
        'code': 'linux-high-cpu',
        'name': 'Linux High CPU Usage',
        'source_type': 'prometheus',
        'level': 'warning',
        'query_config': {'query': '(1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) by (instance)) * 100', 'value_path': 'value'},
        'condition': {'operator': '>', 'threshold': 85},
        'default_labels': {'integration': 'linux', 'service': 'linux'},
        'annotations': {'summary': 'Linux CPU usage is higher than 85%'},
        'interval_seconds': 60,
        'duration_seconds': 180,
        'notify_enabled': True,
        'auto_analyze': False,
        'description': 'Linux CPU usage rule.',
        'sort_order': 610,
    },
    {
        'code': 'linux-high-memory',
        'name': 'Linux High Memory Usage',
        'source_type': 'prometheus',
        'level': 'warning',
        'query_config': {'query': '(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100', 'value_path': 'value'},
        'condition': {'operator': '>', 'threshold': 85},
        'default_labels': {'integration': 'linux', 'service': 'linux'},
        'annotations': {'summary': 'Linux memory usage is higher than 85%'},
        'interval_seconds': 60,
        'duration_seconds': 180,
        'notify_enabled': True,
        'auto_analyze': False,
        'description': 'Linux memory usage rule.',
        'sort_order': 620,
    },
    {
        'code': 'linux-high-disk',
        'name': 'Linux High Disk Usage',
        'source_type': 'prometheus',
        'level': 'warning',
        'query_config': {'query': '(1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"}) * 100', 'value_path': 'value'},
        'condition': {'operator': '>', 'threshold': 85},
        'default_labels': {'integration': 'linux', 'service': 'linux'},
        'annotations': {'summary': 'Linux disk usage is higher than 85%'},
        'interval_seconds': 60,
        'duration_seconds': 300,
        'notify_enabled': True,
        'auto_analyze': False,
        'description': 'Linux disk usage rule.',
        'sort_order': 630,
    },
]


TEST_TEMPLATE_VALUES = {'test', '测试', '测试告警', '告警通知测试', '通知测试'}


def seed_template_bundles(apps, schema_editor):
    template_model = apps.get_model('ops', 'AlertRuleTemplate')
    for item in TEMPLATES:
        payload = dict(item)
        payload['is_builtin'] = True
        payload['is_enabled'] = True
        template_model.objects.update_or_create(code=item['code'], defaults=payload)

    channel_model = apps.get_model('ops', 'AlertNotificationChannel')
    for channel in channel_model.objects.all():
        update_fields = []
        if (channel.template_title or '').strip().lower() in TEST_TEMPLATE_VALUES:
            channel.template_title = ''
            update_fields.append('template_title')
        if (channel.template_body or '').strip().lower() in TEST_TEMPLATE_VALUES:
            channel.template_body = ''
            update_fields.append('template_body')
        if update_fields:
            channel.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0072_clear_test_alert_notification_templates'),
    ]

    operations = [
        migrations.RunPython(seed_template_bundles, migrations.RunPython.noop),
    ]
