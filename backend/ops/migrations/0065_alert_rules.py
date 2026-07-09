from django.db import migrations, models
import django.db.models.deletion


ALERT_RULE_TEMPLATE_CODES = [
    'k8s-node-not-ready',
    'k8s-pod-crashloop',
    'k8s-service-no-endpoints',
    'clickhouse-error-log-spike',
    'prometheus-target-down',
    'sla-monthly-risk',
]


def seed_alert_rule_templates(apps, schema_editor):
    AlertRuleTemplate = apps.get_model('ops', 'AlertRuleTemplate')
    templates = [
        {
            'name': 'K8S 节点 NotReady',
            'code': 'k8s-node-not-ready',
            'source_type': 'k8s',
            'level': 'critical',
            'query_config': {'resource': 'nodes', 'field': 'conditions.Ready'},
            'condition': {'status': 'False', 'duration_seconds': 300},
            'default_labels': {'product': 'container-platform', 'resource_type': 'node'},
            'annotations': {'summary': 'K8S 节点不可用', 'ai_hint': '检查 kubelet、容器运行时、节点网络和磁盘压力。'},
            'interval_seconds': 60,
            'duration_seconds': 300,
            'sort_order': 10,
            'description': '平台巡检 K8S 节点 Ready 状态，持续异常后生成告警事件。',
        },
        {
            'name': 'K8S Pod CrashLoopBackOff',
            'code': 'k8s-pod-crashloop',
            'source_type': 'k8s',
            'level': 'warning',
            'query_config': {'resource': 'pods', 'field': 'container_statuses'},
            'condition': {'waiting_reason': 'CrashLoopBackOff', 'restart_count_gte': 3},
            'default_labels': {'product': 'container-platform', 'resource_type': 'pod'},
            'annotations': {'summary': 'Pod 持续重启', 'ai_hint': '关联最近容器日志、事件、镜像拉取和探针配置。'},
            'interval_seconds': 60,
            'duration_seconds': 180,
            'sort_order': 20,
            'description': '平台巡检 Pod 容器状态，发现持续重启后生成告警事件。',
        },
        {
            'name': 'K8S Service 无可用 Endpoint',
            'code': 'k8s-service-no-endpoints',
            'source_type': 'k8s',
            'level': 'warning',
            'query_config': {'resource': 'endpoints'},
            'condition': {'ready_address_count': 0, 'duration_seconds': 180},
            'default_labels': {'product': 'container-platform', 'resource_type': 'service'},
            'annotations': {'summary': 'Service 没有可用后端', 'ai_hint': '检查 selector、Pod Ready 状态和 EndpointSlice。'},
            'interval_seconds': 60,
            'duration_seconds': 180,
            'sort_order': 30,
            'description': '平台巡检 Service Endpoint，持续为空时生成告警事件。',
        },
        {
            'name': 'ClickHouse ERROR 日志突增',
            'code': 'clickhouse-error-log-spike',
            'source_type': 'clickhouse',
            'level': 'warning',
            'query_config': {'collection': 'container-logs', 'window': '5m', 'level_field': 'log_level'},
            'condition': {'level': 'ERROR', 'count_gte': 20},
            'default_labels': {'product': 'application', 'resource_type': 'log'},
            'annotations': {'summary': 'ERROR 日志数量超过阈值', 'ai_hint': '汇总 Top 服务、Pod、错误栈和最近变更。'},
            'interval_seconds': 60,
            'duration_seconds': 0,
            'sort_order': 40,
            'description': '平台查询 ClickHouse 日志集合，按时间窗口检测 ERROR 日志突增。',
        },
        {
            'name': 'Prometheus Target Down',
            'code': 'prometheus-target-down',
            'source_type': 'prometheus',
            'level': 'critical',
            'query_config': {'promql': 'up == 0'},
            'condition': {'operator': '>', 'threshold': 0, 'duration_seconds': 300},
            'default_labels': {'product': 'monitoring', 'resource_type': 'target'},
            'annotations': {'summary': '监控目标不可达', 'ai_hint': '检查 exporter、ServiceMonitor、网络连通性和目标实例。'},
            'interval_seconds': 60,
            'duration_seconds': 300,
            'sort_order': 50,
            'description': '平台查询 Prometheus 兼容指标源，发现 target down 后生成告警事件。',
        },
        {
            'name': '本月 SLA 达成风险',
            'code': 'sla-monthly-risk',
            'source_type': 'sla',
            'level': 'critical',
            'query_config': {'scope': 'monthly', 'target_percent': 99.96},
            'condition': {'status_in': ['risk', 'failed']},
            'default_labels': {'product': 'sla', 'resource_type': 'sla'},
            'annotations': {'summary': '本月 SLA 存在达成风险', 'ai_hint': '关联灾难级事件持续时间、影响产品和工单处理及时性。'},
            'interval_seconds': 300,
            'duration_seconds': 0,
            'sort_order': 60,
            'description': '平台基于 SLA 口径检测本月达标风险。',
        },
    ]
    for item in templates:
        defaults = {
            **item,
            'notify_enabled': True,
            'auto_analyze': True,
            'is_builtin': True,
            'is_enabled': True,
        }
        code = defaults.pop('code')
        AlertRuleTemplate.objects.update_or_create(code=code, defaults=defaults)


