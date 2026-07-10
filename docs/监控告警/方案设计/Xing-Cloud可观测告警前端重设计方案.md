# Xing-Cloud 可观测告警前端重设计方案

## Status

Approved for design by the product owner on 2026-07-10. This document defines the first implementation phase for redesigning observability alert sources, alert rules, rule templates, and monitoring dashboards in Xing-Cloud.

## Background

The current frontend has the technical capability to manage alerts, rules, templates, notification policies, metric sources, log sources, and JSON dashboards. The problem is product discoverability:

- Users do not know where alert sources are configured.
- Alert rules are shown as a table plus JSON-heavy form, which makes it hard to create a rule from a real monitoring object.
- Rule templates are listed as generic records instead of reusable monitoring assets.
- Monitoring dashboards are usable, but the relationship between a monitored component, its collector, its rule templates, and its dashboard is not obvious.

Nightingale solves this with an integration-pack model. A component such as MySQL, Redis, or Kafka contains collector guidance, alert templates, dashboard definitions, icons, and metric documents in one folder. Xing-Cloud should borrow that product path while keeping the existing Prometheus, ClickHouse, SLA, and AIOps architecture.

## Branding Rule

All visible product and UI copy must use `Xing-Cloud`.

Do not introduce alternate product spellings in page titles, headers, empty states, import/export names, dashboard names, template names, or deployment-facing text.

## Goals

1. Make alert sources visible in the frontend.
2. Make alert rule creation follow a guided workflow instead of starting with JSON.
3. Redesign rule templates as a template catalog grouped by monitoring integration.
4. Redesign monitoring dashboards as integration assets with JSON import/export still available.
5. Keep the current platform-native direction: Prometheus metrics, ClickHouse logs, built-in SLA, K8S through Prometheus and ClickHouse.
6. Keep existing alert event, notification, silence, inhibition, aggregation, escalation, and AIOps analysis flows.

## Non-Goals

- Do not add Grafana as a runtime dependency.
- Do not add trace systems.
- Do not add customer inbound alert webhook ingestion.
- Do not add automatic self-healing execution.
- Do not build a drag-and-drop dashboard editor in this phase.
- Do not replace the existing backend alert engine with Nightingale code.

## Nightingale Reference

The design borrows these ideas from Nightingale:

- Integration packs group component assets under one product entry.
- Each integration can contain alert rules, dashboards, collection docs, icons, and metric metadata.
- Alert rule templates are importable assets, not only manually created records.
- Dashboard JSON is a first-class asset and can be imported or exported.
- Users start from the monitored object and then install rules or dashboards.

Reference examples inspected:

- `integrations/MySQL/alerts/mysql_by_exporter.json`
- `integrations/Redis/alerts/redis_by_exporter.json`
- `integrations/Kafka/alerts/kafka_by_exporter.json`
- `integrations/MySQL/dashboards/mysql_by_exporter.json`
- `center/integration/init.go`

## Proposed Information Architecture

The observability module should use this menu structure:

1. Platform Overview: `/observability/overview`
2. Monitoring Integrations: `/observability/integrations`
3. Alert Center: `/observability/alerts`
4. Monitoring Dashboards: `/observability/dashboards`
5. Metric Query: `/observability/metrics`
6. Log Query: `/logs/query`
7. Data Sources: `/observability/datasources`

Compatibility:

- Keep `/alerts` as a redirect to `/observability/alerts`.
- Keep existing backend API paths for alerts and alert rules.
- Keep existing dashboard query APIs.

## Page Design

### 1. Monitoring Integrations

New page: `frontend/src/views/ObservabilityIntegrations.vue`

Purpose:

Users choose what they want to monitor first. The page behaves like a monitoring asset catalog.

Initial integration cards:

- MySQL
- Redis
- PostgreSQL
- Kafka
- Kubernetes
- Linux Server
- ClickHouse Logs
- Ingress Access Logs
- SLA Risk

Each card shows:

- Integration name and icon.
- Source type: Prometheus, ClickHouse, SLA, or mixed.
- Connection state: Not connected, source available, rules installed, dashboards installed.
- Asset counts: alert templates, dashboard definitions, metric checks, guide documents.
- Primary actions: Setup Guide, Import Rules, Open Dashboard, Test Source.

Data source health should come from existing metric and log source APIs. Rule and dashboard installation state can be derived from existing AlertRule, AlertRuleTemplate, and ObservabilityDashboard data.

### 2. Alert Source View

The alert source concept must be visible before users create rules.

Add a section in the Alert Center or Monitoring Integrations page named `Alert Sources`.

Source groups:

- Prometheus Metric Sources: MySQL, Redis, Kafka, Kubernetes, Linux Server.
- ClickHouse Log Sources: Container Logs, K8S Events, Ingress Access Logs.
- Built-in SLA Source: monthly SLA, disaster events, budget remaining.
- Built-in K8S Source: implemented through Prometheus and ClickHouse.

