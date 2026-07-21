# Xing-Cloud Observability Alert UI Redesign Implementation Plan

> **历史实施计划，不代表当前产品状态。** 当前菜单和页面以仓库现有路由为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the new Xing-Cloud observability frontend around monitoring integrations, explicit alert sources, guided alert rule creation, a rule template catalog, and a JSON-dashboard-only monitoring dashboard experience.

**Architecture:** Backend adds a code-defined observability integration registry and install/dry-run APIs that reuse existing models. Frontend ignores old UI constraints and replaces legacy dashboard/rule entry flows with new catalog and wizard components. Dashboards are queried only through `ObservabilityDashboard` definitions; the old hard-coded dashboard query API is removed.

**Tech Stack:** Django REST Framework, Django ORM, Vue 3 Composition API, Element Plus, existing Xing-Cloud CSS tokens, existing `NativeDashboardChart.vue`, Prometheus and ClickHouse query services.

---

## File Structure

Backend files:

- Create `backend/ops/observability_integrations.py`: code-defined registry for MySQL, Redis, PostgreSQL, Kafka, Kubernetes, Linux Server, ClickHouse Logs, Ingress Access Logs, and SLA Risk.
- Create `backend/ops/alert_rule_presets.py`: seed built-in alert rule templates and create rules from templates.
- Modify `backend/ops/dashboard_presets.py`: expand built-in JSON dashboard definitions and ensure old native dashboard panels are available as JSON definitions.
- Modify `backend/ops/observability_views.py`: add integrations API, install-rule API, install-dashboard API, draft dry-run API, dashboard summary based on dashboard definitions, and remove old hard-coded dashboard query functions.
- Modify `backend/ops/urls.py`: add new observability integration and draft dry-run routes, and remove the old `observability/dashboards/query/` route.
- Modify `backend/ops/views.py`: expose `dry_run_draft` on `AlertRuleViewSet`.
- Modify `backend/ops/tests.py`: cover registry, template install, dashboard install, draft dry-run, and dashboard-definition-only behavior.

Frontend files:

- Modify `frontend/src/router/index.js`: add `/observability/integrations`, add `/observability/alerts`, redirect `/alerts` to `/observability/alerts`.
- Modify `frontend/src/layout/AppLayout.vue`: add Monitoring Integrations menu entry and point Alert Center to `/observability/alerts`.
- Modify `frontend/src/api/modules/ops.js`: add integration APIs and draft dry-run API; remove `queryMonitoringDashboard`.
- Create `frontend/src/views/ObservabilityIntegrations.vue`: monitoring integration catalog page.
- Replace user-facing structure in `frontend/src/views/NativeMonitoringDashboard.vue`: JSON dashboard catalog and viewer only.
- Modify `frontend/src/views/Alerts.vue`: use new source matrix, rule wizard, and template catalog components.
- Modify `frontend/src/components/observability/ObservabilityRouteTabs.vue`: include integrations, alerts, dashboards, metrics, logs, and data sources.
- Create `frontend/src/components/observability/IntegrationCard.vue`.
- Create `frontend/src/components/observability/AlertSourceMatrix.vue`.
- Create `frontend/src/components/observability/AlertRuleWizard.vue`.
- Create `frontend/src/components/observability/RuleTemplateCatalog.vue`.
- Create `frontend/src/components/observability/DashboardCatalog.vue`.
- Create `frontend/src/components/observability/JsonAssetImportDialog.vue`.

Docs:

- Update `docs/历史设计/可观测与告警/Xing-Cloud可观测告警前端重设计方案.md` if implementation changes the agreed API names.

---

### Task 1: Backend Integration Registry

**Files:**
- Create: `backend/ops/observability_integrations.py`
- Modify: `backend/ops/observability_views.py`
- Modify: `backend/ops/urls.py`
- Test: `backend/ops/tests.py`

- [ ] **Step 1: Write failing registry API test**

Add this test method to the existing observability test class in `backend/ops/tests.py`:

```python
def test_observability_integrations_returns_catalog_and_status(self):
    from ops.models import MetricDataSource

    MetricDataSource.objects.create(
        name='Default Prometheus',
        provider='prometheus',
        endpoint='http://prometheus.local:9090',
        is_default=True,
        is_enabled=True,
        health_query='up',
        last_check_status='ok',
    )

    response = self.client.get('/api/observability/integrations/')

    self.assertEqual(response.status_code, 200)
    payload = response.json()
    keys = [item['key'] for item in payload['integrations']]
    self.assertIn('mysql', keys)
    self.assertIn('redis', keys)
    self.assertIn('kafka', keys)
    mysql = next(item for item in payload['integrations'] if item['key'] == 'mysql')
    self.assertEqual(mysql['brand'], 'Xing-Cloud')
    self.assertEqual(mysql['source_types'], ['prometheus'])
    self.assertIn(mysql['status'], ['source_available', 'rules_installed', 'dashboards_installed'])
    self.assertGreaterEqual(mysql['template_count'], 0)
    self.assertGreaterEqual(mysql['dashboard_count'], 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python manage.py test ops.tests.ObservabilityViewsTests.test_observability_integrations_returns_catalog_and_status --verbosity 2
```

Expected: FAIL with 404 for `/api/observability/integrations/`.

- [ ] **Step 3: Create integration registry**

Create `backend/ops/observability_integrations.py`:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ObservabilityIntegration:
    key: str
    title: str
    category: str
    source_types: list[str]
    tags: list[str]
    icon: str
    guide_path: str
    template_codes: list[str] = field(default_factory=list)
    dashboard_titles: list[str] = field(default_factory=list)
    metric_probe_queries: list[str] = field(default_factory=list)
    log_collections: list[str] = field(default_factory=list)


