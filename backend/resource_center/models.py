import uuid

from django.conf import settings
from django.db import models


class ResourceType(models.Model):
    CATEGORY_CHOICES = [
        ('organization', '组织与业务'),
        ('compute', '计算资源'),
        ('platform', '平台组件'),
    ]

    code = models.SlugField('类型编码', max_length=64, unique=True)
    name = models.CharField('类型名称', max_length=64)
    category = models.CharField('分类', max_length=32, choices=CATEGORY_CHOICES)
    icon = models.CharField('图标', max_length=64, blank=True, default='Box')
    attribute_schema = models.JSONField('扩展字段规范', default=dict, blank=True)
    is_builtin = models.BooleanField('内置类型', default=False)
    is_enabled = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'name', 'id']

    def __str__(self):
        return self.name


class Resource(models.Model):
    ENVIRONMENT_CHOICES = [('prod', '生产'), ('test', '测试'), ('dev', '开发'), ('unknown', '未指定')]
    STATUS_CHOICES = [
        ('pending', '待确认'),
        ('active', '使用中'),
        ('warning', '异常'),
        ('missing', '疑似失联'),
        ('offline', '已失联'),
        ('retired', '已下线'),
    ]
    CRITICALITY_CHOICES = [('low', '低'), ('medium', '中'), ('high', '高'), ('critical', '核心')]

    uid = models.UUIDField('资源 ID', default=uuid.uuid4, unique=True, editable=False)
    resource_type = models.ForeignKey(ResourceType, on_delete=models.PROTECT, related_name='resources')
    business_contexts = models.ManyToManyField(
        'aiops.AIOpsKnowledgeEnvironment', blank=True, related_name='resources',
        verbose_name='业务上下文',
    )
    name = models.CharField('资源名称', max_length=255)
    display_name = models.CharField('显示名称', max_length=255, blank=True, default='')
    environment = models.CharField('环境', max_length=16, choices=ENVIRONMENT_CHOICES, default='unknown')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='active')
    product = models.CharField('所属产品', max_length=128, blank=True, default='')
    business_system = models.CharField('业务系统', max_length=128, blank=True, default='')
    primary_ip = models.GenericIPAddressField('主要 IP', null=True, blank=True)
    criticality = models.CharField('重要级别', max_length=16, choices=CRITICALITY_CHOICES, default='medium')
    source = models.CharField('创建来源', max_length=32, default='manual')
    description = models.CharField('说明', max_length=255, blank=True, default='')
    attributes = models.JSONField('扩展属性', default=dict, blank=True)
    manual_fields = models.JSONField('人工锁定字段', default=list, blank=True)
    consecutive_misses = models.PositiveIntegerField('连续未发现次数', default=0)
    first_seen_at = models.DateTimeField('首次发现时间', null=True, blank=True)
    last_seen_at = models.DateTimeField('最后发现时间', null=True, blank=True)
    created_by = models.CharField('创建人', max_length=64, blank=True, default='system')
    updated_by = models.CharField('更新人', max_length=64, blank=True, default='system')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['resource_type__category', 'resource_type__name', 'name', 'id']
        indexes = [
            models.Index(fields=['resource_type', 'status'], name='rc_res_type_status_idx'),
            models.Index(fields=['primary_ip'], name='rc_res_primary_ip_idx'),
            models.Index(fields=['product', 'environment'], name='rc_res_product_env_idx'),
            models.Index(fields=['last_seen_at'], name='rc_res_last_seen_idx'),
        ]

    def __str__(self):
        return self.display_name or self.name


class ResourceIdentifier(models.Model):
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='identifiers')
    kind = models.CharField('标识类型', max_length=32)
    value = models.CharField('标识值', max_length=255)
    scope = models.CharField('标识作用域', max_length=128, default='global')
    source = models.CharField('标识来源', max_length=32, blank=True, default='manual')
    is_primary = models.BooleanField('主要标识', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['kind', 'scope', 'value'], name='rc_identifier_unique'),
        ]
        indexes = [models.Index(fields=['kind', 'value'], name='rc_identifier_lookup_idx')]


class ResourceRelation(models.Model):
    RELATION_CHOICES = [
        ('belongs_to', '属于'),
        ('contains', '包含'),
        ('runs_on', '运行于'),
        ('deployed_on', '部署于'),
        ('depends_on', '依赖'),
        ('monitored_by', '监控于'),
    ]

    source = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='outgoing_relations')
    target = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='incoming_relations')
    relation_type = models.CharField('关系类型', max_length=32, choices=RELATION_CHOICES)
    origin = models.CharField('关系来源', max_length=32, default='manual')
    attributes = models.JSONField('关系属性', default=dict, blank=True)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['source', 'target', 'relation_type'], name='rc_relation_unique'),
            models.CheckConstraint(condition=~models.Q(source=models.F('target')), name='rc_relation_no_self'),
        ]


