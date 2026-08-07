# 告警闭环改进总体规划

> 对标蓝鲸运维平台（bk-monitor → 统一告警 → 故障自愈/标准运维）梳理。
> 覆盖四个方向：事件中心落地、告警收敛+拓扑抑制、值班表+告警转工单、检测算法插件化。
> 本规划只做方案设计；每个阶段开工前单独做一次 vc-intent-clarify 拷问确认细节。

## 现状（代码事实）

| 能力 | 现状 | 关键位置 |
|------|------|----------|
| 外部告警接入 | Prometheus 规则（真实 PromQL 查询）+ Zabbix/Alertmanager webhook 归一化，fingerprint 幂等、Waiting 去重、通知批次、AI 研判均已成熟 | ops/alert_engine/、ops/alert_ingest.py |
| 事件中心 | eventwall_stub.py 全部 no-op（"intentionally a no-op"） | ops/eventwall_stub.py |
| 收敛/抑制 | 有 AlertSilence 静默；无跨告警收敛、无拓扑抑制 | ops/models.py |
| 值班 | 有 AlertRecipientGroup 接收组；无排班表 | ops/models.py |
| 转工单 | 有 TransactionTicket；无任何告警→工单联动路径 | ops/models.py |
| 拓扑基础 | 资产拓扑 ResourceRelation(contains)、告警资源匹配 alert_matching.py 已存在 | resource_center/ |
| 检测算法 | condition 静态阈值；anomaly_detection.py 存在未接入规则引擎 | ops/anomaly_detection.py |

## 阶段 0：事件中心落地（地基，依赖：无）

### 目标
所有来源（外部 webhook、平台内部变更/部署/K8s 事件/巡检）统一落 Event，Alert 由事件驱动，复盘有完整时间线。

### 方案
1. 新增 `Event` 模型：source_type / kind / severity / target_type / target_resource / message / payload / occurred_at / alert_id（可空外键）
2. 接入改造：`ingest_external_alert_payload` 在 upsert Alert 前先写 Event（携带 ingest 元数据），webhook 响应协议**保持不变**（现有 Zabbix/Alertmanager 对接零改动）
3. 平台内部事件写入：部署、变更、K8s 事件、巡检结果等关键动作同步写 Event
4. API：`/api/events/` 只读查询（类型/目标/时间范围过滤、搜索），不开放外部写入
5. 保留策略：Event 滚动保留（可配置天数），Alert 长期保留；Event 删除不影响 Alert

### 影响范围
- 新增表 + 迁移；alert_ingest.py 插入写事件逻辑；ops_scheduler 巡检/发现结果补事件
- 不动 webhook 对外协议、不动 Alert 表结构

### 风险与回滚
- 重构点集中在 upsert 链路：fingerprint、恢复、reactivated、Waiting 语义必须与现状完全一致
- 门禁：test_alert_ingest.py / test_unified_alert_sources.py / test_multi_source_alerts.py / test_waiting_alert_stability.py 全绿
- 回滚：删除迁移即可，Alert 数据不受影响

### 验收标准
- 外部 webhook 语义（幂等/恢复/Waiting）与现状逐条一致
- 事件可查询、可按告警反查事件时间线
- 事件写失败不阻塞告警生成（降级为日志告警）

## 阶段 1：告警收敛 + 拓扑抑制（依赖：阶段 0 提供时间窗数据）

### 目标
Node 挂掉时几十条 Pod 告警归并/抑制，只留最上层一条，通知不风暴。

### 方案
1. **规则级收敛**：AlertRule 增加收敛配置（window_minutes / group_fields / max_count）；评估时同窗口同组归并为一条告警，occurrence_count 累积、可展开子项
2. **拓扑抑制**：告警经 alert_matching 关联资源 → 沿 ResourceRelation(contains) 查父资源是否有 active 告警；有则标记 `suppressed`（计数但不通知）
3. 抑制优先级：用户显式静默 > 拓扑抑制；**拓扑抑制默认关闭，按规则显式开启**（防误伤独立故障）
4. 通知：suppressed 告警不发；收敛告警只发一次

### 影响范围
- AlertRule 收敛字段、Alert 增加 suppressed 状态位、评估器与通知批次逻辑调整、告警列表前端标记
- 依赖 resource_center 拓扑查询接口

### 验收标准
- 场景模拟：父资源 active 时子资源告警被抑制；父恢复后子告警恢复独立评估
- 收敛计数正确、风暴阈值仍生效
- 默认关闭拓扑抑制时行为与现状一致

## 阶段 2：值班表 + 告警转工单（依赖：无；阶段 0 仅作为后续复盘时间线）

### 目标
升级通知给"当前值班人"；告警可转工单并回写状态。
（注：原规划中的"规则级自动动作（FTA 简化版+审批门禁）"已移出本阶段，后续单独评估。）

### 方案
1. **值班排班**：`OnCallSchedule` 模型（绑定 recipient_group + 星期位图 + 每日起止，支持隔夜班）；`apply_escalation_policy` 的接收人解析命中当班人，无班次时回退原接收人
2. **告警转工单**：告警详情"转工单"动作（仅手动、幂等）→ 创建 TransactionTicket（TYPE_INCIDENT）+ `AlertTicket` 关联表；工单状态/关联告警双向可查

### 影响范围
- 新增 OnCallSchedule、AlertTicket 表；升级策略接收人解析注入；serializer 补字段；告警详情操作区（前端后置）

### 验收标准
- 值班人收到升级通知；无排班时行为与现状一致（回退）
- 告警→工单→审批→完成闭环可走通，重复转单幂等
- 未配置值班时升级行为零回归

## 阶段 3：检测算法插件化（依赖：无，可与阶段 1/2 并行）

### 目标
规则引擎支持静态阈值之外的同比/环比等检测算法，统一证据与诊断。

### 方案
1. `detector` 注册表：threshold（现有）/ yoy（同比）/ wow（环比），AlertRule.detector 字段选择，**默认 threshold，旧规则零迁移**
2. yoy/wow 用 execute_promql_query range query 取同期基准做比较，输出 base_value / delta 进证据
3. 规则质量分（AlertRuleQuality）与 dry-run 面板兼容新算法

### 验收标准
- yoy 规则 dry-run 输出正确基准与偏差
- 旧规则行为与现状完全一致；算法切换可回滚

## 依赖图与里程碑

```
阶段0 事件中心 ──► 阶段1 收敛+拓扑抑制
   │                └──► 阶段2 值班+转工单
   └──► 阶段3 检测算法插件化（并行）
```

每阶段独立上线、独立回滚；建议顺序 0 → 1 → 2，3 可穿插。

## 上线节奏（按"快，风险可接受"）

- 每阶段：模型+迁移 → 后端逻辑 → 测试 → 前端（可后置）→ 部署（沿用现有 deploy 流程，迁移由 init job 执行）
- 阶段 0/1/2 各自是一次完整交付（含测试），阶段 3 视排期