INTEGRATIONS = [
    ObservabilityIntegration(
        key='mysql',
        title='MySQL',
        category='middleware',
        source_types=['prometheus'],
        tags=['database', 'mysql'],
        icon='DataBase',
        guide_path='docs/监控告警/中间件监控教学/2. 部署mysql服务并监控mysql.md',
        template_codes=['mysql-down', 'mysql-high-connections', 'mysql-high-running-threads', 'mysql-slow-queries'],
        dashboard_titles=['MySQL Overview'],
        metric_probe_queries=['mysql_up', 'mysql_global_status_threads_connected'],
    ),
    ObservabilityIntegration(
        key='redis',
        title='Redis',
        category='middleware',
        source_types=['prometheus'],
        tags=['cache', 'redis'],
        icon='Coin',
        guide_path='docs/监控告警/中间件监控教学/',
        template_codes=['redis-down', 'redis-high-memory', 'redis-high-clients', 'redis-evicted-keys'],
        dashboard_titles=['Redis Overview'],
        metric_probe_queries=['redis_up', 'redis_connected_clients'],
    ),
    ObservabilityIntegration(
        key='postgresql',
        title='PostgreSQL',
        category='middleware',
        source_types=['prometheus'],
        tags=['database', 'postgresql'],
        icon='DataBase',
        guide_path='docs/监控告警/中间件监控教学/4. 部署postgresql服务并监控postgresql.md',
        template_codes=['postgresql-down', 'postgresql-high-connections'],
        dashboard_titles=['PostgreSQL Overview'],
        metric_probe_queries=['pg_up'],
    ),
    ObservabilityIntegration(
        key='kafka',
        title='Kafka',
        category='middleware',
        source_types=['prometheus'],
        tags=['queue', 'kafka'],
        icon='Connection',
        guide_path='docs/监控告警/中间件监控教学/',
        template_codes=['kafka-broker-down', 'kafka-consumer-lag', 'kafka-offline-partitions'],
        dashboard_titles=['Kafka Overview'],
        metric_probe_queries=['kafka_brokers', 'kafka_consumergroup_lag'],
    ),
    ObservabilityIntegration(
        key='kubernetes',
        title='Kubernetes',
        category='platform',
        source_types=['prometheus', 'clickhouse'],
        tags=['k8s', 'cluster'],
        icon='Histogram',
        guide_path='docs/历史设计/可观测与告警/',
        template_codes=['k8s-node-not-ready', 'k8s-abnormal-pods', 'k8s-pod-restarts'],
        dashboard_titles=['Kubernetes Cluster Health', 'ClickHouse K8S Events'],
        metric_probe_queries=['kube_node_info', 'kube_pod_info'],
        log_collections=['k8s-events'],
    ),
    ObservabilityIntegration(
        key='linux',
        title='Linux Server',
        category='infrastructure',
        source_types=['prometheus'],
        tags=['server', 'linux'],
        icon='Monitor',
        guide_path='docs/历史设计/可观测与告警/',
        template_codes=['linux-node-down', 'linux-high-cpu', 'linux-high-memory', 'linux-high-disk'],
        dashboard_titles=['Linux Server Resources'],
        metric_probe_queries=['node_uname_info', 'node_cpu_seconds_total'],
    ),
    ObservabilityIntegration(
        key='clickhouse-logs',
        title='ClickHouse Logs',
        category='logs',
        source_types=['clickhouse'],
        tags=['logs', 'clickhouse', 'container'],
        icon='Search',
        guide_path='docs/历史设计/可观测与告警/',
        template_codes=['container-error-spike'],
        dashboard_titles=['ClickHouse Container Logs'],
        log_collections=['container-logs'],
    ),
    ObservabilityIntegration(
        key='ingress-access',
        title='Ingress Access Logs',
        category='logs',
        source_types=['clickhouse'],
        tags=['ingress', 'web'],
        icon='TrendCharts',
        guide_path='docs/历史设计/可观测与告警/',
        template_codes=['ingress-5xx-spike', 'ingress-latency-high'],
        dashboard_titles=['Ingress Access Logs'],
        log_collections=['ingress-access'],
    ),
    ObservabilityIntegration(
        key='sla-risk',
        title='SLA Risk',
        category='sla',
        source_types=['sla'],
        tags=['sla', 'risk'],
        icon='Odometer',
        guide_path='docs/历史设计/可观测与告警/可观测告警引擎设计方案.md',
        template_codes=['sla-monthly-risk'],
        dashboard_titles=['SLA Risk Cockpit'],
    ),
]


def list_integrations():
    return INTEGRATIONS


def get_integration(key):
    for integration in INTEGRATIONS:
        if integration.key == key:
            return integration
    return None
```

- [ ] **Step 4: Add integration status view**

In `backend/ops/observability_views.py`, import the registry:

```python
from .observability_integrations import get_integration, list_integrations
```

Add helper and view:

```python
def _integration_status(integration):
    template_count = AlertRuleTemplate.objects.filter(code__in=integration.template_codes, is_enabled=True).count()
    rule_count = AlertRule.objects.filter(template__code__in=integration.template_codes).count()
    dashboard_count = ObservabilityDashboard.objects.filter(title__in=integration.dashboard_titles, is_enabled=True).count()
    metric_ready = MetricDataSource.objects.filter(is_enabled=True, last_check_status='ok').exists()
    log_ready = LogDataSource.objects.filter(provider='clickhouse', is_enabled=True, last_check_status='ok').exists()
    source_available = (
        'sla' in integration.source_types
        or ('prometheus' in integration.source_types and metric_ready)
        or ('clickhouse' in integration.source_types and log_ready)
    )
    if dashboard_count and rule_count:
        status_value = 'dashboards_installed'
    elif rule_count:
        status_value = 'rules_installed'
    elif source_available:
        status_value = 'source_available'
    else:
        status_value = 'not_connected'
    return template_count, rule_count, dashboard_count, status_value


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.monitor.dashboard.view')])
def observability_integrations(request):
    ensure_builtin_dashboards()
    items = []
    for integration in list_integrations():
        template_count, rule_count, dashboard_count, status_value = _integration_status(integration)
        items.append({
            'key': integration.key,
            'title': integration.title,
            'brand': 'Xing-Cloud',
            'category': integration.category,
            'source_types': integration.source_types,
            'tags': integration.tags,
            'icon': integration.icon,
            'guide_path': integration.guide_path,
            'template_codes': integration.template_codes,
            'dashboard_titles': integration.dashboard_titles,
            'metric_probe_queries': integration.metric_probe_queries,
            'log_collections': integration.log_collections,
            'template_count': template_count,
            'rule_count': rule_count,
            'dashboard_count': dashboard_count,
            'status': status_value,
        })
    return Response({'integrations': items})
