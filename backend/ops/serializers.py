import re
import uuid

from django.contrib.auth import get_user_model
from rest_framework import serializers

from cmdb.models import CIRelation, ConfigItem, ResourceNode

from .host_task_schedules import CronExpressionError, compute_next_run, preview_next_runs, validate_cron_expression
from .models import (
    Alert,
    AlertAction,
    AlertClaim,
    AlertInteractionToken,
    AlertNotificationChannel,
    AlertNotificationLog,
    AlertNotificationPolicy,
    AlertRecipient,
    AlertRecipientGroup,
    AlertRule,
    AlertSilence,
    Deployment,
    DeploymentApprovalFlow,
    DeploymentApprovalNode,
    DeploymentApprovalStep,
    DockerHost,
    Host,
    HostTask,
    HostTaskExecution,
    HostTaskSchedule,
    HostTaskScheduleExecution,
    HostTaskTemplate,
    K8sCluster,
    LogDataSource,
    LogEntry,
    MetricDataSource,
    NginxCertificate,
    NginxDomain,
    NginxEnvironment,
    NginxRoute,
    ObservabilityDashboard,
    ObservabilityDashboardPanel,
    TransactionTicket,
    TaskResource,
    TaskResourceGroup,
)


User = get_user_model()

LOG_SENSITIVE_KEYS = {
    'password',
    'api_key',
    'token',
    'bearer_token',
    'authorization',
    'client_secret',
}

METRIC_SENSITIVE_KEYS = {
    'password',
    'prometheus.password',
    'token',
    'bearer_token',
    'api_key',
    'authorization',
    'client_secret',
}


def normalize_json_object(value):
    return value if isinstance(value, dict) else {}


def mask_sensitive_config(value, sensitive_keys):
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in sensitive_keys:
                masked[key] = 'configured' if item else ''
            else:
                masked[key] = mask_sensitive_config(item, sensitive_keys)
        return masked
    if isinstance(value, list):
        return [mask_sensitive_config(item, sensitive_keys) for item in value]
    return value


def validate_host_task_payload(task_type, payload):
    payload = normalize_json_object(payload)
    if task_type == HostTask.TASK_RUN_COMMAND and not (payload.get('command') or '').strip():
        raise serializers.ValidationError({'payload': '请填写需要执行的命令'})
    if task_type == HostTask.TASK_RUN_PLAYBOOK and not (payload.get('playbook_content') or '').strip():
        raise serializers.ValidationError({'payload': '请填写 Playbook 内容'})
    if task_type == HostTask.TASK_SERVICE_STATUS and not (payload.get('service_name') or '').strip():
        raise serializers.ValidationError({'payload': '请填写需要巡检的服务名'})
    if task_type == HostTask.TASK_K8S_POD_EXEC and not (payload.get('command') or '').strip():
        raise serializers.ValidationError({'payload': '请填写需要在 Pod 内执行的命令'})
    if task_type == HostTask.TASK_K8S_SCALE_WORKLOAD:
        workload_type = (payload.get('workload_type') or '').strip().lower()
        if workload_type not in ('deployment', 'statefulset'):
            raise serializers.ValidationError({'payload': 'K8s 伸缩任务仅支持 Deployment 或 StatefulSet'})
        try:
            replicas = int(payload.get('replicas'))
        except (TypeError, ValueError):
            raise serializers.ValidationError({'payload': '请填写合法的副本数'})
        if replicas < 0:
            raise serializers.ValidationError({'payload': '副本数不能小于 0'})
    return payload


def normalize_schedule_hosts(value):
    value = value or []
    return list(dict.fromkeys(int(item) for item in value if item))


def validate_schedule_definition(attrs, instance=None):
    schedule_type = attrs.get('schedule_type') or getattr(instance, 'schedule_type', HostTaskSchedule.SCHEDULE_TYPE_CRON)
    timezone_name = attrs.get('timezone') or getattr(instance, 'timezone', 'Asia/Shanghai')
    cron_expression = (attrs.get('cron_expression') if 'cron_expression' in attrs else getattr(instance, 'cron_expression', '')) or ''
    interval_seconds = attrs.get('interval_seconds') if 'interval_seconds' in attrs else getattr(instance, 'interval_seconds', None)
    run_at = attrs.get('run_at') if 'run_at' in attrs else getattr(instance, 'run_at', None)

    if schedule_type == HostTaskSchedule.SCHEDULE_TYPE_CRON:
        if not str(cron_expression).strip():
            raise serializers.ValidationError({'cron_expression': '请填写 Cron 表达式'})
        try:
            validate_cron_expression(cron_expression)
        except CronExpressionError as exc:
            raise serializers.ValidationError({'cron_expression': str(exc)}) from exc
        attrs['interval_seconds'] = None
    elif schedule_type == HostTaskSchedule.SCHEDULE_TYPE_INTERVAL:
        if not interval_seconds:
            raise serializers.ValidationError({'interval_seconds': '请填写间隔秒数'})
        if int(interval_seconds) < 60:
            raise serializers.ValidationError({'interval_seconds': '间隔任务至少间隔 60 秒'})
        attrs['cron_expression'] = ''
    elif schedule_type == HostTaskSchedule.SCHEDULE_TYPE_ONCE:
        if not run_at:
            raise serializers.ValidationError({'run_at': '请选择执行时间'})
        attrs['cron_expression'] = ''
        attrs['interval_seconds'] = None
    else:
        raise serializers.ValidationError({'schedule_type': '不支持的调度类型'})

    preview_source = {
        'schedule_type': schedule_type,
        'cron_expression': attrs.get('cron_expression', cron_expression),
        'interval_seconds': attrs.get('interval_seconds', interval_seconds),
        'run_at': attrs.get('run_at', run_at),
        'timezone': timezone_name,
    }
    attrs['computed_next_run_at'] = compute_next_run(preview_source)
    return attrs


class HostSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_display = serializers.SerializerMethodField()

    class Meta:
        model = Host
        fields = '__all__'

    def get_environment_display(self, obj):
        return obj.get_environment_display() if obj.environment else ''

    def validate(self, attrs):
        business_line = (attrs.get('business_line') if 'business_line' in attrs else getattr(self.instance, 'business_line', '')) or ''
        environment = (attrs.get('environment') if 'environment' in attrs else getattr(self.instance, 'environment', '')) or ''

        business_line = business_line.strip()
        if business_line and not ResourceNode.objects.filter(node_type='biz', name=business_line).exists():
            raise serializers.ValidationError({'business_line': '所选系统未在资源树中配置'})

        if environment:
            if not business_line:
                raise serializers.ValidationError({'environment': '请先选择系统'})
            if not ResourceNode.objects.filter(node_type='env', parent__name=business_line, name=environment).exists():
                raise serializers.ValidationError({'environment': '所选环境未在当前系统下配置'})

        attrs['business_line'] = business_line
        return attrs


class LogDataSourceSerializer(serializers.ModelSerializer):
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)

    class Meta:
        model = LogDataSource
        fields = '__all__'

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['config'] = mask_sensitive_config(data.get('config') or {}, LOG_SENSITIVE_KEYS)
        return data


class MetricDataSourceSerializer(serializers.ModelSerializer):
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)

    class Meta:
        model = MetricDataSource
        fields = '__all__'

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['config'] = mask_sensitive_config(data.get('config') or {}, METRIC_SENSITIVE_KEYS)
        return data


class ObservabilityDashboardPanelSerializer(serializers.ModelSerializer):
    datasource_type_display = serializers.CharField(source='get_datasource_type_display', read_only=True)

    class Meta:
        model = ObservabilityDashboardPanel
        fields = [
            'id',
            'key',
            'title',
            'chart_type',
            'datasource_type',
            'datasource_type_display',
            'targets',
            'options',
            'sort_order',
            'created_at',
            'updated_at',
        ]

    def validate_targets(self, value):
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('targets must be a list')
        return value

    def validate_options(self, value):
        return value if isinstance(value, dict) else {}


