# 阶段 0 详细设计：事件中心（Event Hub）落地

> 状态：已实施（2026-08-06 生产上线，镜像 event-hub-phase0-20260806，提交 c83df11）。
> 范围（已拷问确认）：webhook 链路 + 平台内部事件（部署/巡检/资源发现）；不做前端；不回填历史告警；Event 保留 30 天可配置。
> 对照总体规划：`docs/Alert-Closure-Improvement-Plan.md` 阶段 0。

## 0. 实施记录（与实际代码的差异与决策）

1. **存量调用盘点（评审补充）**：盘点全仓发现 85 处既有 `record_event` 调用（经 `ops/eventwall_stub.py` no-op 占位，语义为旧事件墙）。决策：**按类别启用 39 处、保留 46 处 no-op**。
   - 启用（39）：ops/views.py 19、nginx_views.py 6、log_views.py 3、observability_views.py 2、aiops/services.py 3、rbac/views.py 3、deployer.py 2（重写为新语义）、host_tasks.py 1。
   - 保留 no-op（46）：aiops/views.py 23（知识环境/Runbook/会话审计删除/A2A 内部编排，与告警闭环无关）等遗迹调用。
   - 实现方式：`ops/events.py` 的 `record_event` 双语义——新语义走新模型；旧语义 kwargs（module/category/action/result/actor_*/resource_*/business_line/environment/application/correlation_id/source_type）经适配层映射，`SOURCE_TYPE_MAP` 完成 resource_type→source_type 转换，resource_type='alert' 时绑定 alert FK。`eventwall_stub.py` 保留作 no-op 兜底供 46 处遗迹继续引用。
2. **搜索参数**：设计文档写 `q`，实际 EventViewSet 用 DRF SearchFilter 默认参数 `search`（设计第 5 节与测试按 `search` 实现）。
3. **清理调度**：`run_ops_scheduler_once` 内以全局时间戳 `_LAST_EVENT_CLEANUP_AT` 控制"距上次清理 ≥1 小时"触发一次，结果键 `event_cleanup`；`run_due_event_cleanup` 按剩余限额分批（每批 ≤500）。
4. **webhook 事件**：upsert 循环内 `_record_ingest_event(normalized, alert, kind, severity)` 只写状态变化（alert_active / alert_reactivated / alert_resolved），同状态更新不写，防事件风暴。
5. **验证**：新增 21 个测试（test_events.py），全量回归 366 全绿；生产验收 webhook 真实链路 alert_active(critical)/alert_resolved(info) 落库且 alert_id 正确关联；`/api/events/` 未认证 401。

## 1. 数据模型（新表 ops_event）

```
Event
  id            bigint PK
  source_type   varchar(32)   来源类别: webhook / deployment / inspection / discovery / system
  kind          varchar(64)   事件类型: alert_active / alert_resolved / alert_reactivated /
                               release_success / release_failed / batch_advanced / service_stopped /
                               service_started / service_removed / inspection_completed /
                               inspection_failed / discovery_success / discovery_failed
  severity      varchar(16)   info / warning / error / danger（默认 info）
  title         varchar(255)
  message       text(blank)
  target_type   varchar(64)   k8s_cluster / node / pod / deployment / schedule / source / host ...
  target_resource varchar(255) 目标标识（名称/编码）
  alert         FK(Alert, SET_NULL, null, related_name='events')
  payload       JSON(default=dict)
  occurred_at   datetime(索引, db_index)
  created_at    datetime(auto_now_add)
```

索引：`(occurred_at desc)`、`source_type`、`kind`、`target_resource`。
约束：`kind` 非空；`occurred_at` 默认 `timezone.now()`。

## 2. 写入模块（新增 backend/ops/events.py）

```python
def record_event(source_type, kind, severity='info', title='', message='',
                 target_type='', target_resource='', alert=None, payload=None,
                 occurred_at=None) -> Event | None
```

- 内部 `try/except Exception` 包裹，失败仅 `logger.warning`，**绝不抛出**（降级原则：事件写失败不影响告警/部署主链路）
- payload 统一塞入 `ingest` 元数据（webhook 来源）或业务上下文（部署/巡检/发现）
- 单一写入入口，后续内部系统接入只调这一个函数

## 3. webhook 链路插入点（ops/alert_ingest.py）

`ingest_external_alert_payload` 在 `upsert_alert` 之后（约 461-502 行区域），按状态变迁写事件，**只写状态变化不写每次 occurrence 更新**（防事件风暴）：

| 场景 | kind | severity |
|------|------|----------|
| 新建/重新激活（created 或 reactivated 且 active） | alert_active | 按告警级别映射 |
| 恢复（newly_resolved） | alert_resolved | info |
| 其余 upsert（同状态更新） | 不写 | - |

