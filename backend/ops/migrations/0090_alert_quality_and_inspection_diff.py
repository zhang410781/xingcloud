from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ops', '0089_derive_elk_log_level_when_unmapped')]

    operations = [
        migrations.AddField(model_name='alertrule', name='last_evaluation_duration_ms', field=models.PositiveIntegerField(blank=True, null=True, verbose_name='最近评估耗时毫秒')),
        migrations.AddField(model_name='alertrule', name='last_result_count', field=models.PositiveIntegerField(default=0, verbose_name='最近结果数')),
        migrations.AddField(model_name='alertrule', name='last_matched_count', field=models.PositiveIntegerField(default=0, verbose_name='最近命中数')),
        migrations.AddField(model_name='alertrule', name='last_matched_resource', field=models.CharField(blank=True, default='', max_length=256, verbose_name='最近命中对象')),
        migrations.AddField(model_name='alertrule', name='evaluation_error_count', field=models.PositiveIntegerField(default=0, verbose_name='评估错误次数')),
        migrations.AddField(model_name='alertrule', name='consecutive_error_count', field=models.PositiveIntegerField(default=0, verbose_name='连续评估错误次数')),
        migrations.AddField(model_name='alertrule', name='no_data_count', field=models.PositiveIntegerField(default=0, verbose_name='无数据次数')),
        migrations.AddField(model_name='alertrule', name='trigger_count', field=models.PositiveIntegerField(default=0, verbose_name='触发次数')),
        migrations.AddField(model_name='alertrule', name='flap_count', field=models.PositiveIntegerField(default=0, verbose_name='抖动次数')),
        migrations.AddField(model_name='alertrule', name='last_evaluation_error', field=models.TextField(blank=True, default='', verbose_name='最近评估错误')),
        migrations.AddField(model_name='inspectionreportschedule', name='notify_changes_only', field=models.BooleanField(default=True, verbose_name='仅推送新增或恶化项')),
        migrations.AddField(model_name='inspectionreportexecution', name='change_summary', field=models.JSONField(blank=True, default=dict, verbose_name='与上次巡检差异')),
        migrations.AlterField(model_name='alertrule', name='category', field=models.CharField(choices=[('server', '服务器'), ('k8s', 'Kubernetes'), ('storage', '存储'), ('database', '数据库'), ('network', '网络'), ('middleware', '中间件'), ('control_plane', '控制面'), ('workload', '工作负载')], db_index=True, default='server', max_length=16, verbose_name='分类')),
    ]