class ObservabilityDashboardSerializer(serializers.ModelSerializer):
    panels = ObservabilityDashboardPanelSerializer(many=True, required=False)

    class Meta:
        model = ObservabilityDashboard
        fields = [
            'id',
            'title',
            'description',
            'tags',
            'layout',
            'is_builtin',
            'is_enabled',
            'panels',
            'created_at',
            'updated_at',
        ]

    def validate_tags(self, value):
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('tags must be a list')
        return value

    def validate_layout(self, value):
        return value if isinstance(value, dict) else {}

    def _replace_panels(self, dashboard, panels):
        if panels is None:
            return
        dashboard.panels.all().delete()
        for index, panel in enumerate(panels):
            ObservabilityDashboardPanel.objects.create(
                dashboard=dashboard,
                sort_order=panel.get('sort_order') or index + 1,
                **{key: value for key, value in panel.items() if key != 'sort_order'},
            )

    def create(self, validated_data):
        panels = validated_data.pop('panels', [])
        dashboard = ObservabilityDashboard.objects.create(**validated_data)
        self._replace_panels(dashboard, panels)
        return dashboard

    def update(self, instance, validated_data):
        panels = validated_data.pop('panels', None)
        instance = super().update(instance, validated_data)
        self._replace_panels(instance, panels)
        return instance


class DockerHostSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = DockerHost
        fields = '__all__'
        extra_kwargs = {
            'ssh_password': {
                'write_only': True,
                'required': False,
                'allow_blank': True,
            },
        }


class K8sClusterSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = K8sCluster
        fields = [
            'id',
            'name',
            'api_server',
            'kubeconfig',
            'user_type',
            'status',
            'status_display',
            'description',
            'created_at',
            'updated_at',
        ]
        extra_kwargs = {
            'kubeconfig': {
                'write_only': True,
                'required': False,
                'allow_blank': True,
            },
        }