class ResourceContact(models.Model):
    ROLE_CHOICES = [
        ('ops_owner', '运维负责人'),
        ('project_owner', '项目负责人'),
        ('product_owner', '产品负责人'),
        ('oncall', '值班人员'),
    ]

    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='contacts')
    role = models.CharField('职责', max_length=32, choices=ROLE_CHOICES)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    recipient = models.ForeignKey('ops.AlertRecipient', on_delete=models.SET_NULL, null=True, blank=True)
    contact_name = models.CharField('联系人', max_length=64, blank=True, default='')
    inherit_to_children = models.BooleanField('向下继承', default=True)
    is_primary = models.BooleanField('主要负责人', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['resource', 'role', 'user', 'recipient'], name='rc_contact_unique'),
        ]


class DiscoverySource(models.Model):
    TYPE_CHOICES = [
        ('k8s', 'Kubernetes API'),
        ('zabbix', 'Zabbix'),
        ('prometheus', 'Prometheus'),
        ('ssh', 'SSH'),
        ('manual', '手工登记'),
    ]
    STATUS_CHOICES = [('pending', '待发现'), ('healthy', '正常'), ('degraded', '部分成功'), ('failed', '失败')]

    name = models.CharField('发现源名称', max_length=128)
    source_type = models.CharField('发现源类型', max_length=32, choices=TYPE_CHOICES)
    k8s_cluster = models.ForeignKey(
        'ops.K8sCluster', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='resource_discovery_source', verbose_name='K8S 集群连接',
    )
    config = models.JSONField('发现配置', default=dict, blank=True)
    sync_interval_minutes = models.PositiveIntegerField('同步间隔分钟', default=10)
    is_enabled = models.BooleanField('启用', default=True)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='pending')
    next_run_at = models.DateTimeField('下次执行时间', null=True, blank=True, db_index=True)
    last_run_at = models.DateTimeField('最近执行时间', null=True, blank=True)
    last_success_at = models.DateTimeField('最近成功时间', null=True, blank=True)
    last_error = models.TextField('最近错误', blank=True, default='')
    created_by = models.CharField('创建人', max_length=64, blank=True, default='system')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['source_type', 'name', 'id']


class DiscoveryRun(models.Model):
    STATUS_CHOICES = [
        ('pending', '等待中'), ('connecting', '连接中'), ('collecting', '采集中'),
        ('reconciling', '对账中'), ('completed', '完成'), ('partial', '部分完成'), ('failed', '失败'),
    ]

    source = models.ForeignKey(DiscoverySource, on_delete=models.CASCADE, related_name='runs')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='pending')
    trigger = models.CharField('触发方式', max_length=16, default='manual')
    discovered_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    unchanged_count = models.PositiveIntegerField(default=0)
    missing_count = models.PositiveIntegerField(default=0)
    conflict_count = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class ResourceSourceBinding(models.Model):
    source = models.ForeignKey(DiscoverySource, on_delete=models.CASCADE, related_name='bindings')
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='source_bindings')
    external_type = models.CharField(max_length=64)
    external_id = models.CharField(max_length=255)
    content_hash = models.CharField(max_length=64, blank=True, default='')
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['source', 'external_type', 'external_id'], name='rc_binding_unique'),
        ]


class RuntimeResource(models.Model):
    source = models.ForeignKey(DiscoverySource, on_delete=models.CASCADE, related_name='runtime_resources')
    cluster_resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='runtime_resources')
    kind = models.CharField(max_length=64)
    uid = models.CharField(max_length=255)
    namespace = models.CharField(max_length=128, blank=True, default='')
    name = models.CharField(max_length=255)
    status = models.CharField(max_length=64, blank=True, default='')
    owner_kind = models.CharField(max_length=64, blank=True, default='')
    owner_name = models.CharField(max_length=255, blank=True, default='')
    node_name = models.CharField(max_length=255, blank=True, default='')
    attributes = models.JSONField(default=dict, blank=True)
    last_seen_at = models.DateTimeField(db_index=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source', 'kind', 'uid'], name='rc_runtime_unique')]
        indexes = [models.Index(fields=['cluster_resource', 'kind', 'namespace'], name='rc_runtime_scope_idx')]


class ResourceChange(models.Model):
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='changes')
    discovery_run = models.ForeignKey(DiscoveryRun, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=32)
    field = models.CharField(max_length=64, blank=True, default='')
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    actor = models.CharField(max_length=64, default='system')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class ResourceNode(models.Model):
    """业务线/环境分组树节点（自 cmdb app 迁移并入）"""
    NODE_TYPE_CHOICES = [
        ('biz', '业务线'),
        ('env', '环境'),
    ]

    name = models.CharField(max_length=100, verbose_name='名称')
    node_type = models.CharField(max_length=20, choices=NODE_TYPE_CHOICES, verbose_name='节点类型')
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='children', verbose_name='父节点'
    )
    sort_order = models.IntegerField(default=0, verbose_name='排序')

    class Meta:
        verbose_name = '资源分组节点'
        verbose_name_plural = '资源分组节点'

    def __str__(self):
        return self.name