Each source row shows:

- Health status.
- Last check time.
- Last error summary.
- Available rule templates.
- Enabled alert rules.
- Action: Create Rule, Dry Run, Open Query.

### 3. Alert Rule Wizard

Replace the default entry path for creating a rule with a guided wizard. Keep advanced JSON mode inside the same dialog.

Steps:

1. Select monitoring object.
   - MySQL, Redis, Kafka, Kubernetes, Linux Server, Container Logs, K8S Events, Ingress Access Logs, SLA.
2. Select rule template.
   - Show grouped template cards with severity, expression summary, duration, and labels.
3. Configure trigger.
   - Threshold, comparator, duration, evaluation interval, severity, grouping labels.
4. Configure response.
   - Notify, AIOps analysis, notification group, silence/inhibition hint, runbook link.
5. Dry run and save.
   - Execute `POST /api/alert-rules/{id}/evaluate/` for existing rules or a dry-run preview endpoint for draft rules if implemented.
   - Show query result, calculated value, expected state, and generated labels.

Advanced mode:

- Prometheus: edit query config and condition JSON directly.
- ClickHouse: edit collection, time window, level, keyword, group-by, threshold.
- SLA: edit metric name and risk threshold.
- K8S: edit Prometheus or ClickHouse-backed query config.

### 4. Rule Template Catalog

Redesign the current rule template tab from a plain table into a catalog.

Layout:

- Left filter rail: source type, integration, severity, built-in/custom, installed state.
- Main grid: template cards.
- Right preview drawer: expression, default labels, annotations, interval, duration, dry-run support.

Template card fields:

- Name.
- Integration.
- Severity.
- Source type.
- Expression summary.
- Duration and interval.
- Built-in or custom.
- Installed or not installed.

Actions:

- Import as Rule.
- Batch Import.
- Preview.
- Edit custom template.
- Disable built-in template visibility if needed.

Template examples to seed in this phase:

- MySQL: high running threads, high connections, down, slow queries.
- Redis: down, high client usage, high memory usage, evicted keys rising.
- Kafka: consumer lag, broker down, partition offline.
- Kubernetes: abnormal pods, pod restarts, node not ready.
- Linux Server: CPU high, memory high, disk high, node down.
- ClickHouse Logs: ERROR log spike, K8S warning event spike, Ingress 5XX spike.
- SLA: monthly SLA at risk.

### 5. Monitoring Dashboards

Keep the existing JSON dashboard backend and chart renderer. Redesign the frontend as a dashboard asset catalog.

Views:

- Built-in dashboards.
- Integration dashboards.
- Custom dashboards.
- Import and export JSON.

Dashboard list fields:

- Title.
- Integration.
- Source type.
- Tags.
- Built-in or custom.
- Panel count.
- Last updated time.
- Health warning if required data source is missing.

Dashboard viewer:

- Top filter bar: time range, metric source, log source, namespace, instance, service, log collection.
- Integration context: show related rule templates and data source health.
- Panel grid rendered with existing `NativeDashboardChart.vue`.
- JSON import/export remains available.

Initial dashboards:

- MySQL Overview.
- Redis Overview.
- Kafka Overview.
- Kubernetes Cluster Health.
- Linux Server Resources.
- ClickHouse Container Logs.
- ClickHouse K8S Events.
- Ingress Access Logs.
- SLA Risk Cockpit.

## Backend/API Design

Prefer reusing current models and APIs in the first phase.

Existing backend assets:

- `MetricDataSource`.
- `LogDataSource`.
- `AlertRuleTemplate`.
- `AlertRule`.
- `AlertRuleState`.
- `Alert`.
- `ObservabilityDashboard`.
- `ObservabilityDashboardPanel`.
- Alert engine evaluator and scheduler.
- Dashboard definition CRUD, import, export, and query APIs.

New or expanded APIs:

- `GET /api/observability/integrations/`
  - Returns integration cards, source health, template counts, dashboard counts, and installed state.
- `POST /api/observability/integrations/{key}/install-rules/`
  - Creates alert rules from selected templates.
- `POST /api/observability/integrations/{key}/install-dashboards/`
  - Imports or enables built-in dashboard definitions.
- `POST /api/alert-rules/dry-run-draft/`
  - Optional first-phase endpoint if draft dry-run cannot be done through the existing detail endpoint.

Compatibility:

- Keep `GET/POST /api/alert-rules/`.
- Keep `POST /api/alert-rules/{id}/evaluate/`.
- Keep `GET/POST /api/observability/dashboard-definitions/`.
- Keep dashboard definition query/export/import endpoints.

## Data Model Design

First phase can avoid adding database tables if integration metadata is code-defined.

Use a backend registry module such as:

- `backend/ops/observability_integrations.py`

Registry fields:

- `key`
- `title`
- `category`
- `source_types`
- `tags`
- `icon`
- `guide_path`
- `template_codes`
- `dashboard_titles`
- `metric_probe_queries`
- `log_collections`

This keeps rollout low risk while allowing future migration to database-backed integration packs.

## Frontend Components

Suggested components:

- `ObservabilityIntegrations.vue`
- `components/observability/IntegrationCard.vue`
- `components/observability/AlertSourceMatrix.vue`
- `components/observability/AlertRuleWizard.vue`
- `components/observability/RuleTemplateCatalog.vue`
- `components/observability/DashboardCatalog.vue`
- `components/observability/JsonAssetImportDialog.vue`

Existing components to reuse:

- `NativeDashboardChart.vue`
- `MatcherEditor`
- existing alert notification and policy sections
- existing data source selectors

## Data Flow

### Rule Installation

1. User opens Monitoring Integrations.
2. User selects an integration, for example Redis.
3. Frontend fetches source health, templates, and dashboards.
4. User clicks Import Rules.
5. Backend creates AlertRule rows from selected AlertRuleTemplate rows.
6. User opens Alert Center and sees installed rules grouped by integration.
7. Scheduler evaluates rules and writes AlertRuleState and Alert rows.

### Manual Rule Creation

1. User clicks Create Rule.
2. Wizard asks for monitoring object and source.
3. Wizard applies template defaults.
4. User edits threshold, duration, labels, notification, and AIOps options.
5. User runs dry-run.
6. User saves.

### Dashboard Use

1. User opens Monitoring Dashboards.
2. User filters by integration or source type.
3. User selects dashboard.
4. Frontend queries existing dashboard definition endpoint.
5. Panels render through `NativeDashboardChart.vue`.

## Error Handling

Show clear states instead of silently failing:

- No Prometheus source: show `Not connected` and link to metric data source management.
- Prometheus query error: show last error and allow opening metric query page.
- No ClickHouse source: show `Not connected` and link to log source management.
- Missing log collection: show collection name and setup guide.
- Template import conflict: show existing rule and offer skip or create copy.
- Dashboard data source missing: keep dashboard visible but mark panels as unavailable.
- Dry-run failure: show query, source, error message, and suggested next action.

## Permissions

Reuse current RBAC:

- View integrations: any observability view permission.
- Install rules: `ops.alert.config.manage`.
- View alert sources: `ops.alert.config.view` or relevant source view permission.
- Manage dashboards: `ops.monitor.dashboard.manage`.
- View dashboards: `ops.monitor.dashboard.view`.
- View metric sources: `ops.metric.datasource.view`.
- View log sources: `ops.log.datasource.view`.

## Testing Plan

Backend tests:

- Integration registry returns MySQL, Redis, Kafka, Kubernetes, Linux Server, logs, and SLA entries.
- Integration status reflects metric/log data source health.
- Installing templates creates AlertRule records without duplicates.
- Missing Prometheus or ClickHouse source returns actionable status.
- Dashboard install enables or imports expected dashboard definitions.

Frontend tests or build checks:

- `npm run build`.
- Alert Center can open through `/observability/alerts`.
- `/alerts` redirects to `/observability/alerts`.
- Integration catalog renders cards and status.
- Rule wizard can create a Prometheus rule from a template.
- Rule wizard can dry-run or show a controlled dry-run error.
- Dashboard catalog can open built-in and imported dashboards.

Deployment checks:

- `python manage.py check`.
- `python manage.py test ops.tests aiops.tests`.
- Confirm scheduler still runs `run_ops_scheduler`.
- Confirm existing alert event and notification pages still work.

## Rollout Plan

Phase 1:

- Add `/observability/integrations`.
- Add `/observability/alerts` route and redirect `/alerts`.
- Redesign alert rule creation as a wizard.
- Redesign template tab as catalog.
- Redesign dashboard page as catalog plus viewer.
- Seed first middleware and platform templates.

Phase 2:

- Add richer JSON dashboard import mapping from Nightingale-like assets.
- Add dashboard variable templates.
- Add more middleware integrations.
- Add guided exporter deployment snippets.

Phase 3:

- Consider database-backed integration packs if users need to upload custom packs.
- Consider visual dashboard editing.

## Open Decisions

1. Whether draft rule dry-run should use a new endpoint or save a disabled temporary rule first.
2. Whether integration metadata should remain code-defined or become database-backed after phase 1.
3. Whether imported Nightingale dashboard JSON should be converted automatically or manually curated into Xing-Cloud dashboard panel JSON.

Recommended decisions for phase 1:

- Add a draft dry-run endpoint.
- Keep integration metadata code-defined.
- Manually curate built-in dashboard definitions for MySQL, Redis, Kafka, K8S, Linux, logs, and SLA.