def remove_alert_rule_templates(apps, schema_editor):
    AlertRuleTemplate = apps.get_model('ops', 'AlertRuleTemplate')
    AlertRuleTemplate.objects.filter(code__in=ALERT_RULE_TEMPLATE_CODES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0064_clickhouse_collections'),
    ]

    operations = [
        migrations.AlterField(
            model_name='alert',
            name='source_type',
            field=models.CharField(choices=[('prometheus', 'Prometheus Alertmanager'), ('zabbix', 'Zabbix'), ('nightingale', '夜莺'), ('aliyun', '阿里云监控'), ('platform', '平台告警规则'), ('generic', '通用 Webhook')], default='generic', max_length=32, verbose_name='来源类型'),
        ),
        migrations.AlterField(
            model_name='alertintegration',
            name='provider',
            field=models.CharField(choices=[('prometheus', 'Prometheus Alertmanager'), ('zabbix', 'Zabbix'), ('nightingale', '夜莺'), ('aliyun', '阿里云监控'), ('platform', '平台告警规则'), ('generic', '通用 Webhook')], max_length=32, verbose_name='接入类型'),
        ),
        migrations.AlterField(
            model_name='alertaction',
            name='action',
            field=models.CharField(choices=[('webhook', 'Webhook 接入'), ('rule_evaluation', '规则触发'), ('notify', '发送通知'), ('acknowledge', '确认'), ('claim', '认领'), ('unclaim', '取消认领'), ('mute', '屏蔽'), ('escalate', '升级'), ('resolve', '恢复'), ('close', '关闭'), ('reopen', '重新打开'), ('comment', '备注')], max_length=32, verbose_name='动作'),
        ),
        migrations.AlterField(
            model_name='alertinteractiontoken',
            name='action',
            field=models.CharField(choices=[('webhook', 'Webhook 接入'), ('rule_evaluation', '规则触发'), ('notify', '发送通知'), ('acknowledge', '确认'), ('claim', '认领'), ('unclaim', '取消认领'), ('mute', '屏蔽'), ('escalate', '升级'), ('resolve', '恢复'), ('close', '关闭'), ('reopen', '重新打开'), ('comment', '备注')], max_length=32, verbose_name='动作'),
        ),
        migrations.CreateModel(
            name='AlertRuleTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=128, verbose_name='模板名称')),
                ('code', models.SlugField(blank=True, default='', max_length=96, unique=True, verbose_name='模板编码')),
                ('source_type', models.CharField(choices=[('prometheus', 'Prometheus 指标'), ('clickhouse', 'ClickHouse 日志'), ('k8s', 'K8S 资源/事件'), ('sla', 'SLA'), ('platform', '平台内置')], max_length=32, verbose_name='数据源类型')),
                ('level', models.CharField(choices=[('critical', '严重'), ('warning', '警告'), ('info', '信息')], default='warning', max_length=16, verbose_name='默认级别')),
                ('query_config', models.JSONField(blank=True, default=dict, verbose_name='查询配置')),
                ('condition', models.JSONField(blank=True, default=dict, verbose_name='触发条件')),
                ('default_labels', models.JSONField(blank=True, default=dict, verbose_name='默认标签')),
                ('annotations', models.JSONField(blank=True, default=dict, verbose_name='默认注解')),
                ('interval_seconds', models.PositiveIntegerField(default=60, verbose_name='默认巡检间隔秒')),
                ('duration_seconds', models.PositiveIntegerField(default=0, verbose_name='默认持续时间秒')),
                ('notify_enabled', models.BooleanField(default=True, verbose_name='默认通知')),
                ('auto_analyze', models.BooleanField(default=True, verbose_name='默认 AI 研判')),
                ('is_builtin', models.BooleanField(default=False, verbose_name='内置模板')),
                ('is_enabled', models.BooleanField(default=True, verbose_name='启用')),
                ('sort_order', models.PositiveIntegerField(default=100, verbose_name='排序')),
                ('description', models.CharField(blank=True, default='', max_length=255, verbose_name='说明')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '告警规则模板',
                'verbose_name_plural': '告警规则模板',
                'ordering': ['sort_order', 'source_type', 'name'],
            },
        ),
        migrations.CreateModel(
            name='AlertRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=128, verbose_name='规则名称')),
                ('code', models.SlugField(blank=True, default='', max_length=96, unique=True, verbose_name='规则编码')),
                ('source_type', models.CharField(choices=[('prometheus', 'Prometheus 指标'), ('clickhouse', 'ClickHouse 日志'), ('k8s', 'K8S 资源/事件'), ('sla', 'SLA'), ('platform', '平台内置')], max_length=32, verbose_name='数据源类型')),
                ('level', models.CharField(choices=[('critical', '严重'), ('warning', '警告'), ('info', '信息')], default='warning', max_length=16, verbose_name='级别')),
                ('query_config', models.JSONField(blank=True, default=dict, verbose_name='查询配置')),
                ('condition', models.JSONField(blank=True, default=dict, verbose_name='触发条件')),
                ('labels', models.JSONField(blank=True, default=dict, verbose_name='标签')),
                ('annotations', models.JSONField(blank=True, default=dict, verbose_name='注解')),
                ('interval_seconds', models.PositiveIntegerField(default=60, verbose_name='巡检间隔秒')),
                ('duration_seconds', models.PositiveIntegerField(default=0, verbose_name='持续时间秒')),
                ('notify_enabled', models.BooleanField(default=True, verbose_name='命中后通知')),
                ('auto_analyze', models.BooleanField(default=True, verbose_name='命中后 AI 研判')),
                ('is_enabled', models.BooleanField(default=True, verbose_name='启用')),
                ('last_evaluated_at', models.DateTimeField(blank=True, null=True, verbose_name='最近评估时间')),
                ('last_triggered_at', models.DateTimeField(blank=True, null=True, verbose_name='最近触发时间')),
                ('description', models.CharField(blank=True, default='', max_length=255, verbose_name='说明')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('template', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='rules', to='ops.alertruletemplate', verbose_name='规则模板')),
            ],
            options={
                'verbose_name': '告警规则',
                'verbose_name_plural': '告警规则',
                'ordering': ['source_type', 'name'],
            },
        ),
        migrations.AddIndex(
            model_name='alertruletemplate',
            index=models.Index(fields=['source_type', 'is_enabled'], name='ops_ar_tpl_src_enabled_idx'),
        ),
        migrations.AddIndex(
            model_name='alertruletemplate',
            index=models.Index(fields=['is_builtin', 'sort_order'], name='ops_ar_tpl_builtin_idx'),
        ),
        migrations.AddIndex(
            model_name='alertrule',
            index=models.Index(fields=['source_type', 'is_enabled'], name='ops_ar_src_enabled_idx'),
        ),
        migrations.AddIndex(
            model_name='alertrule',
            index=models.Index(fields=['last_evaluated_at', 'last_triggered_at'], name='ops_ar_eval_trigger_idx'),
        ),
        migrations.RunPython(seed_alert_rule_templates, remove_alert_rule_templates),
    ]