class TaskResourceGroupSerializer(serializers.ModelSerializer):
    group_type_display = serializers.CharField(source='get_group_type_display', read_only=True)
    parent_name = serializers.CharField(source='parent.name', read_only=True)
    event_environment_code = serializers.SerializerMethodField()
    event_environment_name = serializers.SerializerMethodField()

    def get_event_environment_code(self, obj):
        return str(obj.event_environment or '')

    def get_event_environment_name(self, obj):
        return ''

    class Meta:
        model = TaskResourceGroup
        fields = [
            'id',
            'name',
            'code',
            'group_type',
            'group_type_display',
            'parent',
            'parent_name',
            'event_environment',
            'event_environment_code',
            'event_environment_name',
            'description',
            'sort_order',
            'created_by',
            'updated_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        group_type = attrs.get('group_type') or getattr(self.instance, 'group_type', '')
        parent = attrs.get('parent') if 'parent' in attrs else getattr(self.instance, 'parent', None)
        name = (attrs.get('name') if 'name' in attrs else getattr(self.instance, 'name', '')) or ''
        attrs['name'] = name.strip()
        attrs['code'] = ((attrs.get('code') if 'code' in attrs else getattr(self.instance, 'code', '')) or '').strip()
        if not attrs['name']:
            raise serializers.ValidationError({'name': '请填写节点名称'})
        if group_type == TaskResourceGroup.GROUP_ENVIRONMENT:
            attrs['parent'] = None
        elif group_type == TaskResourceGroup.GROUP_SYSTEM:
            attrs['event_environment'] = None
            if not parent:
                raise serializers.ValidationError({'parent': '系统必须归属到一个环境'})
            if parent.group_type != TaskResourceGroup.GROUP_ENVIRONMENT:
                raise serializers.ValidationError({'parent': '系统的上级节点必须是环境'})
        else:
            raise serializers.ValidationError({'group_type': '不支持的节点类型'})
        return attrs


class TaskResourceSerializer(serializers.ModelSerializer):
    resource_type_display = serializers.CharField(source='get_resource_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_name = serializers.CharField(source='environment.name', read_only=True)
    system_name = serializers.CharField(source='system.name', read_only=True)
    cluster_name = serializers.CharField(source='cluster.name', read_only=True)
    endpoint = serializers.SerializerMethodField()
    hostname = serializers.CharField(source='name', read_only=True)
    business_line = serializers.CharField(source='system.name', read_only=True)
    admin_user = serializers.CharField(source='owner', read_only=True)
    environment_display = serializers.CharField(source='environment.name', read_only=True)

    class Meta:
        model = TaskResource
        fields = [
            'id',
            'name',
            'hostname',
            'resource_type',
            'resource_type_display',
            'environment',
            'environment_name',
            'environment_display',
            'system',
            'system_name',
            'business_line',
            'status',
            'status_display',
            'asset_environment',
            'ip_address',
            'ssh_port',
            'ssh_user',
            'ssh_password',
            'cluster',
            'cluster_name',
            'namespace',
            'endpoint',
            'owner',
            'admin_user',
            'project_owner',
            'description',
            'metadata',
            'created_by',
            'updated_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']
        extra_kwargs = {
            'name': {'required': False, 'allow_blank': True},
            'ssh_password': {'write_only': True, 'required': False, 'allow_blank': True},
        }

    def to_internal_value(self, data):
        if data.get('resource_type') == TaskResource.RESOURCE_K8S and data.get('ip_address') in ('', None):
            data = data.copy()
            data['ip_address'] = None
        return super().to_internal_value(data)

    def get_endpoint(self, obj):
        if obj.resource_type == TaskResource.RESOURCE_K8S:
            return obj.cluster.name if obj.cluster else ''
        return str(obj.ip_address or '')

    def validate(self, attrs):
        resource_type = attrs.get('resource_type') or getattr(self.instance, 'resource_type', TaskResource.RESOURCE_HOST)
        environment = attrs.get('environment') if 'environment' in attrs else getattr(self.instance, 'environment', None)
        system = attrs.get('system') if 'system' in attrs else getattr(self.instance, 'system', None)
        name = (attrs.get('name') if 'name' in attrs else getattr(self.instance, 'name', '')) or ''
        if resource_type == TaskResource.RESOURCE_K8S and not name.strip():
            cluster_for_name = attrs.get('cluster') if 'cluster' in attrs else getattr(self.instance, 'cluster', None)
            if cluster_for_name:
                name = cluster_for_name.name
        attrs['name'] = name.strip()
        if not attrs['name']:
            raise serializers.ValidationError({'name': '请填写资源名称'})
        if not environment or environment.group_type != TaskResourceGroup.GROUP_ENVIRONMENT:
            raise serializers.ValidationError({'environment': '请选择环境'})
        if system:
            if system.group_type != TaskResourceGroup.GROUP_SYSTEM:
                raise serializers.ValidationError({'system': '请选择系统'})
            if system.parent_id != environment.id:
                raise serializers.ValidationError({'system': '系统必须归属到所选环境'})
        if resource_type == TaskResource.RESOURCE_HOST:
            ip_address = attrs.get('ip_address') if 'ip_address' in attrs else getattr(self.instance, 'ip_address', None)
            if not ip_address:
                raise serializers.ValidationError({'ip_address': '请填写主机 IP'})
            attrs['cluster'] = None
            attrs['namespace'] = ''
        elif resource_type == TaskResource.RESOURCE_K8S:
            cluster = attrs.get('cluster') if 'cluster' in attrs else getattr(self.instance, 'cluster', None)
            if not cluster:
                raise serializers.ValidationError({'cluster': '请选择 K8s 集群'})
            attrs['name'] = cluster.name
            attrs['ip_address'] = None
            attrs['ssh_password'] = ''
            attrs['namespace'] = ''
        else:
            raise serializers.ValidationError({'resource_type': '不支持的资源类型'})
        return attrs


class HostTaskExecutionSerializer(serializers.ModelSerializer):
    status_display = serializers.SerializerMethodField()

    class Meta:
        model = HostTaskExecution
        fields = [
            'id',
            'target_type',
            'host',
            'host_name',
            'host_ip',
            'target_id',
            'target_name',
            'target_namespace',
            'target_kind',
            'status',
            'status_display',
            'command',
            'output',
            'error_message',
            'duration_ms',
            'started_at',
            'finished_at',
            'created_at',
        ]

    def get_status_display(self, obj):
        if obj.status == 'running':
            return '执行中'
        return obj.get_status_display()


class HostTaskSerializer(serializers.ModelSerializer):
    target_type_display = serializers.CharField(source='get_target_type_display', read_only=True)
    task_type_display = serializers.CharField(source='get_task_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    lifecycle_status_display = serializers.CharField(source='get_lifecycle_status_display', read_only=True)
    risk_level_display = serializers.CharField(source='get_risk_level_display', read_only=True)
    execution_mode_display = serializers.CharField(source='get_execution_mode_display', read_only=True)
    trigger_source_display = serializers.CharField(source='get_trigger_source_display', read_only=True)
    environment_name = serializers.SerializerMethodField()
    environment_display = serializers.SerializerMethodField()
    success_rate = serializers.SerializerMethodField()

    class Meta:
        model = HostTask
        fields = [
            'id',
            'name',
            'target_type',
            'target_type_display',
            'task_type',
            'task_type_display',
            'execution_mode',
            'execution_mode_display',
            'trigger_source',
            'trigger_source_display',
            'environment_name',
            'environment_display',
            'lifecycle_status',
            'lifecycle_status_display',
            'risk_level',
            'risk_level_display',
            'correlation_id',
            'source_context',
            'status',
            'status_display',
            'description',
            'payload',
            'selection_filters',
            'target_snapshot',
            'execution_strategy',
            'timeout_seconds',
            'target_count',
            'success_count',
            'failed_count',
            'skipped_count',
            'success_rate',
            'cancel_requested',
            'cancel_requested_by',
            'cancel_requested_at',
            'created_by',
            'summary',
            'started_at',
            'finished_at',
            'created_at',
            'updated_at',
        ]

    def get_success_rate(self, obj):
        if not obj.target_count:
            return 0
        return round((obj.success_count / obj.target_count) * 100, 1)

    def _environment_values(self, obj):
        values = []

        def append(value):
            text = str(value or '').strip()
            if text and not text.isdigit() and text not in values:
                values.append(text)

        source_context = obj.source_context or {}
        selection_filters = obj.selection_filters or {}
        append(source_context.get('resource_environment'))
        append(source_context.get('environment_name'))
        append(source_context.get('environment'))
        append(source_context.get('knowledge_environment'))
        append(selection_filters.get('environment_name'))
        append(selection_filters.get('resource_environment'))
        append(selection_filters.get('environment'))
        for item in obj.target_snapshot or []:
            append(item.get('environment_name'))
            append(item.get('environment'))
            append(item.get('env'))
        if obj.target_type == HostTask.TARGET_K8S and not values:
            resource_ids = []
            for item in obj.target_snapshot or []:
                for key in ['resource_id', 'task_resource_id', 'cluster_id']:
                    try:
                        value = int(item.get(key) or 0)
                    except (TypeError, ValueError):
                        value = 0
                    if value > 0 and value not in resource_ids:
                        resource_ids.append(value)
            if resource_ids:
                for resource in TaskResource.objects.select_related('environment').filter(
                    id__in=resource_ids,
                    resource_type=TaskResource.RESOURCE_K8S,
                ):
                    append(resource.environment.name if resource.environment_id else '')
        return values

    def get_environment_name(self, obj):
        values = self._environment_values(obj)
        return values[0] if values else ''

    def get_environment_display(self, obj):
        values = self._environment_values(obj)
        if not values:
            return ''
        if len(values) == 1:
            return values[0]
        return f'{values[0]} 等 {len(values)} 个'


class HostTaskDetailSerializer(HostTaskSerializer):
    executions = HostTaskExecutionSerializer(many=True, read_only=True)

    class Meta(HostTaskSerializer.Meta):
        fields = HostTaskSerializer.Meta.fields + ['executions']


class HostTaskTemplateSerializer(serializers.ModelSerializer):
    target_type_display = serializers.CharField(source='get_target_type_display', read_only=True)
    task_type_display = serializers.CharField(source='get_task_type_display', read_only=True)
    execution_mode_display = serializers.CharField(source='get_execution_mode_display', read_only=True)

    class Meta:
        model = HostTaskTemplate
        fields = [
            'id',
            'name',
            'target_type',
            'target_type_display',
            'task_type',
            'task_type_display',
            'execution_mode',
            'execution_mode_display',
            'description',
            'payload',
            'execution_strategy',
            'timeout_seconds',
            'is_builtin',
            'created_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['is_builtin', 'created_by', 'created_at', 'updated_at']

    def validate_payload(self, value):
        return normalize_json_object(value)

    def validate(self, attrs):
        task_type = attrs.get('task_type') or getattr(self.instance, 'task_type', '')
        target_type = attrs.get('target_type') or getattr(self.instance, 'target_type', HostTask.TARGET_HOST)
        execution_mode = attrs.get('execution_mode') or getattr(self.instance, 'execution_mode', HostTask.EXECUTION_MODE_SSH)
        validate_host_task_payload(task_type, attrs.get('payload') or {})
        if execution_mode == HostTask.EXECUTION_MODE_K8S_API and not str(task_type).startswith('k8s_'):
            raise serializers.ValidationError({'execution_mode': '只有 K8s 命令可以使用 K8s API'})
        if task_type.startswith('k8s_'):
            attrs['target_type'] = HostTask.TARGET_K8S
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_K8S_API
        elif target_type == HostTask.TARGET_K8S:
            raise serializers.ValidationError({'task_type': 'K8s 资源仅支持 K8s 类型任务'})
        if task_type == HostTask.TASK_RUN_PLAYBOOK:
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_ANSIBLE
        return attrs


class HostTaskSubmitSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128)
    target_type = serializers.ChoiceField(choices=HostTask.TARGET_TYPE_CHOICES, default=HostTask.TARGET_HOST)
    task_type = serializers.ChoiceField(choices=HostTask.TASK_TYPE_CHOICES)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    host_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=True, required=False, default=list)
    resource_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=True, required=False, default=list)
    k8s_targets = serializers.ListField(child=serializers.DictField(), allow_empty=True, required=False, default=list)
    payload = serializers.JSONField(required=False, default=dict)
    selection_filters = serializers.JSONField(required=False, default=dict)
    execution_mode = serializers.ChoiceField(choices=HostTask.EXECUTION_MODE_CHOICES, default=HostTask.EXECUTION_MODE_SSH)
    execution_strategy = serializers.ChoiceField(choices=HostTask.STRATEGY_CHOICES, default=HostTask.STRATEGY_CONTINUE)
    timeout_seconds = serializers.IntegerField(min_value=5, max_value=120, default=15)
    trigger_source = serializers.ChoiceField(choices=HostTask.TRIGGER_SOURCE_CHOICES, default=HostTask.TRIGGER_SOURCE_MANUAL, required=False)
    source_context = serializers.JSONField(required=False, default=dict)

    def validate_host_ids(self, value):
        deduplicated = list(dict.fromkeys(value))
        return deduplicated

    def validate_resource_ids(self, value):
        deduplicated = list(dict.fromkeys(value))
        return deduplicated

    def validate_payload(self, value):
        return normalize_json_object(value)

    def validate_source_context(self, value):
        return normalize_json_object(value)

    def validate(self, attrs):
        task_type = attrs.get('task_type')
        target_type = attrs.get('target_type') or HostTask.TARGET_HOST
        execution_mode = attrs.get('execution_mode') or HostTask.EXECUTION_MODE_SSH
        validate_host_task_payload(task_type, attrs.get('payload') or {})
        if execution_mode == HostTask.EXECUTION_MODE_K8S_API and not str(task_type).startswith('k8s_'):
            raise serializers.ValidationError({'execution_mode': '只有 K8s 命令可以使用 K8s API'})
        if target_type == HostTask.TARGET_HOST:
            if task_type.startswith('k8s_'):
                raise serializers.ValidationError({'task_type': '主机资源不支持 K8s 类型任务'})
            if not attrs.get('host_ids') and not attrs.get('resource_ids'):
                raise serializers.ValidationError({'resource_ids': '请至少选择一个主机资源'})
        elif target_type == HostTask.TARGET_K8S:
            if not task_type.startswith('k8s_'):
                raise serializers.ValidationError({'task_type': 'K8s 资源仅支持 K8s 类型任务'})
            targets = attrs.get('k8s_targets') or []
            if not targets:
                raise serializers.ValidationError({'k8s_targets': '请至少选择一个 K8s 目标'})
            cluster_ids = []
            resource_ids = []
            normalized_source_items = []
            for item in targets:
                cluster_id = item.get('cluster_id')
                resource_id = item.get('resource_id') or item.get('task_resource_id')
                name = (item.get('name') or item.get('pod_name') or '').strip()
                namespace = (item.get('namespace') or '').strip()
                kind = (item.get('kind') or item.get('resource_type') or '').strip()
                try:
                    cluster_id = int(cluster_id) if cluster_id else None
                except (TypeError, ValueError):
                    cluster_id = None
                try:
                    resource_id = int(resource_id) if resource_id else None
                except (TypeError, ValueError):
                    resource_id = None
                if not cluster_id:
                    raise serializers.ValidationError({'k8s_targets': '请选择 K8s 集群'})
                cluster_ids.append(cluster_id)
                if resource_id:
                    resource_ids.append(resource_id)
                normalized_source_items.append((item, cluster_id, resource_id, namespace, name, kind))
            cluster_map = {item.id: item for item in K8sCluster.objects.filter(id__in=cluster_ids)}
            resource_map = {
                item.id: item
                for item in TaskResource.objects.select_related('environment', 'system', 'cluster').filter(
                    id__in=set(resource_ids + [cluster_id for _item, cluster_id, _resource_id, _namespace, _name, _kind in normalized_source_items]),
                    resource_type=TaskResource.RESOURCE_K8S,
                )
            }
            normalized_targets = []
            for item, cluster_id, resource_id, namespace, name, kind in normalized_source_items:
                resource = resource_map.get(resource_id) or (resource_map.get(cluster_id) if cluster_id not in cluster_map else None)
                cluster = cluster_map.get(cluster_id) or (resource.cluster if resource else None)
                if not cluster and resource:
                    cluster = K8sCluster.objects.filter(name=resource.name).first()
                if not cluster:
                    cluster_name = (item.get('cluster_name') or item.get('name') or '').strip()
                    if cluster_name and not re.fullmatch(r'Cluster\s+\d+', cluster_name, flags=re.IGNORECASE):
                        cluster = K8sCluster.objects.filter(name=cluster_name).first() or K8sCluster.objects.filter(name__icontains=cluster_name).first()
                if not cluster:
                    raise serializers.ValidationError({'k8s_targets': '请选择有效的 K8s 集群'})
                if task_type == HostTask.TASK_K8S_RESTART_POD and not name:
                    raise serializers.ValidationError({'k8s_targets': '请填写 Pod 名称'})
                if task_type == HostTask.TASK_K8S_SCALE_WORKLOAD and not name:
                    raise serializers.ValidationError({'k8s_targets': '请填写工作负载名称'})
                if task_type in [HostTask.TASK_K8S_RESTART_POD, HostTask.TASK_K8S_SCALE_WORKLOAD]:
                    namespace = namespace or 'default'
                if task_type == HostTask.TASK_K8S_POD_EXEC:
                    payload = attrs.get('payload') or {}
                    payload_kind = (payload.get('resource_kind') or '').strip()
                    if payload_kind and payload_kind != 'pod':
                        kind = kind if kind and kind != 'cluster' else payload_kind
                        namespace = namespace or (payload.get('namespace') or '').strip()
                        name = name or (payload.get('service_name') or payload.get('workload_name') or payload.get('resource_name') or '').strip()
                resource_environment = resource.environment.name if resource and resource.environment_id else (item.get('environment_name') or item.get('environment') or '')
                event_environment = item.get('event_environment') or item.get('event_environment_code') or ''
                event_environment_name = item.get('event_environment_name') or ''
                if resource and resource.environment_id and resource.environment.event_environment:
                    event_environment = str(resource.environment.event_environment)
                resource_system = resource.system.name if resource and resource.system_id else (item.get('system_name') or item.get('system') or '')
                normalized_targets.append({
                    'cluster_id': cluster.id,
                    'cluster_name': cluster.name,
                    'resource_id': resource.id if resource else resource_id,
                    'task_resource_id': resource.id if resource else resource_id,
                    'resource_name': resource.name if resource else (item.get('resource_name') or ''),
                    'environment_name': resource_environment,
                    'event_environment': event_environment,
                    'event_environment_name': event_environment_name,
                    'system_name': resource_system,
                    'namespace': namespace,
                    'name': name,
                    'kind': kind or ('cluster' if task_type == HostTask.TASK_K8S_POD_EXEC and not name else ''),
                    'container': (item.get('container') or '').strip(),
                })
            attrs['k8s_targets'] = normalized_targets
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_K8S_API
        if task_type == HostTask.TASK_RUN_PLAYBOOK:
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_ANSIBLE
        return attrs


class HostTaskBatchCancelSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False)

    def validate_ids(self, value):
        deduplicated = list(dict.fromkeys(value))
        if not deduplicated:
            raise serializers.ValidationError('\u8bf7\u81f3\u5c11\u9009\u62e9\u4e00\u4e2a\u4efb\u52a1')
        return deduplicated


class HostTaskRenameSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, trim_whitespace=True)

    def validate_name(self, value):
        text = str(value or '').strip()
        if not text:
            raise serializers.ValidationError('请填写任务名称')
        return text


class HostTaskTargetSerializer(serializers.ModelSerializer):
    environment_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Host
        fields = [
            'id',
            'hostname',
            'ip_address',
            'business_line',
            'environment',
            'environment_display',
            'admin_user',
            'os_type',
            'status',
            'status_display',
        ]

    def get_environment_display(self, obj):
        return obj.get_environment_display() if obj.environment else ''


class HostTaskScheduleExecutionSerializer(serializers.ModelSerializer):
    schedule_name = serializers.CharField(source='schedule.name', read_only=True)
    host_task_name = serializers.CharField(source='host_task.name', read_only=True)
    trigger_source_display = serializers.CharField(source='get_trigger_source_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = HostTaskScheduleExecution
        fields = [
            'id',
            'schedule',
            'schedule_name',
            'host_task',
            'host_task_name',
            'trigger_source',
            'trigger_source_display',
            'status',
            'status_display',
            'summary',
            'target_count',
            'success_count',
            'failed_count',
            'skipped_count',
            'error_message',
            'requested_by',
            'requested_at',
            'started_at',
            'finished_at',
            'created_at',
        ]


class HostTaskScheduleSerializer(serializers.ModelSerializer):
    task_type_display = serializers.CharField(source='get_task_type_display', read_only=True)
    execution_mode_display = serializers.CharField(source='get_execution_mode_display', read_only=True)
    schedule_type_display = serializers.CharField(source='get_schedule_type_display', read_only=True)
    overlap_policy_display = serializers.CharField(source='get_overlap_policy_display', read_only=True)
    last_status_display = serializers.SerializerMethodField()
    next_runs_preview = serializers.SerializerMethodField()

    class Meta:
        model = HostTaskSchedule
        fields = [
            'id',
            'name',
            'description',
            'enabled',
            'task_type',
            'task_type_display',
            'payload',
            'selection_filters',
            'target_host_ids',
            'target_snapshot',
            'target_count',
            'execution_mode',
            'execution_mode_display',
            'execution_strategy',
            'timeout_seconds',
            'schedule_type',
            'schedule_type_display',
            'cron_expression',
            'interval_seconds',
            'run_at',
            'timezone',
            'overlap_policy',
            'overlap_policy_display',
            'next_run_at',
            'next_runs_preview',
            'last_run_at',
            'last_status',
            'last_status_display',
            'consecutive_failures',
            'total_run_count',
            'last_error',
            'created_by',
            'updated_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'target_snapshot',
            'target_count',
            'next_run_at',
            'last_run_at',
            'last_status',
            'consecutive_failures',
            'total_run_count',
            'last_error',
            'created_by',
            'updated_by',
            'created_at',
            'updated_at',
        ]

    def get_last_status_display(self, obj):
        return obj.get_last_status_display() if obj.last_status else ''

    def get_next_runs_preview(self, obj):
        return preview_next_runs(obj, count=3)

    def validate_payload(self, value):
        return normalize_json_object(value)

    def validate_selection_filters(self, value):
        return normalize_json_object(value)

    def validate_target_host_ids(self, value):
        return normalize_schedule_hosts(value)

    def validate(self, attrs):
        task_type = attrs.get('task_type') or getattr(self.instance, 'task_type', '')
        if str(task_type).startswith('k8s_'):
            raise serializers.ValidationError({'task_type': '当前计划任务仍使用主机资源底座，K8s 调度请先通过任务工作台下发'})
        validate_host_task_payload(task_type, attrs.get('payload') if 'payload' in attrs else getattr(self.instance, 'payload', {}))
        if task_type == HostTask.TASK_RUN_PLAYBOOK:
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_ANSIBLE
        return validate_schedule_definition(attrs, instance=self.instance)


class HostTaskSchedulePreviewSerializer(serializers.Serializer):
    task_type = serializers.ChoiceField(choices=HostTask.TASK_TYPE_CHOICES)
    payload = serializers.JSONField(required=False, default=dict)
    selection_filters = serializers.JSONField(required=False, default=dict)
    target_host_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, default=list)
    execution_mode = serializers.ChoiceField(choices=HostTask.EXECUTION_MODE_CHOICES, default=HostTask.EXECUTION_MODE_SSH)
    execution_strategy = serializers.ChoiceField(choices=HostTask.STRATEGY_CHOICES, default=HostTask.STRATEGY_CONTINUE)
    timeout_seconds = serializers.IntegerField(min_value=5, max_value=300, default=15)
    enabled = serializers.BooleanField(required=False, default=True)
    schedule_type = serializers.ChoiceField(choices=HostTaskSchedule.SCHEDULE_TYPE_CHOICES)
    cron_expression = serializers.CharField(required=False, allow_blank=True, default='')
    interval_seconds = serializers.IntegerField(required=False, allow_null=True, min_value=60, max_value=2592000)
    run_at = serializers.DateTimeField(required=False, allow_null=True)
    timezone = serializers.CharField(required=False, allow_blank=True, default='Asia/Shanghai')
    overlap_policy = serializers.ChoiceField(choices=HostTaskSchedule.OVERLAP_POLICY_CHOICES, default=HostTaskSchedule.OVERLAP_SKIP)

    def validate_payload(self, value):
        return normalize_json_object(value)

    def validate_selection_filters(self, value):
        return normalize_json_object(value)

    def validate_target_host_ids(self, value):
        return normalize_schedule_hosts(value)

    def validate(self, attrs):
        if str(attrs.get('task_type') or '').startswith('k8s_'):
            raise serializers.ValidationError({'task_type': '当前计划任务仍使用主机资源底座，K8s 调度请先通过任务工作台下发'})
        validate_host_task_payload(attrs.get('task_type'), attrs.get('payload') or {})
        if attrs.get('task_type') == HostTask.TASK_RUN_PLAYBOOK:
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_ANSIBLE
        return validate_schedule_definition(attrs)

