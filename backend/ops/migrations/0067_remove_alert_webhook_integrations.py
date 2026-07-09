from django.db import migrations, models


def normalize_alert_sources(apps, schema_editor):
    Alert = apps.get_model('ops', 'Alert')
    AlertAction = apps.get_model('ops', 'AlertAction')
    Alert.objects.exclude(source_type='platform').update(source_type='platform')
    AlertAction.objects.filter(action='webhook').update(action='rule_evaluation')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0066_remove_tracing_runtime'),
    ]

    operations = [
        migrations.RunPython(normalize_alert_sources, noop),
        migrations.RemoveField(
            model_name='alert',
            name='integration',
        ),
        migrations.AlterField(
            model_name='alert',
            name='source_type',
            field=models.CharField(choices=[('platform', '平台告警规则')], default='platform', max_length=32, verbose_name='来源类型'),
        ),
        migrations.AlterField(
            model_name='alertaction',
            name='action',
            field=models.CharField(
                choices=[
                    ('rule_evaluation', '规则触发'),
                    ('notify', '发送通知'),
                    ('acknowledge', '确认'),
                    ('claim', '认领'),
                    ('unclaim', '取消认领'),
                    ('mute', '屏蔽'),
                    ('escalate', '升级'),
                    ('resolve', '恢复'),
                    ('close', '关闭'),
                    ('reopen', '重新打开'),
                    ('comment', '备注'),
                ],
                max_length=32,
                verbose_name='动作',
            ),
        ),
        migrations.DeleteModel(
            name='AlertIntegration',
        ),
    ]
