# 阶段 1 详细设计：告警收敛 + 拓扑抑制

> 状态：已实施（2026-08-06 生产上线，镜像 convergence-phase1-fix-20260806）。
> 范围（已拷问确认）：收敛 + 拓扑抑制一起设计；收敛实现为"数据层聚合为一条告警"；抑制实现为"标记 suppressed 不发通知"；前端后置（仅 API 暴露字段）。
> 对照总体规划：`docs/Alert-Closure-Improvement-Plan.md` 阶段 1。

## 0. 实施记录（2026-08-06）

### 与设计的偏差（均已确认）

| 设计 | 实际实现 | 原因 |
|------|----------|------|
| 外部 webhook 告警不收敛 | **外部告警也支持收敛**（拷问确认）：AlertSource 新增 `converge_enabled` / `converge_group_fields` / `converge_window_minutes`，ingest 走与规则侧相同的收敛逻辑 | 用户拷问答复"也支持收敛" |
| `group_key`（聚合键） | 收敛键改用新字段 **`converge_key`**（varchar 128）；现有 `Alert.group_key` 已被通知分组占用（max_length 256，通知聚合用），不可复用 | 字段语义冲突 |
| Alert 新增 `suppressed` Boolean | **复用现有 `is_suppressed` / `suppressed_by`**（静默/静音机制已使用），仅新增 `suppressed_reason`；拓扑抑制置 `suppressed_by='topology'` | 避免双抑制标志 |
| `group_fields` 存在即收敛 | 新增显式开关 **`converge_enabled`（默认 False）** | 保证"未开启收敛/抑制时零行为变化"（验收标准 4） |
| 恢复：实例不再命中 → 从 children 移除 | 聚合根以 `last_seen` 周期复查 + 实例级恢复：子实例恢复时 `refresh_group_root_status` 复查根；根自身恢复与子实例恢复以 payload `instance_resolved` 标记区分，避免"子实例消失导致根提前 resolve" | 评审补充的"根生命周期=最后一个 active 子实例消失"语义 |
| 同 fingerprint 去重 | 同 fingerprint 重复命中不累积；聚合根自身重复命中时回退 upsert 自增的 occurrence_count | 保证 occurrence_count=独立实例数 |

### 交付文件

- 新增：`ops/alert_convergence.py`（convergence_group_key / find_window_group_root / promote_or_attach / refresh_group_root_status / converge_resolved_alert）、迁移 `0107_alert_converge_key_alert_group_parent_and_more.py`、`0108_alert_suppressed_reason.py`、`ops/test_convergence_suppression.py`（22 个测试）
- 修改：`ops/models.py`（AlertRule/AlertSource/Alert 字段）、`ops/alert_engine/pipeline.py`（规则侧收敛+抑制）、`ops/alert_ingest.py`（外部告警收敛+抑制）、`ops/alerting.py`（通知批次过滤拓扑抑制）、`resource_center/alert_matching.py`（ancestor/descendant_resource_ids 抽取 + check/apply/release_topology_suppression）、`ops/serializers.py`（children_count）、`ops/views.py`（is_group_root/converge_key 过滤 + children action）

### 测试与回归

- 新增 22 个收敛/抑制测试全绿（收敛基础/恢复/拓扑抑制/外部收敛/辅助函数）
- 全量回归 **388 OK**（366 基线 + 22 新增）；未开启开关时零行为变化

### 生产验收（2026-08-06）

1. 迁移 0107/0108 随部署自动应用，字段齐全（converge_key / suppressed_reason / converge_enabled / suppress_by_topology 均确认）
2. 收敛 E2E：同一规则 2 实例 → 1 聚合根（occ=2）+ 1 child，converge_key=`r2:alertname=-`（group_fields=[] 按 alertname 收敛）
3. 收敛恢复：调度器真实评估（无数据）将聚合根置 resolved，恢复链路真实生效
4. 拓扑抑制 E2E：cluster 告警 active 后 node 子告警 `suppressed=True`、`suppressed_by='topology'`、reason=`父资源 10.0.0.1 存在 active 告警`，并作为 child 挂入聚合根
5. 验收数据已清理；规则 2（linux-high-cpu）保留收敛试点（converge_enabled=True, group_fields=[]）
6. 生产备份：`backup_before_convergence_phase1.sql`（99 表）

### 顺手修复的生产事故

- **调度器持续崩溃**（Phase 0 遗留）：`run_due_discoveries` 里 `_record_discovery_event` 引用不存在的 `DiscoverySource.provider` 属性 → 每次调度循环异常。已改 `source_type` 并同步修测试，commit `474d0ca`。

### 遗留项

- `suppressed_by='topology'`（无冒号）与 `alerting.py` 通知批次过滤的 `startswith('topology:')` 前缀判断不一致——功能无影响（通知层另有 `is_suppressed` 拦截），建议后续统一前缀
- `children_count` 在告警列表页为每行一次子查询（与现有 claim 系列模式一致），数据量大时需优化
- 前端尚未消费收敛/抑制字段（按设计后置）