- `alert=alert` 关联；payload 用归一化后的 labels/annotations 精简摘要
- **跨阶段一致性（评审补充）**：若阶段 1（收敛）同上线，聚合根**创建与 resolve** 各写一条事件、children 归并更新不写（防事件风暴）——与阶段 1 设计第 2 节约定一致
- 兼容性：webhook 响应协议、fingerprint、Waiting 语义**零改动**（门禁：test_alert_ingest / test_unified_alert_sources / test_multi_source_alerts / test_waiting_alert_stability 全绿）

## 4. 平台内部事件接入点清单（已核实代码位置）

| 模块 | 位置 | 事件 |
|------|------|------|
| ops/deployer.py | `deploy_service` 成功收尾（约 362 行 `_mark_current_release` 后） | deployment / release_success，payload 复用 `_deployment_event_metadata`（244 行已存在） |
| ops/deployer.py | `deploy_service` 异常路径 | deployment / release_failed，severity=error，message=异常摘要 |
| ops/deployer.py | `advance_batch`（521 行） | deployment / batch_advanced |
| ops/deployer.py | `stop_service`/`start_service`/`remove_service` 成功处 | deployment / service_stopped / service_started / service_removed |
| ops/inspection_reports.py | `run_due_inspection_reports` 内 execution 后（580-583 行） | inspection / inspection_completed（SUCCESS/PARTIAL）/ inspection_failed，target=schedule |
| resource_center/discovery.py | `run_due_discoveries` 每 run 完成后（448-449 行区域） | discovery / discovery_success / discovery_failed（run.status），target=source 或 k8s_cluster |

部署事件 target_type=deployment、target_resource=release_name；巡检 target_type=schedule；发现 target_type=source。

## 5. API（只读）

```
GET /api/events/            # AlertEventViewSet，只读
  过滤：source_type / kind / severity / target_type / target_resource(icontains)
        / alert_id / occurred_after / occurred_before / q(模糊 title+message)
  分页：page_size 默认 20（沿用 AlertConfigPagination）
  排序：-occurred_at
  权限：登录用户可读（沿用现有认证），无写操作、无 admin 专属
响应字段：id, source_type, kind, severity, title, message, target_type,
         target_resource, alert_id, occurred_at, created_at
```

路由：`router.register(r'events', views.EventViewSet, basename='event')`（ops/urls.py）。

## 6. 保留与清理

- `settings.EVENT_RETENTION_DAYS`，默认 30，环境变量 `EVENT_RETENTION_DAYS` 可覆盖（沿用 `_setting_value` 读取风格）
- 清理函数 `run_due_event_cleanup(limit)`：删除 `occurred_at < now - 30天` 的 Event
- 调度：不占 30s 主循环——在 `run_ops_scheduler_once` 内按"距上次清理 ≥1 小时"触发一次（ops_scheduler.py 记录时间戳），避免每轮扫表

## 7. 测试计划（新增 backend/ops/test_events.py）

1. webhook 落事件：ingest 后 Event 存在且 alert_id 正确；active/resolved/reactivated 各生成对应 kind；同状态 upsert 不生成事件
2. 内部事件：mock 部署成功/失败路径生成事件；inspection run 完成/失败；discovery run 完成/失败
3. API：过滤组合、分页、排序、alert_id 反查；未登录 401
4. 清理：过期事件被删、保留期内不删、limit 生效
5. 降级：record_event 抛异常不影响 ingest 主链路（mock 验证）
6. 回归门禁：test_alert_ingest / test_unified_alert_sources / test_multi_source_alerts / test_waiting_alert_stability / test_alert_ingest 全绿

## 8. 影响范围与回滚

- 新增：ops_event 表迁移、ops/events.py、ops/test_events.py、EventViewSet、urls 注册
- 修改：alert_ingest.py（插入点）、deployer.py、inspection_reports.py、discovery.py、ops_scheduler.py（清理）、settings.py（EVENT_RETENTION_DAYS）
- 不动：webhook 对外协议、Alert 表结构、通知/研判链路
- 回滚：撤销迁移 + 移除插入点即可；Alert 数据不受影响

## 9. 验收标准

1. 外部 webhook 语义与现状逐条一致（测试门禁全绿）
2. 部署成功/失败、批次推进、巡检完成/失败、发现成功/失败均有事件可查
3. /api/events/ 过滤查询可用；告警详情可通过 alert_id 反查事件时间线（API 层）
4. Event 保留 30 天可配置，清理任务验证有效
5. record_event 失败降级，不阻塞告警主链路
