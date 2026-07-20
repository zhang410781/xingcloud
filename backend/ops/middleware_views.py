from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from rbac.permissions import build_rbac_permission
from rbac.services import DEMO_ACCOUNT_MUTATION_MESSAGE, is_demo_account

from .models import MiddlewareAsset, TaskResourceGroup


ASSET_TYPES = {choice[0] for choice in MiddlewareAsset.TYPE_CHOICES}
ASSET_STATUSES = {choice[0] for choice in MiddlewareAsset.STATUS_CHOICES}


def _clean(value):
    return str(value or '').strip()


def _serialize_asset(asset):
    groups = list(asset.business_groups.order_by('sort_order', 'name', 'id'))
    return {
        'id': asset.id,
        'name': asset.name,
        'asset_type': asset.asset_type,
        'asset_type_label': asset.get_asset_type_display(),
        'task_resource_environment_id': asset.task_resource_environment_id,
        'task_resource_environment_name': getattr(asset.task_resource_environment, 'name', ''),
        'business_group_ids': [item.id for item in groups],
        'business_group_names': [item.name for item in groups],
        'environment': asset.environment,
        'endpoint': asset.endpoint,
        'username': asset.username,
        'password_configured': bool(asset.password),
        'version': asset.version,
        'status': asset.status,
        'status_label': asset.get_status_display(),
        'description': asset.description,
        'metadata': asset.metadata or {},
        'created_by': asset.created_by,
        'updated_by': asset.updated_by,
        'created_at': asset.created_at.isoformat() if asset.created_at else None,
        'updated_at': asset.updated_at.isoformat() if asset.updated_at else None,
    }


def _build_overview(task_resource_environment_id=None):
    queryset = MiddlewareAsset.objects.select_related('task_resource_environment').prefetch_related('business_groups')
    if task_resource_environment_id:
        queryset = queryset.filter(business_groups__id=task_resource_environment_id).distinct()
    assets = list(queryset)
    by_type = {asset_type: 0 for asset_type in ASSET_TYPES}
    by_status = {status: 0 for status in ASSET_STATUSES}
    for asset in assets:
        by_type[asset.asset_type] += 1
        by_status[asset.status] += 1
    return {
        'updated_at': timezone.now().isoformat(),
        'assets': [_serialize_asset(asset) for asset in assets],
        'summary': {
            'total': len(assets),
            'by_type': by_type,
            'by_status': by_status,
        },
    }


def _validate_payload(payload, *, partial=False):
    payload = payload if isinstance(payload, dict) else {}
    cleaned = {}
    required_fields = ('name', 'asset_type', 'endpoint')
    for field in required_fields:
        if field in payload or not partial:
            cleaned[field] = _clean(payload.get(field))
            if not cleaned[field]:
                return None, f'{field} is required.'

    if 'asset_type' in cleaned and cleaned['asset_type'] not in ASSET_TYPES:
        return None, 'Unsupported middleware asset type.'

    for field in ('version', 'description', 'username'):
        if field in payload:
            cleaned[field] = _clean(payload.get(field))

    if 'password' in payload:
        password = str(payload.get('password') or '')
        if password and password != '******':
            cleaned['password'] = password

    if 'status' in payload:
        cleaned['status'] = _clean(payload.get('status'))
        if cleaned['status'] not in ASSET_STATUSES:
            return None, 'Unsupported middleware asset status.'

    if 'metadata' in payload:
        if not isinstance(payload.get('metadata'), dict):
            return None, 'metadata must be an object.'
        cleaned['metadata'] = payload.get('metadata')
    if 'task_resource_environment_id' in payload:
        try:
            cleaned['task_resource_environment_id'] = int(payload.get('task_resource_environment_id'))
        except (TypeError, ValueError):
            return None, 'task_resource_environment_id must be an integer.'
    if 'business_group_ids' in payload:
        raw_ids = payload.get('business_group_ids') or []
        if not isinstance(raw_ids, list):
            return None, 'business_group_ids must be an array.'
        try:
            cleaned['business_group_ids'] = list(dict.fromkeys(int(item) for item in raw_ids if item not in ('', None)))
        except (TypeError, ValueError):
            return None, 'business_group_ids must contain integers.'
    return cleaned, ''


