from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0078_alert_rule_datasource_notification_policy'),
    ]

    operations = [
        migrations.AddField(
            model_name='alertnotificationpolicy',
            name='notify_on_analysis',
            field=models.BooleanField(default=True, verbose_name='发送研判完成通知'),
        ),
        migrations.CreateModel(
            name='AlertAnalysis',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('pending', '待研判'), ('running', '研判中'), ('completed', '已完成'), ('partial', '部分完成'), ('failed', '失败')], db_index=True, default='pending', max_length=16, verbose_name='状态')),
                ('trigger', models.CharField(choices=[('first_active', '首次活跃'), ('severity_escalation', '级别升级'), ('manual', '人工触发')], default='first_active', max_length=32, verbose_name='触发原因')),
                ('evidence', models.JSONField(blank=True, default=dict, verbose_name='证据')),
                ('candidates', models.JSONField(blank=True, default=list, verbose_name='候选根因')),
                ('confidence', models.FloatField(blank=True, null=True, verbose_name='置信度')),
                ('result', models.JSONField(blank=True, default=dict, verbose_name='结构化结果')),
                ('root_cause', models.TextField(blank=True, default='', verbose_name='根因')),
                ('suggestion', models.TextField(blank=True, default='', verbose_name='建议')),
                ('provider', models.CharField(blank=True, default='', max_length=128, verbose_name='模型提供商')),
                ('model', models.CharField(blank=True, default='', max_length=128, verbose_name='模型')),
                ('retry_count', models.PositiveSmallIntegerField(default=0, verbose_name='已重试次数')),
                ('max_retries', models.PositiveSmallIntegerField(default=2, verbose_name='最大重试次数')),
                ('last_error', models.TextField(blank=True, default='', verbose_name='最近错误')),
                ('requested_by', models.CharField(blank=True, default='', max_length=128, verbose_name='触发人')),
                ('started_at', models.DateTimeField(blank=True, null=True, verbose_name='开始时间')),
                ('completed_at', models.DateTimeField(blank=True, null=True, verbose_name='完成时间')),
                ('next_retry_at', models.DateTimeField(blank=True, null=True, verbose_name='下次重试时间')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('alert', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='analyses', to='ops.alert', verbose_name='告警')),
            ],
            options={
                'verbose_name': '告警智能研判',
                'verbose_name_plural': '告警智能研判',
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='alertanalysis',
            index=models.Index(fields=['status', 'next_retry_at', 'created_at'], name='ops_aa_due_idx'),
        ),
        migrations.AddIndex(
            model_name='alertanalysis',
            index=models.Index(fields=['alert', 'created_at'], name='ops_aa_alert_created_idx'),
        ),
    ]