class DeploymentApprovalNodeSerializer(serializers.ModelSerializer):
    approver_type_display = serializers.CharField(source='get_approver_type_display', read_only=True)
    approver_scope_display = serializers.CharField(read_only=True)

    class Meta:
        model = DeploymentApprovalNode
        fields = [
            'id',
            'name',
            'order',
            'approver_type',
            'approver_type_display',
            'approver_value',
            'approver_scope_display',
            'description',
        ]


class DeploymentApprovalStepSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    approver_type_display = serializers.CharField(source='get_approver_type_display', read_only=True)
    approver_scope_display = serializers.CharField(read_only=True)

    class Meta:
        model = DeploymentApprovalStep
        fields = [
            'id',
            'flow',
            'node_name',
            'node_order',
            'approver_type',
            'approver_type_display',
            'approver_value',
            'approver_scope_display',
            'status',
            'status_display',
            'is_current',
            'approver',
            'comment',
            'acted_at',
            'created_at',
        ]


class DeploymentApprovalFlowSerializer(serializers.ModelSerializer):
    environment_display = serializers.SerializerMethodField()
    scope_display = serializers.CharField(read_only=True)
    nodes = DeploymentApprovalNodeSerializer(many=True)
    node_count = serializers.SerializerMethodField()

    class Meta:
        model = DeploymentApprovalFlow
        fields = [
            'id',
            'name',
            'environment',
            'environment_display',
            'scope_display',
            'description',
            'is_active',
            'created_by',
            'node_count',
            'nodes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']

    def get_environment_display(self, obj):
        return obj.get_environment_display() if obj.environment else '全部环境'

    def get_node_count(self, obj):
        return obj.nodes.count()

    def validate_nodes(self, value):
        if not value:
            raise serializers.ValidationError('至少需要配置一个审批节点')
        workorders = [item.get('order') for item in value]
        if len(set(workorders)) != len(workorders):
            raise serializers.ValidationError('审批节点顺序不能重复')
        for item in value:
            if not item.get('name'):
                raise serializers.ValidationError('审批节点名称不能为空')
        return value

    def _sync_active_flow(self, instance):
        if instance.is_active:
            DeploymentApprovalFlow.objects.filter(
                environment=instance.environment,
                is_active=True,
            ).exclude(pk=instance.pk).update(is_active=False)

    def _replace_nodes(self, instance, nodes):
        instance.nodes.all().delete()
        DeploymentApprovalNode.objects.bulk_create([
            DeploymentApprovalNode(
                flow=instance,
                name=item['name'],
                order=item['order'],
                approver_type=item.get('approver_type') or 'user',
                approver_value=item.get('approver_value', ''),
                description=item.get('description', ''),
            )
            for item in sorted(nodes, key=lambda data: (data['order'], data.get('name', '')))
        ])

    def create(self, validated_data):
        nodes = validated_data.pop('nodes', [])
        instance = super().create(validated_data)
        self._replace_nodes(instance, nodes)
        self._sync_active_flow(instance)
        return instance

    def update(self, instance, validated_data):
        nodes = validated_data.pop('nodes', None)
        instance = super().update(instance, validated_data)
        if nodes is not None:
            self._replace_nodes(instance, nodes)
        self._sync_active_flow(instance)
        return instance


class DeploymentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_display = serializers.CharField(source='get_environment_display', read_only=True)
    deploy_mode_display = serializers.CharField(source='get_deploy_mode_display', read_only=True)
    approval_status_display = serializers.CharField(source='get_approval_status_display', read_only=True)
    action_type_display = serializers.CharField(source='get_action_type_display', read_only=True)
    release_strategy_display = serializers.CharField(source='get_release_strategy_display', read_only=True)
    cluster_name = serializers.CharField(source='cluster.name', read_only=True, default='')
    target_display = serializers.CharField(read_only=True)
    strategy_summary = serializers.CharField(read_only=True)
    approval_progress_text = serializers.CharField(read_only=True)
    approval_flow_name = serializers.CharField(source='approval_flow.name', read_only=True, default='')
    approval_steps = DeploymentApprovalStepSerializer(many=True, read_only=True)
    current_approval_step = serializers.SerializerMethodField()
    previous_success_version = serializers.CharField(source='previous_success.version', read_only=True, default='')
    rollback_source_version = serializers.CharField(source='rollback_source.version', read_only=True, default='')
    rerun_source_version = serializers.CharField(source='rerun_source.version', read_only=True, default='')
    can_rollback = serializers.SerializerMethodField()
    can_advance_batch = serializers.SerializerMethodField()
    cmdb_item_id = serializers.SerializerMethodField()
    cmdb_item_name = serializers.SerializerMethodField()
    cmdb_item_status = serializers.SerializerMethodField()
    cmdb_targets = serializers.SerializerMethodField()

    class Meta:
        model = Deployment
        fields = [
            'id',
            'app_name',
            'business_line',
            'version',
            'image',
            'environment',
            'environment_display',
            'deploy_mode',
            'deploy_mode_display',
            'status',
            'status_display',
            'approval_status',
            'approval_status_display',
            'action_type',
            'action_type_display',
            'release_strategy',
            'release_strategy_display',
            'strategy_summary',
            'canary_percent',
            'batch_total',
            'batch_current',
            'batch_size',
            'strategy_config',
            'submitter',
            'deployer',
            'approver',
            'approval_comment',
            'change_summary',
            'description',
            'env_config',
            'deploy_log',
            'deploy_dir',
            'release_name',
            'namespace',
            'replicas',
            'container_port',
            'service_port',
            'cluster',
            'cluster_name',
            'target_display',
            'approval_flow',
            'approval_flow_name',
            'approval_progress_text',
            'approval_steps',
            'current_approval_step',
            'previous_success',
            'previous_success_version',
            'rollback_source',
            'rollback_source_version',
            'rerun_source',
            'rerun_source_version',
            'approved_at',
            'executed_at',
            'finished_at',
            'execution_count',
            'is_current',
            'can_rollback',
            'can_advance_batch',
            'cmdb_item_id',
            'cmdb_item_name',
            'cmdb_item_status',
            'cmdb_targets',
            'deployed_at',
        ]
        read_only_fields = [
            'status',
            'approval_status',
            'action_type',
            'submitter',
            'deployer',
            'approver',
            'approval_comment',
            'deploy_log',
            'deploy_dir',
            'approval_flow',
            'previous_success',
            'rollback_source',
            'rerun_source',
            'approved_at',
            'executed_at',
            'finished_at',
            'execution_count',
            'is_current',
            'batch_current',
            'deployed_at',
        ]

    def get_can_rollback(self, obj):
        return bool(obj.is_current and obj.get_previous_successful_release())

    def get_can_advance_batch(self, obj):
        return bool(
            obj.release_strategy == 'batch'
            and obj.approval_status == 'approved'
            and obj.is_current
            and (obj.batch_current or 0) < (obj.batch_total or 1)
        )

    def get_current_approval_step(self, obj):
        step = obj.current_approval_step
        return DeploymentApprovalStepSerializer(step).data if step else None

    def _get_cmdb_item(self, obj):
        cached = getattr(obj, '_cmdb_item_cache', None)
        if cached is not None:
            return cached
        item = ConfigItem.objects.filter(
            attributes__source='app_release',
            attributes__deployment_id=obj.id,
        ).first()
        setattr(obj, '_cmdb_item_cache', item)
        return item

    def get_cmdb_item_id(self, obj):
        item = self._get_cmdb_item(obj)
        return item.id if item else None

    def get_cmdb_item_name(self, obj):
        item = self._get_cmdb_item(obj)
        return item.name if item else ''

    def get_cmdb_item_status(self, obj):
        item = self._get_cmdb_item(obj)
        return item.get_status_display() if item else ''

    def get_cmdb_targets(self, obj):
        item = self._get_cmdb_item(obj)
        if not item:
            return []
        return [
            relation.target.name
            for relation in CIRelation.objects.select_related('target').filter(source=item, relation_type='runs_on')
        ]

    def validate_strategy_config(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('策略配置必须为 JSON 对象')
        return value

    def validate_env_config(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('环境变量必须为 JSON 对象')
        return value

    def validate(self, attrs):
        business_line = (attrs.get('business_line') or getattr(self.instance, 'business_line', '') or '').strip()
        environment = attrs.get('environment') or getattr(self.instance, 'environment', '')
        deploy_mode = attrs.get('deploy_mode') or getattr(self.instance, 'deploy_mode', 'k8s')
        cluster = attrs.get('cluster', getattr(self.instance, 'cluster', None))
        namespace = attrs.get('namespace', getattr(self.instance, 'namespace', ''))
        strategy = attrs.get('release_strategy') or getattr(self.instance, 'release_strategy', 'standard')
        canary_percent = attrs.get('canary_percent', getattr(self.instance, 'canary_percent', 10))
        batch_total = attrs.get('batch_total', getattr(self.instance, 'batch_total', 1))
        batch_size = attrs.get('batch_size', getattr(self.instance, 'batch_size', 1))

        if not business_line:
            raise serializers.ValidationError({'business_line': '请选择系统'})
        biz_node = ResourceNode.objects.filter(node_type='biz', name=business_line).first()
        if not biz_node:
            raise serializers.ValidationError({'business_line': '所选系统未在资源树中配置'})
        if not environment:
            raise serializers.ValidationError({'environment': '请选择环境'})
        if not ResourceNode.objects.filter(node_type='env', parent=biz_node, name=environment).exists():
            raise serializers.ValidationError({'environment': '所选环境未绑定到当前系统'})
        attrs['business_line'] = business_line

        if deploy_mode != 'k8s':
            raise serializers.ValidationError({'deploy_mode': '发布流程仅支持 K8S 集群'})
        if not cluster:
            raise serializers.ValidationError({'cluster': '请选择目标 K8S 集群'})
        attrs['deploy_mode'] = 'k8s'
        attrs['docker_host'] = None
        attrs['host'] = None
        attrs['namespace'] = (namespace or 'default').strip() or 'default'

        if strategy == 'canary':
            if canary_percent <= 0 or canary_percent > 100:
                raise serializers.ValidationError({'canary_percent': '灰度比例必须在 1-100 之间'})
            attrs['batch_total'] = 1
            attrs['batch_size'] = 1
        elif strategy == 'batch':
            if batch_total < 2:
                raise serializers.ValidationError({'batch_total': '批次发布至少需要 2 个批次'})
            if batch_size < 1:
                raise serializers.ValidationError({'batch_size': '单批规模必须大于 0'})
        else:
            attrs['canary_percent'] = 10
            attrs['batch_total'] = 1
            attrs['batch_size'] = 1

        image = attrs.get('image') or getattr(self.instance, 'image', '')
        app_name = attrs.get('app_name') or getattr(self.instance, 'app_name', '')
        version = attrs.get('version') or getattr(self.instance, 'version', '')
        if not image:
            attrs['image'] = f'{app_name}:{version}'
        return attrs

class ApprovalActionSerializer(serializers.Serializer):
    comment = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class DeploymentActionSerializer(serializers.Serializer):
    change_summary = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class TransactionTicketSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_ticket_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_display = serializers.CharField(source='get_environment_display', read_only=True)
    approval_flow_name = serializers.CharField(source='approval_flow.name', read_only=True, default='')

    class Meta:
        model = TransactionTicket
        fields = [
            'id',
            'title',
            'ticket_type',
            'type_display',
            'priority',
            'priority_display',
            'business_line',
            'environment',
            'environment_display',
            'approval_flow',
            'approval_flow_name',
            'owner',
            'applicant',
            'window',
            'description',
            'status',
            'status_display',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'applicant',
            'status',
            'created_at',
            'updated_at',
            'type_display',
            'priority_display',
            'status_display',
            'environment_display',
            'approval_flow_name',
        ]

    def validate(self, attrs):
        business_line = (attrs.get('business_line') if 'business_line' in attrs else getattr(self.instance, 'business_line', '')) or ''
        environment = (attrs.get('environment') if 'environment' in attrs else getattr(self.instance, 'environment', '')) or ''

        business_line = business_line.strip()
        if not business_line:
            raise serializers.ValidationError({'business_line': '请选择系统'})
        if not ResourceNode.objects.filter(node_type='biz', name=business_line).exists():
            raise serializers.ValidationError({'business_line': '所选系统未在资源树中配置'})

        if not environment:
            raise serializers.ValidationError({'environment': '请选择环境'})
        if not ResourceNode.objects.filter(node_type='env', parent__name=business_line, name=environment).exists():
            raise serializers.ValidationError({'environment': '所选环境未在当前系统下配置'})

        approval_flow = attrs.get('approval_flow') if 'approval_flow' in attrs else getattr(self.instance, 'approval_flow', None)
        if approval_flow and approval_flow.environment and approval_flow.environment != environment:
            raise serializers.ValidationError({'approval_flow': '所选审批流与当前环境不匹配'})

        attrs['business_line'] = business_line
        return attrs


class AlertUserLiteSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'display_name']

    def get_display_name(self, obj):
        full_name = f'{obj.first_name} {obj.last_name}'.strip()
        return full_name or obj.username


class AlertRuleSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    source_type_display = serializers.CharField(source='get_source_type_display', read_only=True)
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    metric_datasource_detail = serializers.SerializerMethodField()
    template_detail = serializers.SerializerMethodField()
    needs_binding = serializers.SerializerMethodField()

    class Meta:
        model = AlertRule
        fields = '__all__'

    def get_metric_datasource_detail(self, obj):
        datasource = obj.metric_datasource
        if not datasource:
            return None
        return {
            'id': datasource.id,
            'name': datasource.name,
            'environment': datasource.environment,
            'cluster_name': datasource.cluster_name,
            'is_enabled': datasource.is_enabled,
        }

    def get_template_detail(self, obj):
        template = obj.template
        if not template:
            return None
        labels = template.labels if isinstance(template.labels, dict) else {}
        return {
            'id': template.id,
            'code': template.code,
            'name': template.name,
            'rule_group': labels.get('rule_group') or '',
            'rule_group_label': labels.get('rule_group_label') or '',
            'template_source': labels.get('template_source') or '',
        }

    def get_needs_binding(self, obj):
        return obj.source_type == 'prometheus' and not obj.is_template and not obj.metric_datasource_id

    def validate(self, attrs):
        source_type = attrs.get('source_type', getattr(self.instance, 'source_type', ''))
        is_template = attrs.get('is_template', getattr(self.instance, 'is_template', False))
        datasource = attrs.get('metric_datasource', getattr(self.instance, 'metric_datasource', None))
        template = attrs.get('template', getattr(self.instance, 'template', None))
        if template and not template.is_template:
            raise serializers.ValidationError({'template': '来源规则不是模板'})
        if source_type == 'prometheus' and not is_template and not datasource:
            raise serializers.ValidationError({'metric_datasource': 'Prometheus 规则必须绑定指标数据源'})
        if datasource and not datasource.is_enabled:
            raise serializers.ValidationError({'metric_datasource': '指标数据源已停用'})
        query_config = dict(attrs.get('query_config', getattr(self.instance, 'query_config', {}) or {}))
        if datasource:
            query_config['metric_datasource_id'] = datasource.id
            attrs['query_config'] = query_config
        return attrs


class AlertSilenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertSilence
        fields = '__all__'
        read_only_fields = ['created_by', 'created_at', 'updated_at']



class AlertRecipientSerializer(serializers.ModelSerializer):
    user_detail = AlertUserLiteSerializer(source='user', read_only=True)
    contact_channels = serializers.SerializerMethodField()
    group_refs = serializers.SerializerMethodField()

    class Meta:
        model = AlertRecipient
        fields = [
            'id', 'name', 'user', 'user_detail', 'phone', 'email',
            'dingtalk_user_id', 'feishu_user_id', 'wecom_user_id',
            'contact_channels', 'group_refs', 'is_enabled', 'description',
            'created_at', 'updated_at',
        ]

    def get_contact_channels(self, obj):
        channels = []
        if obj.email or (obj.user_id and obj.user and obj.user.email):
            channels.append('email')
        if obj.phone:
            channels.extend(['sms', 'voice'])
        if obj.dingtalk_user_id:
            channels.append('dingtalk')
        if obj.feishu_user_id:
            channels.append('feishu')
        if obj.wecom_user_id:
            channels.append('wecom')
        return channels

    def get_group_refs(self, obj):
        return [{'id': group.id, 'name': group.name} for group in obj.groups.all()]


class AlertRecipientGroupSerializer(serializers.ModelSerializer):
    recipient_ids = serializers.PrimaryKeyRelatedField(queryset=AlertRecipient.objects.all(), many=True, write_only=True, required=False)
    user_ids = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), many=True, write_only=True, required=False)
    recipients = AlertRecipientSerializer(many=True, read_only=True)
    users = AlertUserLiteSerializer(many=True, read_only=True)
    member_count = serializers.SerializerMethodField()
    active_member_count = serializers.SerializerMethodField()
    reachable_member_count = serializers.SerializerMethodField()
    contact_coverage = serializers.SerializerMethodField()
    health_status = serializers.SerializerMethodField()
    policy_refs = serializers.SerializerMethodField()
    policy_count = serializers.SerializerMethodField()

    class Meta:
        model = AlertRecipientGroup
        fields = [
            'id', 'name', 'description', 'is_enabled', 'created_at', 'updated_at',
            'recipient_ids', 'user_ids', 'recipients', 'users',
            'member_count', 'active_member_count', 'reachable_member_count',
            'contact_coverage', 'health_status', 'policy_refs', 'policy_count',
        ]

    def _members(self, obj):
        recipients = list(obj.recipients.all())
        users = list(obj.users.all())
        return recipients, users

    def _active_members(self, obj):
        recipients, users = self._members(obj)
        return (
            [item for item in recipients if item.is_enabled],
            [item for item in users if item.is_active],
        )

    def get_member_count(self, obj):
        recipients, users = self._members(obj)
        return len(recipients) + len(users)

    def get_active_member_count(self, obj):
        recipients, users = self._active_members(obj)
        return len(recipients) + len(users)

    def get_contact_coverage(self, obj):
        recipients, users = self._active_members(obj)
        return {
            'email': sum(1 for item in recipients if item.email or (item.user_id and item.user and item.user.email)) + sum(1 for item in users if item.email),
            'phone': sum(1 for item in recipients if item.phone),
            'dingtalk': sum(1 for item in recipients if item.dingtalk_user_id),
            'feishu': sum(1 for item in recipients if item.feishu_user_id),
            'wecom': sum(1 for item in recipients if item.wecom_user_id),
        }

    def get_reachable_member_count(self, obj):
        recipients, users = self._active_members(obj)
        recipient_count = sum(1 for item in recipients if (
            item.email or item.phone or item.dingtalk_user_id or item.feishu_user_id
            or item.wecom_user_id or (item.user_id and item.user and item.user.email)
        ))
        return recipient_count + sum(1 for item in users if item.email)

    def get_health_status(self, obj):
        active_count = self.get_active_member_count(obj)
        reachable_count = self.get_reachable_member_count(obj)
        if active_count == 0:
            return 'empty'
        if reachable_count == 0:
            return 'unreachable'
        if reachable_count < active_count:
            return 'partial'
        return 'ready'

    def get_policy_refs(self, obj):
        return [
            {
                'id': policy.id,
                'name': policy.name,
                'metric_datasource_id': policy.metric_datasource_id,
            }
            for policy in obj.notification_policies.all()
        ]

    def get_policy_count(self, obj):
        return len(self.get_policy_refs(obj))

    def validate(self, attrs):
        attrs = super().validate(attrs)
        is_enabled = attrs.get('is_enabled', getattr(self.instance, 'is_enabled', True))
        recipients = attrs.get('recipient_ids')
        users = attrs.get('user_ids')
        if recipients is None and self.instance is not None:
            recipients = list(self.instance.recipients.all())
        if users is None and self.instance is not None:
            users = list(self.instance.users.all())
        if is_enabled and not (recipients or users):
            raise serializers.ValidationError('启用的接收组至少需要一个成员')
        return attrs

    def create(self, validated_data):
        recipient_ids = validated_data.pop('recipient_ids', [])
        user_ids = validated_data.pop('user_ids', [])
        instance = super().create(validated_data)
        instance.recipients.set(recipient_ids)
        instance.users.set(user_ids)
        return instance

    def update(self, instance, validated_data):
        recipient_ids = validated_data.pop('recipient_ids', None)
        user_ids = validated_data.pop('user_ids', None)
        instance = super().update(instance, validated_data)
        if recipient_ids is not None:
            instance.recipients.set(recipient_ids)
        if user_ids is not None:
            instance.users.set(user_ids)
        return instance