```

- [ ] **Step 5: Wire URL**

In `backend/ops/urls.py`, add:

```python
path('observability/integrations/', observability_views.observability_integrations, name='observability-integrations'),
```

- [ ] **Step 6: Run test to verify it passes**

Run:

```bash
python manage.py test ops.tests.ObservabilityViewsTests.test_observability_integrations_returns_catalog_and_status --verbosity 2
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/ops/observability_integrations.py backend/ops/observability_views.py backend/ops/urls.py backend/ops/tests.py
git commit -m "feat: add observability integration registry"
```

---

### Task 2: Built-In Alert Templates and Rule Installation

**Files:**
- Create: `backend/ops/alert_rule_presets.py`
- Modify: `backend/ops/observability_views.py`
- Modify: `backend/ops/urls.py`
- Test: `backend/ops/tests.py`

- [ ] **Step 1: Write failing template install test**

Add to `backend/ops/tests.py`:

```python
def test_install_integration_rules_creates_rules_from_builtin_templates(self):
    response = self.client.post(
        '/api/observability/integrations/redis/install-rules/',
        {'template_codes': ['redis-down', 'redis-high-memory']},
        format='json',
    )

    self.assertEqual(response.status_code, 201)
    payload = response.json()
    self.assertEqual(payload['created_count'], 2)
    self.assertEqual(payload['skipped_count'], 0)
    self.assertTrue(AlertRule.objects.filter(code__startswith='redis-down').exists())
    self.assertTrue(AlertRuleTemplate.objects.filter(code='redis-down', is_builtin=True).exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python manage.py test ops.tests.ObservabilityViewsTests.test_install_integration_rules_creates_rules_from_builtin_templates --verbosity 2
```

Expected: FAIL with 404.

- [ ] **Step 3: Create alert rule presets**

Create `backend/ops/alert_rule_presets.py` with a compact seed list:

```python
from .models import AlertRule, AlertRuleTemplate


BUILTIN_ALERT_RULE_TEMPLATES = [
    {
        'code': 'redis-down',
        'name': 'Redis Down',
        'source_type': 'prometheus',
        'level': 'critical',
        'query_config': {'query': 'redis_up == 0', 'value_path': 'value'},
        'condition': {'operator': '>', 'threshold': 0},
        'default_labels': {'integration': 'redis', 'service': 'redis'},
        'annotations': {'summary': 'Redis exporter reports the instance is down'},
        'interval_seconds': 60,
        'duration_seconds': 60,
        'notify_enabled': True,
        'auto_analyze': True,
        'description': 'Redis availability rule based on redis_up.',
    },
    {
        'code': 'redis-high-memory',
        'name': 'Redis High Memory Usage',
        'source_type': 'prometheus',
        'level': 'warning',
        'query_config': {'query': 'redis_memory_used_bytes / redis_memory_max_bytes * 100', 'value_path': 'value'},
        'condition': {'operator': '>', 'threshold': 85},
        'default_labels': {'integration': 'redis', 'service': 'redis'},
        'annotations': {'summary': 'Redis memory usage is higher than 85%'},
        'interval_seconds': 60,
        'duration_seconds': 120,
        'notify_enabled': True,
        'auto_analyze': False,
        'description': 'Redis memory pressure rule.',
    },
    {
        'code': 'mysql-down',
        'name': 'MySQL Down',
        'source_type': 'prometheus',
        'level': 'critical',
        'query_config': {'query': 'mysql_up == 0', 'value_path': 'value'},
        'condition': {'operator': '>', 'threshold': 0},
        'default_labels': {'integration': 'mysql', 'service': 'mysql'},
        'annotations': {'summary': 'MySQL exporter reports the instance is down'},
        'interval_seconds': 60,
        'duration_seconds': 60,
        'notify_enabled': True,
        'auto_analyze': True,
        'description': 'MySQL availability rule based on mysql_up.',
    },
    {
        'code': 'k8s-abnormal-pods',
        'name': 'K8S Abnormal Pods',
        'source_type': 'k8s',
        'level': 'warning',
        'query_config': {'query': 'count(kube_pod_status_phase{phase=~"Pending|Failed|Unknown"} == 1)', 'value_path': 'value'},
        'condition': {'operator': '>', 'threshold': 0},
        'default_labels': {'integration': 'kubernetes', 'service': 'kubernetes'},
        'annotations': {'summary': 'Kubernetes has abnormal pods'},
        'interval_seconds': 60,
        'duration_seconds': 120,
        'notify_enabled': True,
        'auto_analyze': True,
        'description': 'K8S abnormal pod count rule.',
    },
    {
        'code': 'container-error-spike',
        'name': 'Container ERROR Log Spike',
        'source_type': 'clickhouse',
        'level': 'warning',
        'query_config': {'collection': 'container-logs', 'window_minutes': 5, 'level': ['ERROR', 'FATAL', 'CRITICAL']},
        'condition': {'operator': '>', 'threshold': 50},
        'default_labels': {'integration': 'clickhouse-logs', 'service': 'container-logs'},
        'annotations': {'summary': 'Container ERROR logs spiked in the last 5 minutes'},
        'interval_seconds': 60,
        'duration_seconds': 0,
        'notify_enabled': True,
        'auto_analyze': False,
        'description': 'ClickHouse container log spike rule.',
    },
    {
        'code': 'sla-monthly-risk',
        'name': 'Monthly SLA At Risk',
        'source_type': 'sla',
        'level': 'critical',
        'query_config': {'metric': 'month_sla'},
        'condition': {'operator': '<', 'threshold': 99.96},
        'default_labels': {'integration': 'sla-risk', 'service': 'sla'},
        'annotations': {'summary': 'Monthly SLA is below target'},
        'interval_seconds': 300,
        'duration_seconds': 0,
        'notify_enabled': True,
        'auto_analyze': True,
        'description': 'SLA risk rule based on monthly SLA target.',
    },
]


def ensure_builtin_alert_rule_templates():
    templates = []
    for item in BUILTIN_ALERT_RULE_TEMPLATES:
        template, _ = AlertRuleTemplate.objects.update_or_create(
            code=item['code'],
            defaults={**item, 'is_builtin': True, 'is_enabled': True},
        )
        templates.append(template)
    return templates


def install_rules_from_templates(template_codes):
    ensure_builtin_alert_rule_templates()
    created = []
    skipped = []
    for template in AlertRuleTemplate.objects.filter(code__in=template_codes, is_enabled=True):
        exists = AlertRule.objects.filter(template=template).exists()
        if exists:
            skipped.append(template.code)
            continue
        rule = AlertRule.objects.create(
            template=template,
            name=template.name,
            source_type=template.source_type,
            level=template.level,
            query_config=template.query_config,
            condition=template.condition,
            labels=template.default_labels,
            annotations=template.annotations,
            interval_seconds=template.interval_seconds,
            duration_seconds=template.duration_seconds,
            notify_enabled=template.notify_enabled,
            auto_analyze=template.auto_analyze,
            is_enabled=True,
            description=template.description,
        )
        created.append(rule)
    return created, skipped
```

- [ ] **Step 4: Add install-rules view**

In `backend/ops/observability_views.py`, import:

```python
from .alert_rule_presets import ensure_builtin_alert_rule_templates, install_rules_from_templates
```

Add:

```python
@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.alert.config.manage')])
def install_integration_rules(request, key):
    integration = get_integration(key)
    if not integration:
        return Response({'detail': 'integration not found'}, status=status.HTTP_404_NOT_FOUND)
    requested = request.data.get('template_codes') or integration.template_codes
    requested = [code for code in requested if code in integration.template_codes]
    created, skipped = install_rules_from_templates(requested)
    return Response({
        'integration': key,
        'created_count': len(created),
        'skipped_count': len(skipped),
        'created': [{'id': item.id, 'name': item.name, 'code': item.code} for item in created],
        'skipped': skipped,
    }, status=status.HTTP_201_CREATED)
```

In `observability_integrations`, call `ensure_builtin_alert_rule_templates()` before counting templates.

- [ ] **Step 5: Wire URL**

In `backend/ops/urls.py`, add:

```python
path('observability/integrations/<str:key>/install-rules/', observability_views.install_integration_rules, name='observability-integration-install-rules'),
```

- [ ] **Step 6: Run tests**

Run:

```bash
python manage.py test ops.tests.ObservabilityViewsTests.test_install_integration_rules_creates_rules_from_builtin_templates --verbosity 2
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/ops/alert_rule_presets.py backend/ops/observability_views.py backend/ops/urls.py backend/ops/tests.py
git commit -m "feat: seed observability alert rule templates"
```

---

### Task 3: JSON-Dashboard-Only Backend Behavior

**Files:**
- Modify: `backend/ops/dashboard_presets.py`
- Modify: `backend/ops/observability_views.py`
- Modify: `backend/ops/urls.py`
- Test: `backend/ops/tests.py`

- [ ] **Step 1: Write failing dashboard install and summary tests**

Add:

```python
def test_integration_dashboard_install_enables_builtin_json_dashboard(self):
    response = self.client.post('/api/observability/integrations/redis/install-dashboards/', {}, format='json')

    self.assertEqual(response.status_code, 201)
    payload = response.json()
    self.assertEqual(payload['integration'], 'redis')
    self.assertGreaterEqual(payload['enabled_count'], 1)
    self.assertTrue(ObservabilityDashboard.objects.filter(title='Redis Overview', is_builtin=True, is_enabled=True).exists())


def test_observability_overview_dashboard_summary_uses_json_definitions(self):
    response = self.client.get('/api/observability/overview/')

    self.assertEqual(response.status_code, 200)
    dashboards = response.json()['modules']['dashboards']
    self.assertEqual(dashboards['source'], 'json')
    self.assertIn('Redis Overview', [item['title'] for item in dashboards['dashboards']])


def test_old_native_dashboard_query_endpoint_is_removed(self):
    response = self.client.post('/api/observability/dashboards/query/', {'dashboard': 'kubernetes'}, format='json')

    self.assertEqual(response.status_code, 404)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python manage.py test ops.tests.ObservabilityViewsTests.test_integration_dashboard_install_enables_builtin_json_dashboard ops.tests.ObservabilityViewsTests.test_observability_overview_dashboard_summary_uses_json_definitions ops.tests.ObservabilityViewsTests.test_old_native_dashboard_query_endpoint_is_removed --verbosity 2
```

Expected: FAIL for missing install endpoint, non-json summary, or existing old native dashboard endpoint.

- [ ] **Step 3: Expand dashboard presets**

In `backend/ops/dashboard_presets.py`, add Redis, MySQL, Kafka, and PostgreSQL definitions to `BUILTIN_DASHBOARDS`. Use the existing panel schema:

```python
{
    'title': 'Redis Overview',
    'description': 'Redis availability, clients, memory, and command throughput.',
    'tags': ['redis', 'prometheus', 'middleware'],
    'panels': [
        {'key': 'redis-up', 'title': 'Redis Up', 'chart_type': 'stat', 'datasource_type': 'prometheus', 'targets': [{'query': 'min(redis_up)'}], 'options': {'unit': ''}, 'sort_order': 1},
        {'key': 'redis-clients', 'title': 'Connected Clients', 'chart_type': 'stat', 'datasource_type': 'prometheus', 'targets': [{'query': 'sum(redis_connected_clients)'}], 'options': {'unit': ''}, 'sort_order': 2},
        {'key': 'redis-memory', 'title': 'Memory Usage', 'chart_type': 'timeseries', 'datasource_type': 'prometheus', 'targets': [{'query': 'redis_memory_used_bytes', 'label': 'instance'}], 'options': {'unit': 'bytes'}, 'sort_order': 3},
    ],
}
```

Add similar minimal three-panel definitions:

```python
{
    'title': 'MySQL Overview',
    'description': 'MySQL availability, connections, and running threads.',
    'tags': ['mysql', 'prometheus', 'middleware'],
    'panels': [
        {'key': 'mysql-up', 'title': 'MySQL Up', 'chart_type': 'stat', 'datasource_type': 'prometheus', 'targets': [{'query': 'min(mysql_up)'}], 'options': {'unit': ''}, 'sort_order': 1},
        {'key': 'mysql-connections', 'title': 'Connections', 'chart_type': 'stat', 'datasource_type': 'prometheus', 'targets': [{'query': 'sum(mysql_global_status_threads_connected)'}], 'options': {'unit': ''}, 'sort_order': 2},
        {'key': 'mysql-running-threads', 'title': 'Running Threads', 'chart_type': 'timeseries', 'datasource_type': 'prometheus', 'targets': [{'query': 'mysql_global_status_threads_running', 'label': 'instance'}], 'options': {'unit': ''}, 'sort_order': 3},
    ],
}
```

```python
{
    'title': 'Kafka Overview',
    'description': 'Kafka broker and consumer lag overview.',
    'tags': ['kafka', 'prometheus', 'middleware'],
    'panels': [
        {'key': 'kafka-brokers', 'title': 'Brokers', 'chart_type': 'stat', 'datasource_type': 'prometheus', 'targets': [{'query': 'sum(kafka_brokers)'}], 'options': {'unit': ''}, 'sort_order': 1},
        {'key': 'kafka-consumer-lag', 'title': 'Consumer Lag', 'chart_type': 'timeseries', 'datasource_type': 'prometheus', 'targets': [{'query': 'kafka_consumergroup_lag', 'label': 'consumergroup'}], 'options': {'unit': ''}, 'sort_order': 2},
        {'key': 'kafka-offline-partitions', 'title': 'Offline Partitions', 'chart_type': 'stat', 'datasource_type': 'prometheus', 'targets': [{'query': 'sum(kafka_controller_kafkacontroller_offlinepartitionscount)'}], 'options': {'unit': ''}, 'sort_order': 3},
    ],
}
```

```python
{
    'title': 'PostgreSQL Overview',
    'description': 'PostgreSQL availability and connections.',
    'tags': ['postgresql', 'prometheus', 'middleware'],
    'panels': [
        {'key': 'postgresql-up', 'title': 'PostgreSQL Up', 'chart_type': 'stat', 'datasource_type': 'prometheus', 'targets': [{'query': 'min(pg_up)'}], 'options': {'unit': ''}, 'sort_order': 1},
        {'key': 'postgresql-connections', 'title': 'Connections', 'chart_type': 'stat', 'datasource_type': 'prometheus', 'targets': [{'query': 'sum(pg_stat_activity_count)'}], 'options': {'unit': ''}, 'sort_order': 2},
        {'key': 'postgresql-deadlocks', 'title': 'Deadlocks', 'chart_type': 'timeseries', 'datasource_type': 'prometheus', 'targets': [{'query': 'increase(pg_stat_database_deadlocks[5m])', 'label': 'datname'}], 'options': {'unit': ''}, 'sort_order': 3},
    ],
}
```

- [ ] **Step 4: Update dashboard summary and remove old hard-coded query**

Replace `_native_dashboard_summary()` in `backend/ops/observability_views.py` with a JSON-definition summary, then remove these old hard-coded dashboard objects and functions from the module:

- `NATIVE_DASHBOARD_CATALOG`
- `NATIVE_PROMETHEUS_DASHBOARDS`
- `NATIVE_LOG_DASHBOARDS`
- `NATIVE_DASHBOARD_ALIASES`
- `_native_prometheus_dashboard`
- `_native_log_dashboard`
- `native_dashboard`

Keep shared helpers only if dashboard definition query still uses them.

```python
def _native_dashboard_summary():
    ensure_builtin_dashboards()
    dashboards = ObservabilityDashboard.objects.filter(is_enabled=True).prefetch_related('panels').order_by('-is_builtin', 'title')
    items = [
        {
            'id': item.id,
            'title': item.title,
            'description': item.description,
            'tags': item.tags,
            'is_builtin': item.is_builtin,
            'panel_count': item.panels.count(),
        }
        for item in dashboards
    ]
    return {
        'configured': True,
        'source': 'json',
        'dashboard_count': len(items),
        'types': ['json'],
        'dashboards': items,
    }
```

- [ ] **Step 5: Add install-dashboard view**

In `backend/ops/observability_views.py`, add:

```python
@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.monitor.dashboard.manage')])
def install_integration_dashboards(request, key):
    integration = get_integration(key)
    if not integration:
        return Response({'detail': 'integration not found'}, status=status.HTTP_404_NOT_FOUND)
    ensure_builtin_dashboards()
    dashboards = ObservabilityDashboard.objects.filter(title__in=integration.dashboard_titles)
    dashboards.update(is_enabled=True, is_builtin=True)
    return Response({
        'integration': key,
        'enabled_count': dashboards.count(),
        'dashboards': [{'id': item.id, 'title': item.title} for item in dashboards],
    }, status=status.HTTP_201_CREATED)
```

Add URL:

```python
path('observability/integrations/<str:key>/install-dashboards/', observability_views.install_integration_dashboards, name='observability-integration-install-dashboards'),
```

Remove this old URL from `backend/ops/urls.py`:

```python
path('observability/dashboards/query/', observability_views.native_dashboard, name='observability-dashboards-query'),
```

- [ ] **Step 6: Run tests**

Run:

```bash
python manage.py test ops.tests.ObservabilityViewsTests.test_integration_dashboard_install_enables_builtin_json_dashboard ops.tests.ObservabilityViewsTests.test_observability_overview_dashboard_summary_uses_json_definitions ops.tests.ObservabilityViewsTests.test_old_native_dashboard_query_endpoint_is_removed --verbosity 2
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/ops/dashboard_presets.py backend/ops/observability_views.py backend/ops/urls.py backend/ops/tests.py
git commit -m "feat: use json dashboard definitions for observability"
```

---

### Task 4: Draft Alert Rule Dry Run

**Files:**
- Modify: `backend/ops/views.py`
- Test: `backend/ops/tests.py`
- Modify: `frontend/src/api/modules/ops.js`

- [ ] **Step 1: Write failing backend dry-run test**

Add:

```python
@patch('ops.alert_engine.evaluator.evaluate_rule')
def test_alert_rule_dry_run_draft_creates_unsaved_preview_rule(self, mock_evaluate):
    mock_evaluate.return_value = {'success': True, 'matched_count': 1, 'would_fire_count': 1, 'dry_run': True}

    response = self.client.post(
        '/api/alert-rules/dry-run-draft/',
        {
            'name': 'Draft Redis Down',
            'source_type': 'prometheus',
            'level': 'critical',
            'query_config': {'query': 'redis_up == 0'},
            'condition': {'operator': '>', 'threshold': 0},
            'labels': {'integration': 'redis'},
            'annotations': {},
            'interval_seconds': 60,
            'duration_seconds': 60,
            'notify_enabled': True,
            'auto_analyze': False,
            'is_enabled': False,
        },
        format='json',
    )

    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json()['would_fire_count'], 1)
    self.assertFalse(AlertRule.objects.filter(name='Draft Redis Down').exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python manage.py test ops.tests.ObservabilityViewsTests.test_alert_rule_dry_run_draft_creates_unsaved_preview_rule --verbosity 2
```

Expected: FAIL with 404.

- [ ] **Step 3: Implement dry-run draft action**

In `backend/ops/views.py`, add to `AlertRuleViewSet.rbac_permissions`:

```python
'dry_run_draft': ['ops.alert.config.manage'],
```

Add action:

```python
@action(detail=False, methods=['post'], url_path='dry-run-draft')
def dry_run_draft(self, request):
    serializer = self.get_serializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    rule = AlertRule(**serializer.validated_data)
    rule.id = None
    result = evaluate_rule(rule, dry_run=True, request=request)
    response_status = status.HTTP_200_OK if result.get('success') else status.HTTP_502_BAD_GATEWAY
    return Response(result, status=response_status)
```

- [ ] **Step 4: Add frontend API**

In `frontend/src/api/modules/ops.js`, add:

```javascript
export const dryRunDraftAlertRule = (data = {}) => request.post('/alert-rules/dry-run-draft/', data)
```

- [ ] **Step 5: Run tests**

Run:

```bash
python manage.py test ops.tests.ObservabilityViewsTests.test_alert_rule_dry_run_draft_creates_unsaved_preview_rule --verbosity 2
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/ops/views.py backend/ops/tests.py frontend/src/api/modules/ops.js
git commit -m "feat: add draft alert rule dry run"
```

---

### Task 5: Observability Routes and Menu

**Files:**
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/layout/AppLayout.vue`
- Modify: `frontend/src/components/observability/ObservabilityRouteTabs.vue`
- Modify: `frontend/src/api/modules/ops.js`

- [ ] **Step 1: Add frontend API wrappers**

In `frontend/src/api/modules/ops.js`, add:

```javascript
export const getObservabilityIntegrations = () => request.get('/observability/integrations/')
export const installIntegrationRules = (key, data = {}) => request.post(`/observability/integrations/${key}/install-rules/`, data)
export const installIntegrationDashboards = (key, data = {}) => request.post(`/observability/integrations/${key}/install-dashboards/`, data)
```

Remove the old API wrapper:

```javascript
export const queryMonitoringDashboard = (data, config = {}) => request.post('/observability/dashboards/query/', data, config)
```

- [ ] **Step 2: Change routes**

In `frontend/src/router/index.js`:

```javascript
{
  path: 'alerts',
  redirect: '/observability/alerts',
  meta: { hidden: true, anyPermissions: ['ops.alert.view', 'ops.alert.config.view'] },
},
{
  path: 'observability/integrations',
  name: 'ObservabilityIntegrations',
  component: () => import('@/views/ObservabilityIntegrations.vue'),
  meta: { title: '监控集成', icon: 'Connection', anyPermissions: observabilityOverviewPermissions },
},
{
  path: 'observability/alerts',
  name: 'ObservabilityAlerts',
  component: () => import('@/views/Alerts.vue'),
  meta: { title: '告警中心', icon: 'Bell', anyPermissions: ['ops.alert.view', 'ops.alert.config.view'] },
},
```

Keep `/observability` redirect order:

```javascript
if (authStore.hasAnyPermission(observabilityOverviewPermissions)) return '/observability/overview'
if (authStore.hasAnyPermission(['ops.alert.view', 'ops.alert.config.view'])) return '/observability/alerts'
```

- [ ] **Step 3: Change menu**

In `frontend/src/layout/AppLayout.vue`, update observability children:

```javascript
children: [
  { path: '/observability/overview', title: '平台总览', icon: 'DataLine', anyPermissions: observabilityOverviewPermissions },
  { path: '/observability/integrations', title: '监控集成', icon: 'Connection', anyPermissions: observabilityOverviewPermissions },
  { path: '/observability/alerts', title: '告警中心', icon: 'Bell', anyPermissions: ['ops.alert.view', 'ops.alert.config.view'] },
  { path: '/observability/dashboards', title: '监控看板', icon: 'Histogram', anyPermissions: observabilityBoardPermissions },
  { path: '/observability/metrics', title: '指标查询', icon: 'DataAnalysis', anyPermissions: ['ops.metric.query', 'ops.metric.datasource.view'] },
  { path: '/logs/query', title: '日志查询', icon: 'Search', anyPermissions: ['ops.log.query'] },
  { path: '/observability/datasources', title: '数据源管理', icon: 'DataBoard', anyPermissions: ['ops.metric.datasource.view', 'ops.log.datasource.view'] },
]
```

- [ ] **Step 4: Update route tabs**

In `ObservabilityRouteTabs.vue`, add a default group:

```javascript
const tabGroups = {
  main: [
    { key: 'overview', title: '平台总览', icon: 'DataLine', path: '/observability/overview', anyPermissions: observabilityOverviewPermissions },
    { key: 'integrations', title: '监控集成', icon: 'Connection', path: '/observability/integrations', anyPermissions: observabilityOverviewPermissions },
    { key: 'alerts', title: '告警中心', icon: 'Bell', path: '/observability/alerts', anyPermissions: ['ops.alert.view', 'ops.alert.config.view'] },
    { key: 'dashboards', title: '监控看板', icon: 'Histogram', path: '/observability/dashboards', permission: 'ops.monitor.dashboard.view' },
  ],
}
```

Define `observabilityOverviewPermissions` in the component or import from a shared constant if one exists. Use the same array as router/layout.

- [ ] **Step 5: Run frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/modules/ops.js frontend/src/router/index.js frontend/src/layout/AppLayout.vue frontend/src/components/observability/ObservabilityRouteTabs.vue
git commit -m "feat: add observability routes for integrations and alerts"
```

---

### Task 6: Monitoring Integrations Page

**Files:**
- Create: `frontend/src/views/ObservabilityIntegrations.vue`
- Create: `frontend/src/components/observability/IntegrationCard.vue`

- [ ] **Step 1: Create integration card component**

Create `frontend/src/components/observability/IntegrationCard.vue`:

```vue
<template>
  <article class="integration-card">
    <div class="integration-card__head">
      <span class="integration-card__icon"><el-icon><component :is="item.icon || 'Connection'" /></el-icon></span>
      <div>
        <h3>{{ item.title }}</h3>
        <p>{{ sourceText }}</p>
      </div>
      <el-tag size="small" :type="statusType">{{ statusText }}</el-tag>
    </div>
    <div class="integration-card__metrics">
      <span><strong>{{ item.template_count || 0 }}</strong>规则模板</span>
      <span><strong>{{ item.rule_count || 0 }}</strong>已启用规则</span>
      <span><strong>{{ item.dashboard_count || 0 }}</strong>看板</span>
    </div>
    <div class="integration-card__tags">
      <el-tag v-for="tag in item.tags || []" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
    </div>
    <div class="integration-card__actions">
      <el-button size="small" @click="$emit('guide', item)">接入指引</el-button>
      <el-button size="small" type="primary" @click="$emit('install-rules', item)">导入规则</el-button>
      <el-button size="small" @click="$emit('open-dashboard', item)">打开看板</el-button>
      <el-button size="small" @click="$emit('test-source', item)">检测来源</el-button>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  item: { type: Object, required: true },
})

