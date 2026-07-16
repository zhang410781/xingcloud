from django.db import migrations, models
import django.db.models.deletion


def backfill_rule_sources(apps, schema_editor):
    AlertRule = apps.get_model('ops', 'AlertRule')
    MetricDataSource = apps.get_model('ops', 'MetricDataSource')

    templates = {}
    for rule in AlertRule.objects.all().iterator():
        if rule.source and rule.source != 'custom' and rule.code == rule.source:
            rule.is_template = True
            rule.is_enabled = False
            rule.save(update_fields=['is_template', 'is_enabled'])
            templates[rule.code] = rule

    for rule in AlertRule.objects.filter(is_template=False).iterator():
        query_config = rule.query_config if isinstance(rule.query_config, dict) else {}
        labels = rule.labels if isinstance(rule.labels, dict) else {}
        datasource = None
        datasource_id = query_config.get('metric_datasource_id') or query_config.get('datasource_id')
        if datasource_id:
            datasource = MetricDataSource.objects.filter(pk=datasource_id).first()
        if datasource is None and rule.source_type == 'prometheus':
            cluster_name = str(labels.get('cluster') or '').strip()
            environment = str(labels.get('environment') or '').strip()
            candidates = MetricDataSource.objects.filter(is_enabled=True)
            if cluster_name:
                candidates = candidates.filter(cluster_name=cluster_name)
            elif environment:
                candidates = candidates.filter(environment=environment)
            else:
                candidates = candidates.none()
            if candidates.count() == 1:
                datasource = candidates.first()
        template = templates.get(rule.source)
        update_fields = []
        if datasource is not None:
            rule.metric_datasource_id = datasource.id
            update_fields.append('metric_datasource')
        if template is not None and template.id != rule.id:
            rule.template_id = template.id
            update_fields.append('template')
        if update_fields:
            rule.save(update_fields=update_fields)

    k8s_templates = list(AlertRule.objects.filter(is_template=True, source_type='prometheus', category='k8s'))
    datasources = MetricDataSource.objects.filter(provider='prometheus', is_enabled=True)
    for datasource in datasources.iterator():
        for template in k8s_templates:
            if AlertRule.objects.filter(template_id=template.id, metric_datasource_id=datasource.id).exists():
                continue
            labels = dict(template.labels or {})
            if datasource.environment:
                labels['environment'] = datasource.environment
            if datasource.cluster_name:
                labels['cluster'] = datasource.cluster_name
            code = f'{template.code}-ds{datasource.id}'[:96]
            AlertRule.objects.create(
                name=f'{template.name} · {datasource.cluster_name or datasource.name}',
                code=code,
                category=template.category,
                source=template.code,
                is_template=False,
                template_id=template.id,
                metric_datasource_id=datasource.id,
                notify_config={},
                group_window=template.group_window,
                repeat_interval=template.repeat_interval,
                mute_schedule=template.mute_schedule,
                escalation_minutes=template.escalation_minutes,
                source_type=template.source_type,
                level=template.level,
                query_config=template.query_config,
                condition=template.condition,
                labels=labels,
                annotations=template.annotations,
                interval_seconds=template.interval_seconds,
                duration_seconds=template.duration_seconds,
                notify_enabled=template.notify_enabled,
                auto_analyze=template.auto_analyze,
                is_enabled=False,
                description=template.description,
            )


class Migration(migrations.Migration):
    dependencies = [
        ('ops', '0077_dashboard_log_datasource'),
    ]

    operations = [
        migrations.AddField(
            model_name='alertrule',
            name='is_template',
            field=models.BooleanField(db_index=True, default=False, verbose_name='规则模板'),
        ),
        migrations.AddField(
            model_name='alertrule',
            name='metric_datasource',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='alert_rules', to='ops.metricdatasource', verbose_name='指标数据源'),
        ),
        migrations.AddField(
            model_name='alertrule',
            name='template',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='instances', to='ops.alertrule', verbose_name='来源模板'),
        ),
        migrations.AddField(
            model_name='alertnotificationlog',
            name='policy_id',
            field=models.IntegerField(blank=True, null=True, verbose_name='通知策略ID'),
        ),
        migrations.CreateModel(
            name='AlertNotificationPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=128, verbose_name='策略名称')),
                ('matchers', models.JSONField(blank=True, default=list, verbose_name='标签匹配条件')),
                ('min_level', models.CharField(blank=True, default='', max_length=16, verbose_name='最低告警级别')),
                ('priority', models.IntegerField(db_index=True, default=100, verbose_name='优先级')),
                ('continue_matching', models.BooleanField(default=False, verbose_name='继续匹配后续策略')),
                ('group_by', models.JSONField(blank=True, default=list, verbose_name='聚合维度')),
                ('group_wait_seconds', models.PositiveIntegerField(default=30, verbose_name='首次聚合等待秒')),
                ('group_interval_seconds', models.PositiveIntegerField(default=300, verbose_name='同组通知间隔秒')),
                ('repeat_interval_minutes', models.PositiveIntegerField(default=30, verbose_name='重复通知间隔分钟')),
                ('mute_schedule', models.JSONField(blank=True, default=dict, verbose_name='静默时段')),
                ('inhibition_matchers', models.JSONField(blank=True, default=list, verbose_name='抑制条件')),
                ('escalation_steps', models.JSONField(blank=True, default=list, verbose_name='升级步骤')),
                ('notify_on_fire', models.BooleanField(default=True, verbose_name='发送触发通知')),
                ('notify_on_resolved', models.BooleanField(default=True, verbose_name='发送恢复通知')),
                ('is_enabled', models.BooleanField(default=True, verbose_name='启用')),
                ('description', models.CharField(blank=True, default='', max_length=255, verbose_name='说明')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('channels', models.ManyToManyField(blank=True, related_name='notification_policies', to='ops.alertnotificationchannel', verbose_name='通知渠道')),
                ('metric_datasource', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='alert_notification_policies', to='ops.metricdatasource', verbose_name='指标数据源')),
                ('recipient_groups', models.ManyToManyField(blank=True, related_name='notification_policies', to='ops.alertrecipientgroup', verbose_name='接收组')),
            ],
            options={
                'verbose_name': '告警通知策略',
                'verbose_name_plural': '告警通知策略',
                'ordering': ['priority', 'id'],
            },
        ),
        migrations.AddIndex(
            model_name='alertrule',
            index=models.Index(fields=['metric_datasource', 'is_template', 'is_enabled'], name='ops_ar_ds_tpl_enabled_idx'),
        ),
        migrations.AddConstraint(
            model_name='alertrule',
            constraint=models.UniqueConstraint(condition=models.Q(('is_template', False), ('metric_datasource__isnull', False), ('template__isnull', False)), fields=('template', 'metric_datasource'), name='uniq_ops_alert_rule_template_ds'),
        ),
        migrations.AddIndex(
            model_name='alertnotificationpolicy',
            index=models.Index(fields=['metric_datasource', 'is_enabled', 'priority'], name='ops_anp_ds_enabled_prio_idx'),
        ),
        migrations.RunPython(backfill_rule_sources, migrations.RunPython.noop),
    ]