class AlertNotificationChannelSerializer(serializers.ModelSerializer):
    channel_type_display = serializers.CharField(source='get_channel_type_display', read_only=True)
    SECRET_KEYS = {'secret', 'sign_secret'}
    SECRET_MASK = '******'

    class Meta:
        model = AlertNotificationChannel
        fields = '__all__'

    def _normalize_config(self, config, instance=None):
        if not isinstance(config, dict):
            return config
        normalized = dict(config)
        previous = instance.config if instance and isinstance(instance.config, dict) else {}
        for key in self.SECRET_KEYS:
            value = normalized.get(key)
            if value in ('', None, self.SECRET_MASK):
                if previous.get(key):
                    normalized[key] = previous[key]
                else:
                    normalized.pop(key, None)
            elif key not in normalized and previous.get(key):
                normalized[key] = previous[key]
        return normalized

    def validate(self, attrs):
        channel_type = attrs.get('channel_type') or getattr(self.instance, 'channel_type', '')
        config = attrs.get('config')
        if config is None:
            config = getattr(self.instance, 'config', {}) or {}
        config = self._normalize_config(config, instance=self.instance)
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise serializers.ValidationError({'config': '渠道配置必须为 JSON 对象'})
        if channel_type == AlertNotificationChannel.CHANNEL_FEISHU:
            webhook_url = str(config.get('webhook_url') or config.get('url') or '').strip()
            sign_secret = str(config.get('secret') or config.get('sign_secret') or '').strip()
            if not webhook_url:
                raise serializers.ValidationError({'config': '飞书渠道必须配置 webhook_url'})
            if not sign_secret:
                raise serializers.ValidationError({'config': '飞书渠道必须配置签名密钥'})
        if 'config' in attrs:
            attrs['config'] = config
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        config = data.get('config')
        if isinstance(config, dict):
            config = dict(config)
            for key in self.SECRET_KEYS:
                if config.get(key):
                    config[key] = self.SECRET_MASK
            data['config'] = config
        return data

    def create(self, validated_data):
        if 'config' in validated_data:
            validated_data['config'] = self._normalize_config(validated_data.get('config'))
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'config' in validated_data:
            validated_data['config'] = self._normalize_config(validated_data.get('config'), instance=instance)
        return super().update(instance, validated_data)