defineEmits(['guide', 'install-rules', 'open-dashboard', 'test-source'])

const sourceText = computed(() => (props.item.source_types || []).join(' / ') || '内置来源')
const statusText = computed(() => ({
  not_connected: '未接入',
  source_available: '来源可用',
  rules_installed: '规则已安装',
  dashboards_installed: '看板已安装',
}[props.item.status] || '未知')
const statusType = computed(() => ({
  not_connected: 'info',
  source_available: 'success',
  rules_installed: 'warning',
  dashboards_installed: 'primary',
}[props.item.status] || 'info')
</script>

<style scoped>
.integration-card {
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 16px;
  background: var(--el-bg-color);
}
.integration-card__head,
.integration-card__actions,
.integration-card__metrics,
.integration-card__tags {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.integration-card__head {
  justify-content: space-between;
}
.integration-card__head h3 {
  margin: 0;
  font-size: 16px;
}
.integration-card__head p {
  margin: 4px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.integration-card__icon {
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: var(--el-fill-color-light);
}
.integration-card__metrics {
  margin-top: 14px;
  color: var(--el-text-color-regular);
}
.integration-card__metrics strong {
  margin-right: 4px;
}
.integration-card__tags,
.integration-card__actions {
  margin-top: 12px;
}
</style>
```

- [ ] **Step 2: Create integrations page**

Create `frontend/src/views/ObservabilityIntegrations.vue`:

```vue
<template>
  <div class="workbench-page-shell observability-integrations-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Connection /></el-icon></span>
          <h2>监控集成</h2>
          <p class="page-inline-desc">从监控对象出发，安装 Xing-Cloud 内置规则模板与 JSON 看板。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :loading="loading" @click="loadData">刷新</el-button>
      </div>
    </section>

    <ObservabilityRouteTabs group="main" />

    <section class="panel">
      <div class="section-head">
        <h3>集成目录</h3>
        <el-segmented v-model="category" :options="categoryOptions" size="small" />
      </div>
      <div v-loading="loading" class="integration-grid">
        <IntegrationCard
          v-for="item in filteredIntegrations"
          :key="item.key"
          :item="item"
          @guide="openGuide"
          @install-rules="installRules"
          @open-dashboard="openDashboard"
          @test-source="testSource"
        />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection } from '@element-plus/icons-vue'
import ObservabilityRouteTabs from '@/components/observability/ObservabilityRouteTabs.vue'
import IntegrationCard from '@/components/observability/IntegrationCard.vue'
import { getObservabilityIntegrations, installIntegrationRules, installIntegrationDashboards } from '@/api/modules/ops'

const router = useRouter()
const loading = ref(false)
const integrations = ref([])
const category = ref('all')
const categoryOptions = [
  { label: '全部', value: 'all' },
  { label: '中间件', value: 'middleware' },
  { label: '平台', value: 'platform' },
  { label: '日志', value: 'logs' },
  { label: 'SLA', value: 'sla' },
]

const filteredIntegrations = computed(() => (
  category.value === 'all'
    ? integrations.value
    : integrations.value.filter((item) => item.category === category.value)
))

async function loadData() {
  loading.value = true
  try {
    const response = await getObservabilityIntegrations()
    integrations.value = response.integrations || []
  } finally {
    loading.value = false
  }
}

function openGuide(item) {
  ElMessageBox.alert(item.guide_path || '暂无接入指引', `${item.title} 接入指引`, { confirmButtonText: '知道了' })
}

async function installRules(item) {
  const result = await installIntegrationRules(item.key, { template_codes: item.template_codes || [] })
  ElMessage.success(`已导入 ${result.created_count || 0} 条规则，跳过 ${result.skipped_count || 0} 条`)
  await loadData()
}

async function openDashboard(item) {
  await installIntegrationDashboards(item.key)
  router.push({ path: '/observability/dashboards', query: { integration: item.key } })
}

function testSource(item) {
  const target = item.source_types?.includes('clickhouse') ? '/logs/datasources' : '/observability/metrics'
  router.push(target)
}

onMounted(loadData)
</script>

<style scoped>
.integration-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
</style>
```

- [ ] **Step 3: Run frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/ObservabilityIntegrations.vue frontend/src/components/observability/IntegrationCard.vue
git commit -m "feat: add observability integration catalog"
```

---

### Task 7: Dashboard Catalog Replaces Old Dashboard UI

**Files:**
- Modify: `frontend/src/views/NativeMonitoringDashboard.vue`
- Create: `frontend/src/components/observability/DashboardCatalog.vue`
- Create: `frontend/src/components/observability/JsonAssetImportDialog.vue`

- [ ] **Step 1: Create JSON import dialog**

Create `JsonAssetImportDialog.vue`:

```vue
<template>
  <el-dialog v-model="visible" title="导入 JSON 看板" width="680px">
    <el-input v-model="jsonText" type="textarea" :rows="14" placeholder='{"title":"...","panels":[...]}' />
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="submit">导入</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

const visible = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['submit'])
const jsonText = ref('')

function submit() {
  try {
    const payload = JSON.parse(jsonText.value)
    emit('submit', payload)
    jsonText.value = ''
    visible.value = false
  } catch (error) {
    ElMessage.error('JSON 格式不正确')
  }
}
</script>
```

- [ ] **Step 2: Create dashboard catalog**

Create `DashboardCatalog.vue`:

```vue
<template>
  <section class="panel dashboard-catalog">
    <div class="section-head">
      <h3>看板目录</h3>
      <div class="section-actions">
        <el-input v-model="keyword" size="small" clearable placeholder="搜索看板" />
        <el-select v-model="tag" size="small" clearable placeholder="标签">
          <el-option v-for="item in tags" :key="item" :label="item" :value="item" />
        </el-select>
      </div>
    </div>
    <div class="dashboard-catalog__grid">
      <button
        v-for="item in filtered"
        :key="item.id"
        type="button"
        class="dashboard-catalog__card"
        :class="{ active: String(item.id) === String(modelValue) }"
        @click="$emit('update:modelValue', item.id)"
      >
        <strong>{{ item.title }}</strong>
        <span>{{ item.description || 'Xing-Cloud JSON 看板' }}</span>
        <small>{{ (item.tags || []).join(' / ') || '未分类' }} · {{ item.panels?.length || item.panel_count || 0 }} 面板</small>
      </button>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  dashboards: { type: Array, default: () => [] },
  modelValue: { type: [String, Number], default: '' },
})

defineEmits(['update:modelValue'])

const keyword = ref('')
const tag = ref('')
const tags = computed(() => Array.from(new Set(props.dashboards.flatMap((item) => item.tags || []))).sort())
const filtered = computed(() => props.dashboards.filter((item) => {
  const text = `${item.title || ''} ${item.description || ''} ${(item.tags || []).join(' ')}`.toLowerCase()
  const keywordOk = !keyword.value || text.includes(keyword.value.toLowerCase())
  const tagOk = !tag.value || (item.tags || []).includes(tag.value)
  return keywordOk && tagOk
}))
</script>

<style scoped>
.dashboard-catalog__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.dashboard-catalog__card {
  text-align: left;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 14px;
  background: var(--el-bg-color);
  display: grid;
  gap: 6px;
  cursor: pointer;
}
.dashboard-catalog__card.active {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary-light-7);
}
.dashboard-catalog__card span,
.dashboard-catalog__card small {
  color: var(--el-text-color-secondary);
}
</style>
```

- [ ] **Step 3: Replace dashboard page logic**

In `NativeMonitoringDashboard.vue`:

- Remove `dashboardOptions`, `logVariantOptions`, `queryMonitoringDashboard`, `changeDashboard`, and the old dashboard switcher template.
- Keep data source selectors, time range filters, import/export actions, and panel rendering.
- Always query with `queryDashboardDefinition(activeDefinitionId.value, payload)`.
- If no dashboard definition exists, show an empty state with import action.

Use this load function:

```javascript
async function loadDashboard() {
  dashboardError.value = ''
  if (!activeDefinitionId.value) {
    dashboardPayload.value = {}
    return
  }
  loadingDashboard.value = true
  try {
    dashboardPayload.value = await queryDashboardDefinition(activeDefinitionId.value, buildDashboardPayload(), { timeout: 60000 })
  } catch (error) {
    dashboardPayload.value = {}
    dashboardError.value = error.response?.data?.detail || error.message || '看板数据加载失败'
  } finally {
    loadingDashboard.value = false
  }
}
```

Use this payload:

```javascript
function buildDashboardPayload() {
  return {
    start_ms: toTimestampMs(filters.timeRange?.[0]),
    end_ms: toTimestampMs(filters.timeRange?.[1]),
    step: 60,
    metric_datasource_id: filters.metricDatasourceId || undefined,
    log_datasource_id: filters.logDatasourceId || undefined,
    namespace: commaList(filters.namespace),
    node: commaList(filters.node),
    pod_name: commaList(filters.podName),
    log_level: commaList(filters.logLevel),
    domain: commaList(filters.domain),
    server_ip: commaList(filters.serverIp),
    status: commaList(filters.status),
    client_ip: commaList(filters.clientIp),
  }
}
```

- [ ] **Step 4: Run grep check**

Run:

```bash
rg -n "queryMonitoringDashboard|dashboardOptions|logVariantOptions|changeDashboard|observability/dashboards/query" frontend/src/views/NativeMonitoringDashboard.vue frontend/src/api/modules/ops.js backend/ops
```

Expected: no matches. The old hard-coded dashboard query path is removed from frontend and backend.

- [ ] **Step 5: Run frontend build**

```bash
cd frontend
npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/NativeMonitoringDashboard.vue frontend/src/components/observability/DashboardCatalog.vue frontend/src/components/observability/JsonAssetImportDialog.vue
git commit -m "feat: replace monitoring dashboards with json catalog"
```

---

### Task 8: Alert Sources, Rule Wizard, and Template Catalog

**Files:**
- Create: `frontend/src/components/observability/AlertSourceMatrix.vue`
- Create: `frontend/src/components/observability/RuleTemplateCatalog.vue`
- Create: `frontend/src/components/observability/AlertRuleWizard.vue`
- Modify: `frontend/src/views/Alerts.vue`

- [ ] **Step 1: Create alert source matrix**

Create `AlertSourceMatrix.vue`:

```vue
<template>
  <section class="panel alert-source-matrix">
    <div class="section-head">
      <h3>告警来源</h3>
      <el-button size="small" @click="$emit('refresh')">刷新</el-button>
    </div>
    <el-table :data="sources" size="small" stripe>
      <el-table-column prop="title" label="来源" min-width="150" />
      <el-table-column label="类型" width="160">
        <template #default="{ row }">{{ (row.source_types || []).join(' / ') }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="120">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'not_connected' ? 'info' : 'success'">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="template_count" label="模板" width="90" />
      <el-table-column prop="rule_count" label="规则" width="90" />
      <el-table-column label="操作" width="210">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="$emit('create-rule', row)">创建规则</el-button>
          <el-button link size="small" @click="$emit('open-query', row)">打开查询</el-button>
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>

<script setup>
defineProps({
  sources: { type: Array, default: () => [] },
})
defineEmits(['refresh', 'create-rule', 'open-query'])

function statusText(value) {
  return {
    not_connected: '未接入',
    source_available: '来源可用',
    rules_installed: '规则已安装',
    dashboards_installed: '看板已安装',
  }[value] || value || '-'
}
</script>
```

- [ ] **Step 2: Create template catalog**

Create `RuleTemplateCatalog.vue`:

```vue
<template>
  <section class="panel rule-template-catalog">
    <div class="section-head">
      <h3>规则模板目录</h3>
      <div class="section-actions">
        <el-input v-model="keyword" size="small" clearable placeholder="搜索模板" />
        <el-select v-model="sourceType" size="small" clearable placeholder="来源类型">
          <el-option label="Prometheus" value="prometheus" />
          <el-option label="ClickHouse" value="clickhouse" />
          <el-option label="K8S" value="k8s" />
          <el-option label="SLA" value="sla" />
        </el-select>
      </div>
    </div>
    <div class="template-grid">
      <article v-for="item in filtered" :key="item.id" class="template-card">
        <div class="template-card__head">
          <strong>{{ item.name }}</strong>
          <el-tag size="small" :type="levelType(item.level)">{{ item.level }}</el-tag>
        </div>
        <p>{{ item.description || expressionSummary(item) }}</p>
        <small>{{ item.source_type }} · {{ item.interval_seconds }}s · for {{ item.duration_seconds }}s</small>
        <div class="template-card__actions">
          <el-button size="small" type="primary" @click="$emit('import-rule', item)">导入为规则</el-button>
          <el-button size="small" @click="$emit('preview', item)">预览</el-button>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  templates: { type: Array, default: () => [] },
})
defineEmits(['import-rule', 'preview'])

const keyword = ref('')
const sourceType = ref('')
const filtered = computed(() => props.templates.filter((item) => {
  const text = `${item.name || ''} ${item.code || ''} ${item.description || ''}`.toLowerCase()
  const keywordOk = !keyword.value || text.includes(keyword.value.toLowerCase())
  const sourceOk = !sourceType.value || item.source_type === sourceType.value
  return keywordOk && sourceOk
}))

function levelType(level) {
  return { critical: 'danger', warning: 'warning', info: 'info' }[level] || 'info'
}

function expressionSummary(item) {
  return item.query_config?.query || item.query_config?.sql || item.query_config?.collection || '内置规则模板'
}
</script>

<style scoped>
.template-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.template-card {
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 14px;
}
.template-card__head,
.template-card__actions {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}
.template-card p {
  color: var(--el-text-color-regular);
}
.template-card small {
  color: var(--el-text-color-secondary);
}
</style>
```

- [ ] **Step 3: Create rule wizard shell**

Create `AlertRuleWizard.vue`:

```vue
<template>
  <el-dialog v-model="visible" title="创建告警规则" width="860px">
    <el-steps :active="step" finish-status="success" simple>
      <el-step title="对象" />
      <el-step title="模板" />
      <el-step title="触发" />
      <el-step title="响应" />
      <el-step title="试运行" />
    </el-steps>
    <div class="rule-wizard-body">
      <template v-if="step === 0">
        <el-select v-model="form.integration_key" filterable placeholder="选择监控对象">
          <el-option v-for="item in integrations" :key="item.key" :label="item.title" :value="item.key" />
        </el-select>
      </template>
      <template v-else-if="step === 1">
        <RuleTemplateCatalog :templates="matchingTemplates" @import-rule="applyTemplate" @preview="applyTemplate" />
      </template>
      <template v-else-if="step === 2">
        <el-form label-width="120px">
          <el-form-item label="规则名称"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="严重级别">
            <el-select v-model="form.level">
              <el-option label="严重" value="critical" />
              <el-option label="警告" value="warning" />
              <el-option label="信息" value="info" />
            </el-select>
          </el-form-item>
          <el-form-item label="持续时间"><el-input-number v-model="form.duration_seconds" :min="0" /> 秒</el-form-item>
          <el-form-item label="评估间隔"><el-input-number v-model="form.interval_seconds" :min="10" /> 秒</el-form-item>
          <el-form-item label="查询配置"><el-input v-model="form.query_config_text" type="textarea" :rows="4" /></el-form-item>
          <el-form-item label="触发条件"><el-input v-model="form.condition_text" type="textarea" :rows="3" /></el-form-item>
        </el-form>
      </template>
      <template v-else-if="step === 3">
        <el-checkbox v-model="form.notify_enabled">命中后通知</el-checkbox>
        <el-checkbox v-model="form.auto_analyze">命中后 AIOps 研判</el-checkbox>
        <el-input v-model="form.description" type="textarea" :rows="3" placeholder="规则说明" />
      </template>
      <template v-else>
        <el-button type="primary" :loading="dryRunning" @click="dryRun">试运行</el-button>
        <pre v-if="dryRunResult">{{ dryRunResult }}</pre>
      </template>
    </div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button :disabled="step === 0" @click="step -= 1">上一步</el-button>
      <el-button v-if="step < 4" type="primary" @click="step += 1">下一步</el-button>
      <el-button v-else type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import RuleTemplateCatalog from './RuleTemplateCatalog.vue'
import { dryRunDraftAlertRule } from '@/api/modules/ops'

const visible = defineModel({ type: Boolean, default: false })
const props = defineProps({
  integrations: { type: Array, default: () => [] },
  templates: { type: Array, default: () => [] },
})
const emit = defineEmits(['save'])

const step = ref(0)
const dryRunning = ref(false)
const dryRunResult = ref('')
const form = reactive(emptyForm())

const activeIntegration = computed(() => props.integrations.find((item) => item.key === form.integration_key))
const matchingTemplates = computed(() => {
  const codes = activeIntegration.value?.template_codes || []
  return props.templates.filter((item) => codes.includes(item.code))
})

watch(visible, (value) => {
  if (value) Object.assign(form, emptyForm())
  if (value) step.value = 0
})

function emptyForm() {
  return {
    integration_key: '',
    template: null,
    name: '',
    source_type: 'prometheus',
    level: 'warning',
    query_config_text: '{}',
    condition_text: '{}',
    labels: {},
    annotations: {},
    interval_seconds: 60,
    duration_seconds: 0,
    notify_enabled: true,
    auto_analyze: true,
    is_enabled: true,
    description: '',
  }
}

function applyTemplate(template) {
  form.template = template.id
  form.name = template.name
  form.source_type = template.source_type
  form.level = template.level
  form.query_config_text = JSON.stringify(template.query_config || {}, null, 2)
  form.condition_text = JSON.stringify(template.condition || {}, null, 2)
  form.labels = template.default_labels || {}
  form.annotations = template.annotations || {}
  form.interval_seconds = template.interval_seconds || 60
  form.duration_seconds = template.duration_seconds || 0
  form.notify_enabled = Boolean(template.notify_enabled)
  form.auto_analyze = Boolean(template.auto_analyze)
  form.description = template.description || ''
  step.value = 2
}

function payload() {
  return {
    ...form,
    query_config: JSON.parse(form.query_config_text || '{}'),
    condition: JSON.parse(form.condition_text || '{}'),
  }
}

async function dryRun() {
  dryRunning.value = true
  try {
    const result = await dryRunDraftAlertRule(payload())
    dryRunResult.value = JSON.stringify(result, null, 2)
  } finally {
    dryRunning.value = false
  }
}

function save() {
  emit('save', payload())
  visible.value = false
}
</script>
```

- [ ] **Step 4: Integrate into Alerts.vue**

In `Alerts.vue`:

- Import new components and APIs:

```javascript
import AlertSourceMatrix from '@/components/observability/AlertSourceMatrix.vue'
import RuleTemplateCatalog from '@/components/observability/RuleTemplateCatalog.vue'
import AlertRuleWizard from '@/components/observability/AlertRuleWizard.vue'
import { getObservabilityIntegrations } from '@/api/modules/ops'
```

- Add refs:

```javascript
const integrations = ref([])
const ruleWizardVisible = ref(false)
```

- Add loader:

```javascript
async function fetchIntegrations() {
  const response = await getObservabilityIntegrations()
  integrations.value = response.integrations || []
}
```

- Replace "新增规则" action:

```vue
<el-button v-if="canManageConfig" size="small" type="primary" :icon="Plus" @click="ruleWizardVisible = true">新增规则</el-button>
```

- Add source matrix above rules table:

```vue
<AlertSourceMatrix
  :sources="integrations"
  @refresh="fetchIntegrations"
  @create-rule="ruleWizardVisible = true"
  @open-query="openSourceQuery"
/>
```

- Replace template table with:

```vue
<RuleTemplateCatalog
  :templates="alertRuleTemplates"
  @import-rule="openAlertRuleFromTemplate"
  @preview="openAlertRuleTemplate"
/>
```

- Add wizard:

```vue
<AlertRuleWizard
  v-model="ruleWizardVisible"
  :integrations="integrations"
  :templates="alertRuleTemplates"
  @save="saveWizardRule"
/>
```

- Add methods:

```javascript
function openSourceQuery(source) {
  router.push(source.source_types?.includes('clickhouse') ? '/logs/query' : '/observability/metrics')
}

function openAlertRuleFromTemplate(template) {
  openAlertRule()
  ruleDialog.form.template = template.id
  applyTemplateToRule(template.id)
}

async function saveWizardRule(data) {
  await createAlertRule(data)
  ElMessage.success('告警规则已保存')
  await fetchAlertRules()
}
```

Call `fetchIntegrations()` when loading rules/templates.

- [ ] **Step 5: Run build**

```bash
cd frontend
npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/Alerts.vue frontend/src/components/observability/AlertSourceMatrix.vue frontend/src/components/observability/RuleTemplateCatalog.vue frontend/src/components/observability/AlertRuleWizard.vue
git commit -m "feat: redesign alert sources and rule templates"
```

---

### Task 9: Final Verification and Deployment Package

**Files:**
- No source changes unless verification finds a defect.

- [ ] **Step 1: Backend checks**

Run:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test ops.tests aiops.tests --verbosity 1
```

Expected:

- `System check identified no issues`.
- `No changes detected`.
- Tests pass.

- [ ] **Step 2: Frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: PASS.

- [ ] **Step 3: Search for old frontend dashboard path in new page**

Run:

```bash
rg -n "queryMonitoringDashboard|dashboardOptions|logVariantOptions|changeDashboard|/alerts'|path: 'alerts'" frontend/src/views frontend/src/router/index.js frontend/src/layout/AppLayout.vue
```

Expected:

- No matches in `NativeMonitoringDashboard.vue`.
- `/alerts` exists only as a redirect to `/observability/alerts`.

- [ ] **Step 4: Search for old brand terms in changed frontend and docs**

Run:

```bash
rg -n "<legacy-brand-keywords>" frontend/src docs/历史设计/可观测与告警
```

Expected: no matches.

- [ ] **Step 5: Commit verification fixes**

If any verification fix was needed:

```bash
git add <fixed-files>
git commit -m "fix: stabilize observability redesign"
```

If no fix was needed, do not create an empty commit.

- [ ] **Step 6: Prepare deployment**

Build and deploy using the existing deployment flow:

```bash
TAG=a1.10 bash k8s/deploy.sh
```

Expected:

- `xing-cloud-app` uses the new image tag.
- `xing-cloud-scheduler` remains healthy and still runs `run_ops_scheduler`.
