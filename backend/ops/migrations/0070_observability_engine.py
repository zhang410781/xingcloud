import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0069_remove_grafana_and_seed_environment_datasources'),
    ]

    operations = [
        migrations.AddField(
            model_name='logdatasource',
            name='last_check_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='最近检测时间'),
        ),
        migrations.AddField(
            model_name='logdatasource',
            name='last_check_latency_ms',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='最近检测延迟毫秒'),
        ),
        migrations.AddField(
            model_name='logdatasource',
            name='last_check_message',
            field=models.CharField(blank=True, default='', max_length=500, verbose_name='最近检测信息'),
        ),
        migrations.AddField(
            model_name='logdatasource',
            name='last_check_status',
            field=models.CharField(blank=True, default='', max_length=32, verbose_name='最近检测状态'),
        ),
        migrations.AddField(
            model_name='metricdatasource',
            name='last_check_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='最近检测时间'),
        ),
        migrations.AddField(
            model_name='metricdatasource',
            name='last_check_latency_ms',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='最近检测延迟毫秒'),
        ),
        migrations.AddField(
            model_name='metricdatasource',
            name='last_check_message',
            field=models.CharField(blank=True, default='', max_length=500, verbose_name='最近检测信息'),
        ),
        migrations.AddField(
            model_name='metricdatasource',
            name='last_check_status',
            field=models.CharField(blank=True, default='', max_length=32, verbose_name='最近检测状态'),
        ),
        migrations.CreateModel(
            name='AlertRuleState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fingerprint', models.CharField(db_index=True, max_length=128)),
                ('labels', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('active', 'Active'), ('resolved', 'Resolved'), ('error', 'Error')], default='pending', max_length=16)),
                ('first_seen_at', models.DateTimeField(blank=True, null=True)),
                ('last_seen_at', models.DateTimeField(blank=True, null=True)),
                ('last_value', models.FloatField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('rule', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='states', to='ops.alertrule')),
            ],
            options={
                'ordering': ['rule_id', 'fingerprint'],
            },
        ),
        migrations.CreateModel(
            name='ObservabilityDashboard',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=128, verbose_name='标题')),
                ('description', models.CharField(blank=True, default='', max_length=500, verbose_name='描述')),
                ('tags', models.JSONField(blank=True, default=list, verbose_name='标签')),
                ('layout', models.JSONField(blank=True, default=dict, verbose_name='布局')),
                ('is_builtin', models.BooleanField(default=False, verbose_name='内置看板')),
                ('is_enabled', models.BooleanField(default=True, verbose_name='启用')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '可观测看板',
                'verbose_name_plural': '可观测看板',
                'ordering': ['-is_builtin', 'title'],
            },
        ),
        migrations.CreateModel(
            name='ObservabilityDashboardPanel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.SlugField(blank=True, default='', max_length=128, verbose_name='面板标识')),
                ('title', models.CharField(max_length=128, verbose_name='标题')),
                ('chart_type', models.CharField(default='timeseries', max_length=32, verbose_name='图表类型')),
                ('datasource_type', models.CharField(choices=[('prometheus', 'Prometheus'), ('clickhouse', 'ClickHouse'), ('sla', 'SLA')], default='prometheus', max_length=32, verbose_name='数据源类型')),
                ('targets', models.JSONField(blank=True, default=list, verbose_name='查询目标')),
                ('options', models.JSONField(blank=True, default=dict, verbose_name='展示选项')),
                ('sort_order', models.PositiveIntegerField(default=100, verbose_name='排序')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('dashboard', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='panels', to='ops.observabilitydashboard', verbose_name='看板')),
            ],
            options={
                'verbose_name': '可观测看板面板',
                'verbose_name_plural': '可观测看板面板',
                'ordering': ['dashboard_id', 'sort_order', 'id'],
            },
        ),
        migrations.AddIndex(
            model_name='alertrulestate',
            index=models.Index(fields=['rule', 'status'], name='ops_ars_rule_status_idx'),
        ),
        migrations.AddIndex(
            model_name='alertrulestate',
            index=models.Index(fields=['last_seen_at'], name='ops_ars_last_seen_idx'),
        ),
        migrations.AddConstraint(
            model_name='alertrulestate',
            constraint=models.UniqueConstraint(fields=('rule', 'fingerprint'), name='uniq_ops_alert_rule_state'),
        ),
        migrations.AddIndex(
            model_name='observabilitydashboard',
            index=models.Index(fields=['is_enabled', 'is_builtin'], name='ops_ob_dash_enabled_idx'),
        ),
        migrations.AddIndex(
            model_name='observabilitydashboardpanel',
            index=models.Index(fields=['dashboard', 'sort_order'], name='ops_ob_panel_order_idx'),
        ),
        migrations.AddConstraint(
            model_name='observabilitydashboardpanel',
            constraint=models.UniqueConstraint(fields=('dashboard', 'key'), name='uniq_ops_ob_dash_panel_key'),
        ),
    ]
