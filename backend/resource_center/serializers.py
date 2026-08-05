import ipaddress
from urllib.parse import urlparse

from rest_framework import serializers

from .models import (
    DiscoveryRun,
    DiscoverySource,
    Resource,
    ResourceChange,
    ResourceContact,
    ResourceIdentifier,
    ResourceNode,
    ResourceRelation,
    ResourceSourceBinding,
    ResourceType,
    RuntimeResource,
)


class ResourceTypeSerializer(serializers.ModelSerializer):
    resource_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = ResourceType
        fields = '__all__'
        read_only_fields = ['is_builtin', 'created_at', 'updated_at']


class ResourceIdentifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResourceIdentifier
        fields = ['id', 'kind', 'value', 'scope', 'source', 'is_primary', 'created_at']
        read_only_fields = ['created_at']


class ResourceContactSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True)
    recipient_name = serializers.CharField(source='recipient.name', read_only=True)

    class Meta:
        model = ResourceContact
        fields = '__all__'

    def validate(self, attrs):
        user = attrs.get('user', getattr(self.instance, 'user', None))
        recipient = attrs.get('recipient', getattr(self.instance, 'recipient', None))
        contact_name = attrs.get('contact_name', getattr(self.instance, 'contact_name', ''))
        if not user and not recipient and not str(contact_name or '').strip():
            raise serializers.ValidationError('用户、告警接收人或联系人名称至少填写一项')
        return attrs


class ResourceSerializer(serializers.ModelSerializer):
    resource_type_code = serializers.CharField(source='resource_type.code', read_only=True)
    resource_type_name = serializers.CharField(source='resource_type.name', read_only=True)
    identifiers = ResourceIdentifierSerializer(many=True, read_only=True)
    contacts = ResourceContactSerializer(many=True, read_only=True)
    outgoing_count = serializers.IntegerField(read_only=True, default=0)
    incoming_count = serializers.IntegerField(read_only=True, default=0)
    business_context_names = serializers.SerializerMethodField()

    class Meta:
        model = Resource
        fields = '__all__'
        read_only_fields = [
            'uid', 'source', 'consecutive_misses', 'first_seen_at', 'last_seen_at',
            'created_by', 'updated_by', 'created_at', 'updated_at',
        ]

    def create(self, validated_data):
        request = self.context.get('request')
        actor = getattr(getattr(request, 'user', None), 'username', '') or 'system'
        validated_data.update(source='manual', created_by=actor, updated_by=actor)
        resource = super().create(validated_data)
        self._sync_manual_identifiers(resource)
        ResourceChange.objects.create(
            resource=resource,
            action='manual_create',
            new_value=self._snapshot(resource),
            actor=actor,
        )
        return resource

    def get_business_context_names(self, obj):
        return [item.name for item in obj.business_contexts.all()]

    def update(self, instance, validated_data):
        before = self._snapshot(instance)
        governance_fields = {'name', 'display_name', 'environment', 'product', 'business_system', 'primary_ip', 'criticality', 'description', 'status'}
        locked = set(instance.manual_fields or [])
        locked.update(governance_fields.intersection(validated_data))
        if 'attributes' in validated_data:
            old = instance.attributes or {}
            new = validated_data.get('attributes') or {}
            locked.update(f'attributes.{key}' for key in new if old.get(key) != new.get(key))
        validated_data['manual_fields'] = sorted(locked)
        request = self.context.get('request')
        instance.updated_by = getattr(getattr(request, 'user', None), 'username', '') or 'system'
        resource = super().update(instance, validated_data)
        self._sync_manual_identifiers(resource)
        after = self._snapshot(resource)
        actor = resource.updated_by
        for field in sorted(set(before) | set(after)):
            if before.get(field) != after.get(field):
                ResourceChange.objects.create(
                    resource=resource,
                    action='manual_update',
                    field=field,
                    old_value=before.get(field),
                    new_value=after.get(field),
                    actor=actor,
                )
        return resource

    @staticmethod
    def _snapshot(resource):
        return {
            'resource_type': resource.resource_type_id,
            'name': resource.name,
            'display_name': resource.display_name,
            'environment': resource.environment,
            'status': resource.status,
            'primary_ip': str(resource.primary_ip or ''),
            'product': resource.product,
            'business_system': resource.business_system,
            'criticality': resource.criticality,
            'description': resource.description,
            'attributes': resource.attributes or {},
            'business_contexts': list(resource.business_contexts.order_by('id').values_list('id', flat=True)),
        }

    @staticmethod
    def _sync_manual_identifiers(resource):
        # IP addresses are not globally unique identities: multiple middleware
        # instances may share a host or VIP. Keep identifiers per resource and
        # let alert matching report an explicit conflict when labels are vague.
        scope = f'manual:{resource.id}'
        desired = []
        if resource.primary_ip:
            desired.append(('ip', str(resource.primary_ip), True))
        attributes = resource.attributes if isinstance(resource.attributes, dict) else {}
        for kind, key in (('serial_number', 'serial_number'), ('instance_id', 'instance_id')):
            if attributes.get(key):
                desired.append((kind, str(attributes[key]).strip(), not desired))
        endpoint = str(attributes.get('endpoint') or '').strip()
        if endpoint:
            port = attributes.get('port')
            endpoint_value = f'{endpoint}:{port}' if port and ':' not in endpoint else endpoint
            desired.append(('endpoint', endpoint_value, not desired))
            try:
                parsed = urlparse(endpoint if '://' in endpoint else f'//{endpoint}')
                endpoint_ip = str(ipaddress.ip_address((parsed.hostname or endpoint).strip('[]')))
            except (ValueError, TypeError):
                endpoint_ip = ''
            if endpoint_ip and not any(kind == 'ip' and value == endpoint_ip for kind, value, _ in desired):
                desired.append(('ip', endpoint_ip, not desired))
        for kind, value, is_primary in desired:
            ResourceIdentifier.objects.update_or_create(
                kind=kind, scope=scope, value=value,
                defaults={'resource': resource, 'source': 'manual', 'is_primary': bool(is_primary)},
            )
        desired_keys = {(kind, value) for kind, value, _ in desired}
        for identifier in ResourceIdentifier.objects.filter(resource=resource, scope=scope, source='manual'):
            if (identifier.kind, identifier.value) not in desired_keys:
                identifier.delete()
        ResourceIdentifier.objects.filter(
            resource=resource,
            source='manual',
            scope__startswith='type:',
        ).delete()


class ResourceRelationSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='source.display_name', read_only=True)
    target_name = serializers.CharField(source='target.display_name', read_only=True)

    class Meta:
        model = ResourceRelation
        fields = '__all__'

    def validate(self, attrs):
        source = attrs.get('source', getattr(self.instance, 'source', None))
        target = attrs.get('target', getattr(self.instance, 'target', None))
        if source and target and source == target:
            raise serializers.ValidationError('资源不能与自身建立关系')
        return attrs


class DiscoverySourceSerializer(serializers.ModelSerializer):
    k8s_cluster_name = serializers.CharField(source='k8s_cluster.name', read_only=True)
    run_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = DiscoverySource
        fields = '__all__'
        read_only_fields = ['status', 'last_run_at', 'last_success_at', 'last_error', 'created_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        source_type = attrs.get('source_type', getattr(self.instance, 'source_type', ''))
        cluster = attrs.get('k8s_cluster', getattr(self.instance, 'k8s_cluster', None))
        if source_type == 'k8s' and not cluster:
            raise serializers.ValidationError({'k8s_cluster': 'K8S 发现源必须选择集群连接'})
        return attrs


class DiscoveryRunSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='source.name', read_only=True)
    source_type = serializers.CharField(source='source.source_type', read_only=True)

    class Meta:
        model = DiscoveryRun
        fields = '__all__'
        read_only_fields = [field.name for field in DiscoveryRun._meta.fields]


class ResourceSourceBindingSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='source.name', read_only=True)

    class Meta:
        model = ResourceSourceBinding
        fields = '__all__'
        read_only_fields = [field.name for field in ResourceSourceBinding._meta.fields]


class RuntimeResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = RuntimeResource
        fields = '__all__'
        read_only_fields = [field.name for field in RuntimeResource._meta.fields]


class ResourceChangeSerializer(serializers.ModelSerializer):
    discovery_run_status = serializers.CharField(source='discovery_run.status', read_only=True)

    class Meta:
        model = ResourceChange
        fields = '__all__'


class ResourceNodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResourceNode
        fields = '__all__'
        read_only_fields = [field.name for field in ResourceChange._meta.fields]