## 0A. 现状核实（代码事实）

| 事实 | 位置 |
|------|------|
| AlertRule 已有 `group_window`（聚合窗口分钟，默认 5）、`repeat_interval`（默认 30）字段，但**未在评估/通知逻辑中使用**，仅模板字段复制流转 | ops/models.py:1127-1128；ops/alert_rule_presets.py:411/476-477 |
| Alert 已有 `matched_resource` / `resource_match_status` / `resource_match_reason`（告警资源匹配） | ops/models.py（迁移 0102）；ops/resource_center/alert_matching.py:129 |
| 祖先资源遍历逻辑已存在（contains 反向 + belongs_to/runs_on/deployed_on 正向，3 层）——拓扑抑制直接复用 | resource_center/alert_matching.py:142-170 `resource_contact_recipients` |
| 通知入口：`dispatch_alert_batch_notifications` / `apply_escalation_policy` | ops/alerting.py:1541 / 1594 |
| 静默模型 AlertSilence 已存在 | ops/models.py:1185 |

依赖修正：**阶段 1 不依赖阶段 0（事件中心）**——收敛/抑制基于 Alert 自身记录即可落地；阶段 0 仅作为后续复盘时间线。两个阶段可独立开工、独立上线。

## 1. 模型改动

### AlertRule 新增字段（迁移 1）

```
group_fields          JSONField  default=['source_type','environment','service','cluster','namespace','resource']
                      聚合分组键（对齐 alerting.py DEFAULT_GROUP_BY 默认值）
suppress_by_topology  BooleanField default=False   拓扑抑制开关（默认关闭，按规则显式开启）
suppress_ancestor_hops PositiveIntegerField default=3  向上遍历祖先层数
```

- 复用现有 `group_window`（聚合窗口分钟）、`repeat_interval`（重复通知间隔）字段，不新增
- 规则配置变更（如 group_fields 修改）只影响之后的新评估

### Alert 新增字段（迁移 2）

```
group_key        varchar(128) blank 聚合键；空 = 独立告警（未参与收敛或未命中收敛窗口）
group_parent     FK(Alert, SET_NULL, null, related_name='group_children')  聚合父告警
is_group_root    Boolean default=False   是否聚合根（父告警）
suppressed       Boolean default=False   是否被拓扑抑制
suppressed_reason varchar(255) blank     抑制原因（如"父资源 X 存在 active 告警"）
```

- 聚合根本身也有完整告警字段（title/level/labels/evidence），children 通过 `group_children` 展开
- 不做历史回填，存量 Alert 按默认值（独立、未抑制）

## 2. 收敛流程（评估器改造 ops/alert_engine/pipeline.py）

仅作用于**平台规则评估**（Prometheus/ClickHouse 规则）；外部 webhook 告警无规则配置，保持现状不收敛。

```
命中序列 → 按 rule.group_fields 计算 group_key（labels 取值，缺失字段为空串）
         → 查窗口内（created_at >= now - group_window 分钟）同 group_key 的 active 聚合根
           ├─ 存在 → 归并：occurrence_count += 1
           │        children 追加本次实例（同 fingerprint 去重，更新 last_seen）
           │        刷新聚合根 updated_at，不新建、不重复通知
           └─ 不存在 → 新建聚合根告警（is_group_root=True, group_key=...）
                       首个实例即根自身，不发重复通知（按现有通知批次逻辑）
```

恢复语义：
- 某实例不再命中 → 从 children 移除（或标记 resolved）。**"不再命中"的两种情形（评审补充）**：
  - 值恢复（低于阈值）：正常恢复，从 children 移除
  - **序列消失（no_data，如 Pod 被删/实例下线）：默认视为恢复**，从 children 移除；规则级连续无数据由现有 `no_data_count` 评估路径兜底（evaluator 已有），不在此阶段扩展
- **聚合根的生命周期 = 最后一个 active 子告警消失**：全部子实例恢复后，聚合根 resolve 并发送一次恢复通知
- 部分恢复不触发根的通知（避免通知风暴）

注意：同一规则同一次评估命中多条序列（多实例），天然是收敛候选（同一 group_key 同窗口），先到者建根，其余归并。

### 聚合根与事件中心（评审补充，阶段 0/1 同上线时的约定）

- 若阶段 0（事件中心）已上线：聚合根**创建与 resolve** 各写一条事件；children 归并更新**不写事件**（防事件风暴）
- 阶段 1 不依赖阶段 0 即可落地（见第 0 节）；此约定仅为两阶段同上线时的事件语义一致

## 3. 拓扑抑制流程（新函数，复用 alert_matching 祖先遍历）

```python
def check_topology_suppression(alert, ancestor_hops=3) -> bool
```

- 触发点：
  - 规则告警：评估 upsert 时，且 `rule.suppress_by_topology=True`
  - 外部告警：`AlertSource.suppress_by_topology=True`（AlertSource 新增同名字段，默认 False，设计内一并给出）
