from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from rbac.permissions import RBACPermissionMixin

from .discovery import ensure_builtin_resource_types, execute_discovery_run, preview_source
from .models import DiscoveryRun, DiscoverySource, Resource, ResourceContact, ResourceRelation, ResourceType, RuntimeResource
from .serializers import (
    DiscoveryRunSerializer,
    DiscoverySourceSerializer,
    ResourceContactSerializer,
    ResourceChangeSerializer,
    ResourceRelationSerializer,
    ResourceSerializer,
    ResourceTypeSerializer,
    RuntimeResourceSerializer,
)


class ResourceTypeViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = ResourceTypeSerializer
    pagination_class = None
    rbac_permissions = {
        'list': ['cmdb.ci.view'], 'retrieve': ['cmdb.ci.view'],
        'create': ['cmdb.ci.manage'], 'update': ['cmdb.ci.manage'],
        'partial_update': ['cmdb.ci.manage'], 'destroy': ['cmdb.ci.manage'],
    }

    def get_queryset(self):
        ensure_builtin_resource_types()
        return ResourceType.objects.annotate(resource_count=Count('resources')).filter(is_enabled=True)

    def perform_destroy(self, instance):
        if instance.is_builtin:
            from rest_framework.exceptions import ValidationError
            raise ValidationError('内置资源类型不能删除')
        super().perform_destroy(instance)


class ResourceViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = ResourceSerializer
    rbac_permissions = {
        'list': ['cmdb.ci.view'], 'retrieve': ['cmdb.ci.view'], 'summary': ['cmdb.ci.view'],
        'topology': ['cmdb.topology.view'], 'runtime': ['cmdb.ci.view'],
        'changes': ['cmdb.ci.view'],
        'business_context_options': ['cmdb.ci.view'],
        'create': ['cmdb.ci.manage'], 'update': ['cmdb.ci.manage'],
        'partial_update': ['cmdb.ci.manage'], 'destroy': ['cmdb.ci.manage'],
    }

    def get_queryset(self):
        queryset = Resource.objects.select_related('resource_type').prefetch_related(
            'identifiers', 'contacts', 'business_contexts',
        ).annotate(
            outgoing_count=Count('outgoing_relations', distinct=True),
            incoming_count=Count('incoming_relations', distinct=True),
        )
        params = self.request.query_params
        if params.get('type'):
            queryset = queryset.filter(resource_type__code=params['type'])
        if params.get('category'):
            queryset = queryset.filter(resource_type__category=params['category'])
        if params.get('status'):
            queryset = queryset.filter(status=params['status'])
        if params.get('environment'):
            queryset = queryset.filter(environment=params['environment'])
        if params.get('product'):
            queryset = queryset.filter(product=params['product'])
        if params.get('source'):
            queryset = queryset.filter(source=params['source'])
        search = (params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(display_name__icontains=search) |
                Q(primary_ip__icontains=search) | Q(product__icontains=search) |
                Q(identifiers__value__icontains=search)
            ).distinct()
        return queryset.order_by('resource_type__category', 'resource_type__name', 'name', 'id')

    @action(detail=False, methods=['get'])
    def summary(self, request):
        ensure_builtin_resource_types()
        by_type = list(
            Resource.objects.values('resource_type__code', 'resource_type__name')
            .annotate(count=Count('id')).order_by('resource_type__category', 'resource_type__name')
        )
        by_status = {item['status']: item['count'] for item in Resource.objects.values('status').annotate(count=Count('id'))}
        return Response({
            'total': Resource.objects.count(),
            'active': by_status.get('active', 0),
            'warning': by_status.get('warning', 0),
            'missing': by_status.get('missing', 0) + by_status.get('offline', 0),
            'by_type': by_type,
            'discovery_sources': DiscoverySource.objects.count(),
            'last_discovery_at': DiscoveryRun.objects.filter(status__in=['completed', 'partial']).order_by('-finished_at').values_list('finished_at', flat=True).first(),
        })

    @action(detail=False, methods=['get'])
    def topology(self, request):
        resources = self.get_queryset()[:500]
        resource_ids = [item.id for item in resources]
        relations = ResourceRelation.objects.filter(source_id__in=resource_ids, target_id__in=resource_ids).select_related('source', 'target')[:1000]
        return Response({
            'nodes': ResourceSerializer(resources, many=True).data,
            'edges': ResourceRelationSerializer(relations, many=True).data,
            'truncated': len(resource_ids) >= 500,
        })

    @action(detail=False, methods=['get'], url_path='business-context-options')
    def business_context_options(self, request):
        from aiops.models import AIOpsKnowledgeEnvironment

        rows = AIOpsKnowledgeEnvironment.objects.filter(is_enabled=True).order_by('name', 'id')
        return Response(list(rows.values('id', 'name', 'code', 'business_line', 'environment_type')))

    @action(detail=True, methods=['get'])
    def runtime(self, request, pk=None):
        resource = self.get_object()
        rows = RuntimeResource.objects.filter(cluster_resource=resource, expires_at__gte=timezone.now())
        if request.query_params.get('kind'):
            rows = rows.filter(kind=request.query_params['kind'])
        if request.query_params.get('namespace'):
            rows = rows.filter(namespace=request.query_params['namespace'])
        return Response(RuntimeResourceSerializer(rows.order_by('kind', 'namespace', 'name')[:1000], many=True).data)

    @action(detail=True, methods=['get'])
    def changes(self, request, pk=None):
        resource = self.get_object()
        rows = resource.changes.select_related('discovery_run').order_by('-created_at', '-id')[:100]
        return Response(ResourceChangeSerializer(rows, many=True).data)


class ResourceRelationViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = ResourceRelation.objects.select_related('source', 'target')
    serializer_class = ResourceRelationSerializer
    rbac_permissions = {
        'list': ['cmdb.topology.view'], 'retrieve': ['cmdb.topology.view'],
        'create': ['cmdb.ci.manage'], 'update': ['cmdb.ci.manage'],
        'partial_update': ['cmdb.ci.manage'], 'destroy': ['cmdb.ci.manage'],
    }


class ResourceContactViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = ResourceContact.objects.select_related('resource', 'user', 'recipient')
    serializer_class = ResourceContactSerializer
    rbac_permissions = {
        'list': ['cmdb.ci.view'], 'retrieve': ['cmdb.ci.view'],
        'create': ['cmdb.ci.manage'], 'update': ['cmdb.ci.manage'],
        'partial_update': ['cmdb.ci.manage'], 'destroy': ['cmdb.ci.manage'],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get('resource'):
            queryset = queryset.filter(resource_id=self.request.query_params['resource'])
        return queryset


class DiscoverySourceViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = DiscoverySourceSerializer
    pagination_class = None
    rbac_permissions = {
        'list': ['cmdb.ci.view'], 'retrieve': ['cmdb.ci.view'],
        'create': ['cmdb.ci.manage'], 'update': ['cmdb.ci.manage'],
        'partial_update': ['cmdb.ci.manage'], 'destroy': ['cmdb.ci.manage'],
        'preview': ['cmdb.ci.manage'], 'run': ['cmdb.ci.manage'],
    }

    def get_queryset(self):
        return DiscoverySource.objects.select_related('k8s_cluster').annotate(run_count=Count('runs'))

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.username or 'system', next_run_at=timezone.now())

    @action(detail=True, methods=['post'])
    def preview(self, request, pk=None):
        source = self.get_object()
        try:
            return Response(preview_source(source))
        except Exception as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def run(self, request, pk=None):
        source = self.get_object()
        active = source.runs.filter(status__in=['pending', 'connecting', 'collecting', 'reconciling']).first()
        if active:
            return Response(DiscoveryRunSerializer(active).data)
        run = DiscoveryRun.objects.create(source=source, trigger='manual')
        if request.query_params.get('wait') == 'true':
            execute_discovery_run(run)
        return Response(DiscoveryRunSerializer(run).data, status=status.HTTP_201_CREATED)


class DiscoveryRunViewSet(RBACPermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = DiscoveryRunSerializer
    rbac_permissions = {'list': ['cmdb.ci.view'], 'retrieve': ['cmdb.ci.view']}

    def get_queryset(self):
        queryset = DiscoveryRun.objects.select_related('source')
        if self.request.query_params.get('source'):
            queryset = queryset.filter(source_id=self.request.query_params['source'])
        return queryset