def _validate_asset_environment(cleaned):
    group_ids = cleaned.get('business_group_ids') or []
    if not group_ids and cleaned.get('task_resource_environment_id'):
        group_ids = [cleaned['task_resource_environment_id']]
    groups = list(TaskResourceGroup.objects.filter(
        pk__in=group_ids,
        group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
    ).order_by('sort_order', 'name', 'id'))
    if not groups or len(groups) != len(set(group_ids)):
        return None, '请至少选择一个有效的一级资产业务分组。'
    cleaned['business_group_ids'] = [item.id for item in groups]
    cleaned['task_resource_environment_id'] = groups[0].id
    cleaned['environment'] = 'production'
    return groups, ''

    environment_id = cleaned.get('task_resource_environment_id')
    if not environment_id:
        matches = list(TaskResourceGroup.objects.filter(
            group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
            code=cleaned.get('environment'),
        )[:2])
        if len(matches) != 1:
            return None, '请选择业务上下文绑定的资产环境分组。'
        cleaned['task_resource_environment_id'] = matches[0].id
        return matches[0], ''
    group = TaskResourceGroup.objects.filter(
        pk=environment_id,
        group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
    ).first()
    if not group:
        return None, '资产环境分组不存在或类型不正确。'
    cleaned['environment'] = group.code
    return group, ''


def _actor_name(user):
    if not user:
        return ''
    return _clean(user.get_username()) or _clean(getattr(user, 'email', '')) or 'system'


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.middleware.view')])
def middleware_overview(request):
    environment_id = request.query_params.get('task_resource_environment_id')
    return Response(_build_overview(environment_id))


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.middleware.manage')])
def middleware_action(request):
    action_name = _clean(request.data.get('action'))
    target_id = request.data.get('target_id')
    payload = request.data.get('payload') or {}

    # Accept the previous module field during one compatibility cycle, but never
    # recreate the old cached demo state.
    if isinstance(payload, dict) and not payload.get('asset_type') and request.data.get('module'):
        payload = {**payload, 'asset_type': _clean(request.data.get('module'))}
    if action_name == 'create_cluster':
        action_name = 'create_asset'

    if action_name not in {'create_asset', 'update_asset', 'delete_asset'}:
        return Response({'detail': 'Unsupported middleware asset action.'}, status=400)
    if is_demo_account(request.user):
        return Response({'detail': DEMO_ACCOUNT_MUTATION_MESSAGE}, status=403)

    actor = _actor_name(request.user)
    if action_name == 'create_asset':
        cleaned, error = _validate_payload(payload)
        if error:
            return Response({'detail': error}, status=400)
        _, error = _validate_asset_environment(cleaned)
        if error:
            return Response({'detail': error}, status=400)
        password = cleaned.pop('password', '')
        business_group_ids = cleaned.pop('business_group_ids', [])
        try:
            with transaction.atomic():
                asset = MiddlewareAsset.objects.create(
                    **cleaned,
                    password=password,
                    created_by=actor,
                    updated_by=actor,
                )
                asset.business_groups.set(business_group_ids)
        except IntegrityError:
            return Response({'detail': '同类型、同环境下的资产名称已存在。'}, status=400)
        return Response({
            'success': True,
            'message': '中间件资产已登记。',
            'asset': _serialize_asset(asset),
            'data': _build_overview(),
        }, status=201)

    try:
        asset = MiddlewareAsset.objects.select_related('task_resource_environment').prefetch_related('business_groups').get(pk=target_id)
    except (MiddlewareAsset.DoesNotExist, TypeError, ValueError):
        return Response({'detail': 'Middleware asset not found.'}, status=404)

    if action_name == 'delete_asset':
        asset.delete()
        return Response({
            'success': True,
            'message': '中间件资产已删除。',
            'data': _build_overview(),
        })

    cleaned, error = _validate_payload(payload, partial=True)
    if error:
        return Response({'detail': error}, status=400)
    if not cleaned:
        return Response({'detail': 'No middleware asset fields to update.'}, status=400)
    if 'task_resource_environment_id' in cleaned or 'business_group_ids' in cleaned:
        _, error = _validate_asset_environment(cleaned)
        if error:
            return Response({'detail': error}, status=400)
    business_group_ids = cleaned.pop('business_group_ids', None)
    for field, value in cleaned.items():
        setattr(asset, field, value)
    asset.updated_by = actor
    try:
        with transaction.atomic():
            asset.save()
            if business_group_ids is not None:
                asset.business_groups.set(business_group_ids)
    except IntegrityError:
        return Response({'detail': '同类型、同环境下的资产名称已存在。'}, status=400)
    return Response({
        'success': True,
        'message': '中间件资产已更新。',
        'asset': _serialize_asset(asset),
        'data': _build_overview(),
    })
