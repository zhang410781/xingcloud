from django.db import migrations
from django.db.models import Q


DIRTY_TASK_NAMES = [
    '核心主机资源指标刷新',
]

DIRTY_HOST_MARKERS = [
    'airflow-worker-dev',
    'feature-x-dev-ecs',
]


def remove_dirty_task_notification_data(apps, schema_editor):
    HostTask = apps.get_model('ops', 'HostTask')
    HostTaskSchedule = apps.get_model('ops', 'HostTaskSchedule')
    HostTaskScheduleExecution = apps.get_model('ops', 'HostTaskScheduleExecution')

    task_query = Q(created_by='system-scheduler', name__in=DIRTY_TASK_NAMES)
    for marker in DIRTY_HOST_MARKERS:
        task_query |= Q(summary__icontains=marker)

    dirty_tasks = HostTask.objects.filter(task_query)
    HostTaskScheduleExecution.objects.filter(host_task__in=dirty_tasks).delete()
    dirty_tasks.delete()
    HostTaskSchedule.objects.filter(name__in=DIRTY_TASK_NAMES).delete()

    # Clean up eventwall data if the module still exists
    try:
        EventRecord = apps.get_model('eventwall', 'EventRecord')
        EventEnvironment = apps.get_model('eventwall', 'EventEnvironment')
        event_query = Q(environment='dev') | Q(resource_name__in=DIRTY_TASK_NAMES)
        for marker in DIRTY_HOST_MARKERS:
            event_query |= Q(summary__icontains=marker)
        EventRecord.objects.filter(event_query).delete()
        EventEnvironment.objects.filter(
            Q(code__in=['dev', 'development', 'zhengzhou-dev']) | Q(name__in=['dev', '开发环境', '郑州开发环境']),
            last_seen_at__isnull=True,
        ).delete()
    except LookupError:
        # eventwall module has been removed
        pass


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0061_taskresource_asset_registration_fields'),
    ]

    operations = [
        migrations.RunPython(remove_dirty_task_notification_data, migrations.RunPython.noop),
    ]
