# ClickHouse Log Collections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split ClickHouse log source configuration into one reusable connection with multiple queryable log collections.

**Architecture:** Keep `LogDataSource` as the storage boundary and store ClickHouse collections in `config.collections` to avoid a broad schema migration. Backend catalog actions will list databases/tables/columns and recommend field mappings; log query resolves a collection key into database/table/time/message/level/source/search fields. Frontend data source management edits the connection and nested collections, while the log query page selects a collection instead of raw table metadata.

**Tech Stack:** Django REST Framework, existing `ops.log_views` provider abstraction, Vue 3, Element Plus.

---

### Task 1: Backend Tests

**Files:**
- Modify: `backend/ops/tests.py`

- [ ] Add tests proving ClickHouse datasources can be connection-only, can expose recommended field mappings, and can query a named collection.
- [ ] Run `python backend/manage.py test ops.tests.LogViewsTests --noinput` and verify the new tests fail before implementation.

### Task 2: Backend Implementation

**Files:**
- Modify: `backend/ops/log_views.py`
- Modify: `backend/xing_cloud/settings.py`
- Modify: `backend/ops/migrations/0063_clickhouse_log_datasource.py`

- [ ] Add collection normalization helpers and field recommendation heuristics.
- [ ] Add ClickHouse catalog action `recommend_fields`.
- [ ] Resolve collection config during query and normalize rows with configured message, level, and source fields.
- [ ] Seed the online ClickHouse datasource with `container_logs.logs`, `container_logs.events`, and `nginxlogs.nginx_access` collections.

### Task 3: Frontend Implementation

**Files:**
- Modify: `frontend/src/api/modules/ops.js`
- Modify: `frontend/src/views/LogDataSources.vue`
- Modify: `frontend/src/views/LogsQuery.vue`

- [ ] Change the ClickHouse datasource form to connection-only plus a collections editor.
- [ ] Add database/table/field catalog loading and an AI recommendation button.
- [ ] Change the log query page to select collections and pass `collection` to the backend.

### Task 4: Verification and Deployment

**Files:**
- Deploy changed files to `/xing/devops`

- [ ] Run `python backend/manage.py check`.
- [ ] Run `python backend/manage.py test ops.tests.LogViewsTests --noinput`.
- [ ] Run `npm --prefix frontend run build`.
- [ ] Upload changed files only, run `bash k8s/deploy.sh`, restart deployments if the reused image tag requires it, and verify pods plus ClickHouse query.
