# 阶段 2 详细设计：值班表 + 告警转工单

> 状态：已实施（commit 待定）。实现偏差见第 9 节；编码期间拷问确认见第 10 节。
> 范围（已拷问确认）：值班表（简单班次）+ 告警转工单（仅手动）。**FTA 自动动作已从阶段 2 剔除**（本轮不设计，后续单独评估）；前端后置（API 暴露字段）。
> 对照总体规划：`docs/Alert-Closure-Improvement-Plan.md` 阶段 2（范围已同步更新）。

## 0. 现状核实（代码事实）

| 事实 | 位置 |
|------|------|
| 工单模型已具备：TYPE_INCIDENT（故障处理）、priority、status（pending/approved/processing/done/rejected）、owner、applicant、approval_flow FK——转单复用现有模型，**不改工单表结构** | ops/models.py:2119 TransactionTicket |
| 工单 API 已存在：TransactionTicketViewSet + `/api/transaction-tickets/` | ops/views.py:2298、ops/urls.py:21 |
| 升级链路：`apply_escalation_policy` → `_recipient_contacts(policy, route, alert, level)` 解析接收人——**值班表注入点** | ops/alerting.py:1594 / 1642 |
| 通知策略 AlertNotificationPolicy / 路由 AlertNotificationRoute（after_minutes 未认领升级）已存在 | ops/alerting.py |
| 接收组 AlertRecipientGroup：recipients（联系人）+ users（平台用户）+ is_enabled | ops/models.py:1318 |
| 值班/排班模型：不存在 | - |

## 1. 模型改动

### OnCallSchedule（新表，值班班次）

```
name             varchar(128) 班次名称
recipient_group  FK(AlertRecipientGroup, PROTECT, related_name='oncall_schedules')
weekday_bits     PositiveIntegerField default=127   星期位图：1=周一，2=周二，4=周三…127=全周
start_time       TimeField 默认 00:00
end_time         TimeField 默认 23:59:59   end < start 表示跨天（隔夜班）
is_enabled       BooleanField default=True
created_at / updated_at
```

- 简单班次表：按"星期 + 每日时间段"重复，不搞复杂轮转/节假日（已确认复杂度）
- 解析函数 `current_oncall_group(now=None) -> AlertRecipientGroup | None`：
  - 遍历启用的班次：`weekday_bits & (1 << (weekday-1))` 命中当日，且 `now.time()` 落在班次区间（跨天班拆分处理）
  - 命中返回该班次接收组；无命中返回 None
- 同一时刻多个班次命中 → 取 `id` 最小者（避免歧义，文档注明）

### AlertTicket（新表，告警-工单关联）

```
alert    FK(Alert, CASCADE, related_name='tickets')
ticket   FK(TransactionTicket, CASCADE, related_name='alert_links')
created_by  FK(AUTH_USER, SET_NULL, null)  创建人
created_at  auto_now_add
UniqueConstraint(alert, ticket)
```

- 工单表零改动；关联表实现双向查询

## 2. 值班表接入升级链路（ops/alerting.py）

- AlertNotificationPolicy 新增可空字段 `oncall_schedule = FK(OnCallSchedule, SET_NULL, null, related_name='policies')`
- **注入点（评审修正）**：`_recipient_contacts` 有**两个调用点**——fire/resolved/analysis 首次通知（alerting.py:1499）与升级（alerting.py:1642）。值班只作用于**升级路径**，因此不在 `_recipient_contacts` 内部注入，而是在 `apply_escalation_policy` 的升级调用处（1642）单独解析：
  - `policy.oncall_schedule` 已配置且 `current_oncall_group()` 命中当班 → 升级接收人 = 当班接收组（组内 recipients + users 合并，与现有 recipient_group 目标解析一致），替换本次升级的 `_recipient_contacts` 结果
  - 未命中（当前无当班）或未配置 → 走原 `_recipient_contacts` 逻辑
- fire/resolved 首次通知（1499 调用点）**不受值班影响**（与蓝鲸一致：值班只决定"无人处理的升级通知给谁"）
- 班次判定时区：使用 `timezone.localtime(now)`（与 `_policy_is_muted` 的时区惯例一致，alerting.py:1609）
- 未配置 `oncall_schedule` 的策略行为零变化（回归门禁）

## 3. 告警转工单（仅手动）

### POST /api/alerts/{id}/create-ticket/
- 入参（全部可选，有默认）：
  - `title`（默认取告警标题）
  - `priority`（默认按告警级别映射：critical→high、warning→medium、info→low）
  - `owner`（可选；不传默认取当班班次所属组名 `group.name`，无值班则空——不解析到个人，避免多接收人歧义）
  - `description`（默认告警摘要：标题+资源+级别+时间+labels 精简）
- 行为：
  - 创建 TransactionTicket（ticket_type=TYPE_INCIDENT、applicant=当前用户、status=pending）+ AlertTicket 关联
  - **幂等**：该告警已存在未终结（status in pending/approved/processing）的 incident 关联工单 → 直接返回已有工单（不重复创建）
- 权限：登录用户（RBAC，需告警可读权限）；工单审批沿用现有 TransactionTicket 审批流（approval_status 已有）

### GET /api/alerts/{id}/tickets/
返回该告警关联工单摘要（id/title/priority/status/created_at/owner）

### TransactionTicketSerializer 补充
响应增加 `alerts` 摘要列表（id/title/level）——工单详情反查关联告警

## 4. API 汇总

