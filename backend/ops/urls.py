from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import loki_views
from . import log_views
from . import docker_views
from . import k8s_views
from . import middleware_views
from . import observability_views

router = DefaultRouter()
router.register(r'hosts', views.HostViewSet)
router.register(r'task-resource-groups', views.TaskResourceGroupViewSet, basename='task-resource-group')
router.register(r'task-resources', views.TaskResourceViewSet, basename='task-resource')
router.register(r'host-tasks', views.HostTaskViewSet, basename='host-task')
router.register(r'host-task-templates', views.HostTaskTemplateViewSet, basename='host-task-template')
router.register(r'host-task-schedules', views.HostTaskScheduleViewSet, basename='host-task-schedule')
router.register(r'host-task-schedule-executions', views.HostTaskScheduleExecutionViewSet, basename='host-task-schedule-execution')
router.register(r'deployment-approval-flows', views.DeploymentApprovalFlowViewSet, basename='deployment-approval-flow')
router.register(r'deployments', views.DeploymentViewSet)
router.register(r'transaction-tickets', views.TransactionTicketViewSet, basename='transaction-ticket')
router.register(r'alerts', views.AlertViewSet)
router.register(r'alert-rules', views.AlertRuleViewSet, basename='alert-rule')
router.register(r'alert-rule-templates', views.AlertRuleTemplateViewSet, basename='alert-rule-template')
router.register(r'alert-silences', views.AlertSilenceViewSet, basename='alert-silence')
router.register(r'alert-recipients', views.AlertRecipientViewSet, basename='alert-recipient')
router.register(r'alert-recipient-groups', views.AlertRecipientGroupViewSet, basename='alert-recipient-group')
router.register(r'alert-notification-channels', views.AlertNotificationChannelViewSet, basename='alert-notification-channel')
router.register(r'alert-notification-policies', views.AlertNotificationPolicyViewSet, basename='alert-notification-policy')
router.register(r'alert-notification-rules', views.AlertNotificationPolicyViewSet, basename='alert-notification-rule-compat')
router.register(r'alert-notification-logs', views.AlertNotificationLogViewSet, basename='alert-notification-log')
router.register(r'inspection-report-schedules', views.InspectionReportScheduleViewSet, basename='inspection-report-schedule')
router.register(r'inspection-report-executions', views.InspectionReportExecutionViewSet, basename='inspection-report-execution')
router.register(r'alert-actions', views.AlertActionViewSet, basename='alert-action')
router.register(r'logs', views.LogEntryViewSet)
router.register(r'log/datasources', log_views.LogDataSourceViewSet, basename='log-datasource')
router.register(r'observability/metric/datasources', observability_views.MetricDataSourceViewSet, basename='metric-datasource')
router.register(r'observability/dashboard-definitions', observability_views.ObservabilityDashboardViewSet, basename='observability-dashboard-definition')
router.register(r'k8s/clusters', k8s_views.K8sClusterViewSet)
router.register(r'docker/hosts', docker_views.DockerHostViewSet)
urlpatterns = [
    path('dashboard/stats/', views.dashboard_stats, name='dashboard-stats'),
    path('alerts/card-actions/<uuid:token>/', views.alert_card_action, name='alert-card-action'),
    path('log/providers/', log_views.log_providers, name='log-providers'),
    path('log/providers/<str:provider>/catalog/', log_views.log_provider_catalog, name='log-provider-catalog'),
    path('log/query/', log_views.log_query, name='log-query'),
    # Loki 代理
    path('loki/labels/', loki_views.loki_labels, name='loki-labels'),
    path('loki/label/<str:label_name>/values/', loki_views.loki_label_values, name='loki-label-values'),
    path('loki/query_range/', loki_views.loki_query_range, name='loki-query-range'),
    path('loki/series/', loki_views.loki_series, name='loki-series'),
    # Docker 容器管理
    path('docker/containers/', docker_views.list_containers, name='docker-containers'),
    path('docker/images/', docker_views.list_images, name='docker-images'),
    path('docker/images/remove/', docker_views.remove_images, name='docker-images-remove'),
    path('docker/images/prune/', docker_views.prune_dangling_images, name='docker-images-prune'),
    path('docker/containers/<str:container_id>/action/', docker_views.container_action, name='docker-container-action'),
    path('docker/containers/<str:container_id>/remove/', docker_views.container_remove, name='docker-container-remove'),
    path('docker/containers/<str:container_id>/logs/', docker_views.container_logs, name='docker-container-logs'),
    path('docker/containers/<str:container_id>/inspect/', docker_views.container_inspect, name='docker-container-inspect'),
    path('middleware/overview/', middleware_views.middleware_overview, name='middleware-overview'),
    path('middleware/action/', middleware_views.middleware_action, name='middleware-action'),
    path('observability/overview/', observability_views.observability_overview, name='observability-overview'),
    path('observability/integrations/', observability_views.observability_integrations, name='observability-integrations'),
    path('observability/integrations/<str:key>/install-rules/', observability_views.install_integration_rules, name='observability-integration-install-rules'),
    path('observability/integrations/<str:key>/install-dashboards/', observability_views.install_integration_dashboards, name='observability-integration-install-dashboards'),
    path('observability/sla/summary/', observability_views.sla_summary, name='observability-sla-summary'),
    path('observability/metrics/query/', observability_views.metrics_promql_query, name='observability-metrics-query'),
    path('observability/metrics/series-names/', observability_views.metrics_series_names, name='observability-metrics-series-names'),

    path('', include(router.urls)),
]