class AlertNotificationPolicySerializer(serializers.ModelSerializer):
    channel_ids = serializers.PrimaryKeyRelatedField(queryset=AlertNotificationChannel.objects.all(), many=True, write_only=True, required=False)
    recipient_group_ids = serializers.PrimaryKeyRelatedField(queryset=AlertRecipientGroup.objects.all(), many=True, write_only=True, required=False)
    channels = serializers.SerializerMethodField()
    recipient_groups = serializers.SerializerMethodField()
    metric_datasource_detail = serializers.SerializerMethodField()

    class Meta:
        model = AlertNotificationPolicy
        fields = [
            'id', 'name', 'metric_datasource', 'metric_datasource_detail', 'matchers', 'min_level',
            'priority', 'continue_matching', 'channel_ids', 'channels', 'recipient_group_ids',
            'recipient_groups', 'group_by', 'group_wait_seconds', 'group_interval_seconds',
            'repeat_interval_minutes', 'mute_schedule', 'inhibition_matchers', 'escalation_steps',
            'notify_on_fire', 'notify_on_resolved', 'notify_on_analysis', 'is_enabled', 'description', 'created_at', 'updated_at',
        ]

    def get_channels(self, obj):
        return [
            {'id': item.id, 'name': item.name, 'channel_type': item.channel_type, 'channel_type_display': item.get_channel_type_display()}
            for item in obj.channels.all()
        ]

    def get_recipient_groups(self, obj):
        return [{'id': item.id, 'name': item.name} for item in obj.recipient_groups.all()]

    def get_metric_datasource_detail(self, obj):
        datasource = obj.metric_datasource
        if not datasource:
            return None
        return {'id': datasource.id, 'name': datasource.name, 'environment': datasource.environment, 'cluster_name': datasource.cluster_name}

    def validate_matchers(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('匹配条件必须是列表')
        valid_operators = {'=', '==', '!=', '=~', '!~'}
        for item in value:
            if not isinstance(item, dict) or not str(item.get('key') or '').strip():
                raise serializers.ValidationError('每个匹配条件都必须包含标签名')
            if str(item.get('operator') or '=') not in valid_operators:
                raise serializers.ValidationError('匹配操作符仅支持 =、!=、=~、!~')
        return value

    def validate_min_level(self, value):
        if value and value not in {'info', 'warning', 'critical'}:
            raise serializers.ValidationError('最低级别无效')
        return value

    def create(self, validated_data):
        channels = validated_data.pop('channel_ids', [])
        groups = validated_data.pop('recipient_group_ids', [])
        instance = super().create(validated_data)
        instance.channels.set(channels)
        instance.recipient_groups.set(groups)
        return instance

    def update(self, instance, validated_data):
        channels = validated_data.pop('channel_ids', None)
        groups = validated_data.pop('recipient_group_ids', None)
        instance = super().update(instance, validated_data)
        if channels is not None:
            instance.channels.set(channels)
        if groups is not None:
            instance.recipient_groups.set(groups)
        return instance




class AlertNotificationLogSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AlertNotificationLog
        fields = '__all__'


class AlertActionSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = AlertAction
        fields = '__all__'


class AlertInteractionTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertInteractionToken
        fields = '__all__'


class AlertClaimSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertClaim
        fields = ['id', 'claimant', 'claimed_at']


class AlertSerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    source_type_display = serializers.CharField(source='get_source_type_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')
    claimed_by = serializers.SerializerMethodField()
    claimed_at = serializers.SerializerMethodField()
    claimants = serializers.SerializerMethodField()
    claimant_count = serializers.SerializerMethodField()
    current_user_claimed = serializers.SerializerMethodField()
    actions = AlertActionSerializer(many=True, read_only=True)
    recent_notifications = serializers.SerializerMethodField()

    class Meta:
        model = Alert
        fields = '__all__'

    def _claim_records(self, obj):
        records = getattr(obj, '_prefetched_objects_cache', {}).get('claim_records')
        if records is not None:
            return list(records)
        return list(obj.claim_records.all())

    def get_claimed_by(self, obj):
        names = [item.claimant for item in self._claim_records(obj)]
        return '、'.join(names)

    def get_claimed_at(self, obj):
        records = self._claim_records(obj)
        if not records:
            return None
        return records[0].claimed_at

    def get_claimants(self, obj):
        return AlertClaimSerializer(self._claim_records(obj), many=True).data

    def get_claimant_count(self, obj):
        return len(self._claim_records(obj))

    def get_current_user_claimed(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        username = request.user.username
        return any(item.claimant == username for item in self._claim_records(obj))

    def get_recent_notifications(self, obj):
        logs = obj.notification_logs.all()[:5]
        return AlertNotificationLogSerializer(logs, many=True).data


class LogEntrySerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')

    class Meta:
        model = LogEntry
        fields = '__all__'


class NginxEnvironmentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = NginxEnvironment
        fields = '__all__'
        extra_kwargs = {
            'ssh_password': {'write_only': True},
        }


class NginxCertificateSerializer(serializers.ModelSerializer):
    environment_names = serializers.SerializerMethodField()

    class Meta:
        model = NginxCertificate
        fields = '__all__'
        extra_kwargs = {
            'domain': {'read_only': True},
            'expires_at': {'read_only': True},
            'cert_content': {'write_only': True},
            'key_content': {'write_only': True},
        }

    def get_environment_names(self, obj):
        return [{'id': item.id, 'name': item.name} for item in obj.environments.all()]


class NginxDomainSerializer(serializers.ModelSerializer):
    environment_name = serializers.CharField(source='environment.name', read_only=True)
    ssl_enabled = serializers.BooleanField(read_only=True)
    certificate_domain = serializers.CharField(source='certificate.domain', read_only=True, default=None)

    class Meta:
        model = NginxDomain
        fields = '__all__'


class NginxRouteSerializer(serializers.ModelSerializer):
    domain_name = serializers.CharField(source='nginx_domain.domain', read_only=True)
    environment_name = serializers.CharField(source='nginx_domain.environment.name', read_only=True)

    class Meta:
        model = NginxRoute
        fields = '__all__'