| 端点 | 说明 |
|------|------|
| `/api/oncall-schedules/` CRUD | 班次管理（RBAC） |
| `GET /api/oncall-schedules/current/` | 当前当班（schedule + group + recipients 摘要），前端值班展示 |
| `POST /api/alerts/{id}/create-ticket/` | 转工单（手动，幂等） |
| `GET /api/alerts/{id}/tickets/` | 告警关联工单 |
| 工单详情（现有） | 响应补 `alerts` 关联摘要 |

## 5. 测试计划（新增 backend/ops/test_oncall_ticket.py）

1. **值班解析**：工作日命中/未命中；weekday_bits 过滤；隔夜班（end<start）跨天命中；多班次取 id 最小；无班次返回 None
2. **升级链路**：policy 配置 oncall 且当班命中 → 升级通知接收人 = 当班组（mock send_alert_notification 验证）；**fire/resolved 首次通知接收人不变**（验证 1499 路径不受影响）；无当班回退原接收人；未配置 oncall 行为与现状一致
3. **转单**：创建成功（类型 incident、状态 pending、申请人为当前用户）；owner 默认 = 当班组名；幂等（重复调用返回已有工单不新建）；未登录 401；无权限 403
4. **关联查询**：alerts/{id}/tickets/ 双向正确；工单详情带 alerts 摘要
5. **回归门禁**：test_alert_analysis（escalation 相关）、test_multi_source_alerts、通知批次既有测试全绿

## 6. 影响范围与回滚

- 新增：ops_oncallschedule、ops_alertticket 两个迁移；OnCallScheduleViewSet；告警 create-ticket/tickets 端点；serializer 字段
- 修改：alerting.py `_recipient_contacts`（值班注入，默认路径不变）、AlertNotificationPolicy（加 oncall_schedule 可空 FK）
- 不动：Alert 表、TransactionTicket 表、审批流、通知渠道
- 回滚：撤销迁移；未配置 oncall_schedule 时升级行为零变化（**功能开关保证可逆**）

## 7. 验收标准

1. 班次可配置（组+星期+起止时间，支持隔夜班）；未认领升级通知发给当班人；无当班时回退原接收人
2. 告警详情一键转工单（incident），重复转单幂等；告警↔工单双向可查
3. 未配置值班/未启用时，升级与通知行为与现状完全一致（回归门禁全绿）
4. API 齐全、自动化测试全绿

## 8. 规划文档范围更新

- 总体规划阶段 2 范围调整为：值班表 + 告警转工单
- **FTA 自动动作（规则级自动处置+审批门禁）移出阶段 2**，后续单独阶段再评估（涉及执行器与安全，独立评审）

## 9. 实现偏差记录

1. **升级接收人改为"追加合并"而非"替换"**：当策略配置 `oncall_schedule` 且当班命中时，当班组联系人并入原升级接收人（合并去重），而非替换原接收人；未命中当班或无配置时走原逻辑。理由：避免无人处理的告警因替换丢失原有通知对象，兜底更稳。
2. **OnCallSchedule 默认时间用模块级函数**（`default_oncall_start_time/end_time`）：lambda 默认值无法被 Django 迁移序列化。
3. **create_ticket 端点需显式 `url_path='create-ticket'`**：DRF 3.17 中 `@action` 的 `url_path` 默认保留方法名下划线（`create_ticket`），与项目既有惯例（`rematch-resource`、`log-evidence` 显式传参）一致。
4. **Alert 级别映射用字符串字面量**：Alert 模型只有 `LEVEL_CHOICES`，无 `LEVEL_*` 常量。
5. **默认 owner 取当班组名**（`schedule.recipient_group.name`）而非接收人个人——避免多接收人歧义，与设计第 3 节一致。
6. 通知注入点在 `send_alert_notification` 升级调用处（`apply_escalation_policy` 内），fire/resolved 首次通知不受影响（与设计第 2 节一致）。

## 10. 编码期间拷问确认

| 问题 | 结论 |
|------|------|
| 转单触发方式 | 仅手动（不做自动转单） |
| 升级接收人策略 | **追加合并**（当班组并入原接收人，偏离设计"替换"，见第 9 节） |
| 工单审批 | 沿用现有 TransactionTicket 审批流 |
| 部署节奏 | 完成后即上线 |
| 前端范围 | 纯 API（前端后置） |

## 11. 验收记录

- 自动化：`ops.test_oncall_ticket` 19 测试全绿；相关回归（events/transaction_tickets/alert_ingest/alert_analysis/unified_alert_sources）112 测试全绿；全量 407 测试 1 失败为并行基础设施抖动（Redis/worker 超时），单独复跑通过。
- 生产验收（镜像 `oncall-ticket-20260806`，迁移 0109 已自动应用）：
  1. 值班解析：全周班命中；隔夜班 02:00 命中（停用全天班后仅夜班命中）
  2. 升级合并：策略配置 `oncall_schedule` 且当班命中 → 当班组联系人并入升级接收人（`{'email': ['a@x.com']}` 合并）
  3. 转工单：POST `/api/alerts/{id}/create-ticket/` → 200，ticket_type=incident、priority=critical→high、owner=当班组名、applicant=admin
  4. 幂等：重复 POST → `created=False` 返回已有工单
  5. 双向查询：`GET /api/alerts/{id}/tickets/` 返回关联工单；工单详情 `alerts` 摘要正确
  6. `GET /api/oncall-schedules/` CRUD 与 `GET /api/oncall-schedules/current/` 正常
  7. 验收数据已清理（schedules/policies/sources/tickets/alerts 均 0 残留）