- **性能（评审补充）**：拓扑抑制按实例做祖先查询（≤3 层），每次评估全量重查成本高。优化：
  - 已 `suppressed=True` 的告警在下一轮跳过祖先查询（除非父资源状态变化——由父 resolve 后子下一轮评估自然解除，周期兜底 ≤ 规则间隔）
  - 未抑制实例每轮最多一次查询；查询结果仅状态翻转时写库
  - 顶层判断：`matched_resource` 为空直接返回 False，不查库
- 逻辑：
  1. `alert.matched_resource` 为空 → 返回 False（不抑制）
  2. 复用 alert_matching 祖先遍历（contains 反向 + belongs_to/runs_on/deployed_on 正向，ancestor_hops 层）得到祖先资源集合
  3. 存在祖先资源上有 **active 且未 suppressed** 的告警 → `suppressed=True`、`suppressed_reason='父资源 {name} 存在 active 告警'`
- 恢复语义：父告警 resolve 后，下一轮评估重新判定，子告警自动取消 suppressed（正常流转）
- 优先级：**用户显式静默（AlertSilence）> 拓扑抑制**——静默的告警照常静默；拓扑抑制只是"不发通知 + 标记"

### 抑制与收敛的交互（评审补充）

- 抑制判定发生在实例层面（子实例、聚合根各自独立判定）
- 被抑制的子实例**仍计入**聚合根的 occurrence_count 累积（收敛语义不因抑制改变）
- 聚合根自身未被抑制时，根照常发一次通知；子实例的抑制不影响根的通知
- 收敛后的聚合根若被抑制（根资源自身命中父级抑制），则不通知、标记 suppressed

## 4. 通知层改动（ops/alerting.py）

- `dispatch_alert_batch_notifications`：过滤 `suppressed=True` 的告警（不入 fire/resolved 批次、不参与风暴统计）
- `apply_escalation_policy`：跳过 suppressed 告警
- 收敛聚合根照常走现有通知批次逻辑（通知一次即可，children 变化不逐条通知）

## 5. API 改动

### GET /api/alerts/
新增过滤参数：`suppressed`（bool）、`is_group_root`（bool）、`group_key`
响应字段新增：`group_key` / `group_parent_id` / `is_group_root` / `children_count` / `suppressed` / `suppressed_reason`

### GET /api/alerts/{id}/
聚合根详情返回 `children` 摘要列表：`[{id, title, level, resource, occurred_at}]`（前端展开用）

### GET /api/alerts/{id}/children/
独立端点返回聚合明细（分页），独立告警返回空列表

### /api/alert-rules/ 与 /api/alert-sources/
Serializer 补字段：规则侧 `group_fields` / `group_window` / `repeat_interval` / `suppress_by_topology` / `suppress_ancestor_hops`；源侧 `suppress_by_topology`

## 6. 测试计划（新增 backend/ops/test_convergence_suppression.py）

1. **收敛**：同窗口同 group_key 两次命中 → 一条聚合根，occurrence_count=2，children 正确；跨窗口 → 新建根；配置 group_fields 不同分组键各自独立；部分恢复不触发根通知；全部恢复后根 resolve 且发一次恢复通知
2. **抑制**：父资源 active 时子告警 suppressed=True 且通知批次不含它（mock 通知验证）；父 resolve 后子恢复独立评估；无 matched_resource 不抑制；`suppress_by_topology=False` 时行为与现状一致
3. **静默优先级**：显式静默 + 拓扑抑制同时存在 → 静默语义生效
4. **API**：suppressed/is_group_root 过滤、children 展开、规则/源字段序列化
5. **回归门禁**：test_multi_source_alerts / test_alert_ingest / test_waiting_alert_stability / alerting 通知批次相关既有测试全绿（未开收敛/抑制时零行为变化）

## 7. 影响范围与回滚

- 新增：两个迁移、`check_topology_suppression`（放 alert_matching.py 或新模块）、test_convergence_suppression.py
- 修改：pipeline.py（收敛归并）、alerting.py（通知过滤）、alert_matching.py（复用）、serializers.py、views.py、alert_ingest.py（外部告警抑制判定，走 AlertSource 开关）
- 不动：webhook 协议、Alert 既有字段语义、通知渠道
- 回滚：撤销迁移（新字段默认值不影响存量）+ 撤代码改动；开启状态的规则/源关闭开关即恢复旧行为（**功能开关设计保证可逆**）

## 8. 验收标准

1. 同一波同组告警（同规则多实例/多轮命中）归并为一条聚合告警，occurrence_count 累积、children 可展开
2. 父资源存在 active 告警时，子资源告警 suppressed 且不发通知；拓扑抑制默认关闭，按规则/按源显式开启
3. 显式静默优先级高于拓扑抑制
4. 未开启收敛/抑制时，行为与现状完全一致（回归门禁全绿）
5. API 暴露 suppressed/聚合相关字段与过滤；自动化测试全绿
