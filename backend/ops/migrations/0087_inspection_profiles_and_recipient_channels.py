from django.db import migrations, models


def normalize_profiles_and_channels(apps, schema_editor):
    InspectionReportSchedule = apps.get_model('ops', 'InspectionReportSchedule')
    AlertRecipient = apps.get_model('ops', 'AlertRecipient')

    InspectionReportSchedule.objects.filter(
        profile__in=['control_plane', 'node', 'workload', 'service'],
    ).update(profile='cluster')

    for recipient in AlertRecipient.objects.all().iterator():
        if recipient.preferred_channels:
            continue
        channels = []
        if recipient.email or (recipient.user_id and recipient.user and recipient.user.email):
            channels.append('email')
        if recipient.phone:
            channels.extend(['sms', 'voice'])
        if recipient.dingtalk_user_id:
            channels.append('dingtalk')
        if recipient.feishu_user_id:
            channels.append('feishu')
        if recipient.wecom_user_id:
            channels.append('wecom')
        if channels:
            recipient.preferred_channels = channels
            recipient.save(update_fields=['preferred_channels'])


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0086_inspection_report_schedules'),
    ]

    operations = [
        migrations.AddField(
            model_name='alertrecipient',
            name='preferred_channels',
            field=models.JSONField(blank=True, default=list, verbose_name='接收渠道'),
        ),
        migrations.RunPython(normalize_profiles_and_channels, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='inspectionreportschedule',
            name='profile',
            field=models.CharField(
                choices=[('cluster', '集群综合巡检'), ('server', '服务器巡检')],
                default='cluster',
                max_length=32,
                verbose_name='巡检范围',
            ),
        ),
    ]
