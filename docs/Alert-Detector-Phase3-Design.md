# 阶段 3 详细设计：检测算法插件化（detector 注册表）

> 状态：已实施（2026-08-07 生产上线，commit 0590e3c，镜像 detector-20260807）。
> 范围（已拷问确认）：按项目需要接入关键算法；配置"能自动调用就行"（参数全默认值兜底）；基准用 Prometheus range query 现查；后端+测试，前端后置。
> 对照总体规划：`docs/Alert-Closure-Improvement-Plan.md` 阶段 3。

## 0. 现状核实（代码事实）

| 事实 | 位置 |
|------|------|
| 统计检测算法已有纯 Python 实现（3-Sigma / EWMA / IQR / Isolation Forest），带 eligible/score/threshold/detail 输出结构，**但从未接入规则引擎** | ops/anomaly_detection.py |
| 规则命中判定为静态阈值：`_compare(value, condition)`（operator 默认 `>` + threshold） | ops/alert_engine/evaluator.py:45-50 |
| PromQL 查询支持 range 模式（start_time / end_time / step）——基准数据现查基础 | ops/observability_views.py:427 `execute_promql_query` |
| dry-run 评估端点已存在，不产生告警 | ops/views.py:2842 `/api/alert-rules/{id}/evaluate/` |
| 证据结构已有：`result_evidence('prometheus', query, value, labels, raw)` | ops/alert_engine/evaluator.py:147 |

## 1. 检测算法选型（按项目需要）

首批接入 4 个，覆盖运维告警主场景：

| 算法 | 适用场景 | 依据 |
|------|----------|------|
| `threshold` | 静态阈值（现状） | 默认算法，**旧规则零迁移** |
| `yoy` | 同比：负载/流量/延迟周期性波动（较昨日同期、上周同日） | 运维告警最常用基准比较 |
| `wow` | 环比：较上一周期（24h 前/7d 前） | 无周期数据源的对比 |
| `sigma` | 3-Sigma 统计检测（复用 anomaly_detection._sigma） | 无周期、无固定基线场景 |

后置（注册表占位，不接入实现）：EWMA / IQR / Isolation Forest——样本要求高（≥10/20）、误报率高、不可解释，运维告警价值低于前三者。

## 2. 架构：detector 注册表（新增 ops/alert_engine/detectors.py）

```python
DETECTORS = {
    'threshold': {'label': '静态阈值', 'params': {}, 'implemented': True},
    'yoy':       {'label': '同比',     'params': {'period': 'day', 'delta_pct': 30, 'operator': '>'}, 'implemented': True},
    'wow':       {'label': '环比',     'params': {'period': 'day', 'delta_pct': 30, 'operator': '>'}, 'implemented': True},
    'sigma':     {'label': '3-Sigma',  'params': {'window_minutes': 120, 'threshold': 3.0}, 'implemented': True},
    'ewma':      {'label': 'EWMA',     'params': {}, 'implemented': False},
    'iqr':       {'label': 'IQR',      'params': {}, 'implemented': False},
    'isolation_forest': {'label': 'Isolation Forest', 'params': {}, 'implemented': False},
}

def run_detector(name, current_value, context) -> dict
# 返回：{'matched': bool, 'algorithm': name, 'baseline': float|None,
#       'delta': float|None, 'score': float|None, 'detail': str, 'params': {...}}
```

- **配置形态**：`AlertRule.detector` JSONField，默认 `{'name': 'threshold', 'params': {}}`；缺省/空 = threshold（零迁移）
- **自动调用**：params 与注册表默认值合并（用户只填算法名即可）；算法名不存在或 `implemented=False` → 回退 threshold，evidence 标注 `detector_fallback` 原因
- **统一输出进 evidence**：`_prometheus_results` 的 result_evidence 追加 `detector` 段（algorithm/baseline/delta/score/detail/params）
- **基准缓存（评审补充，性能）**：yoy/wow/sigma 每轮评估都发 range query（窗口 1-2h），规则数增长时 Prometheus 压力线性上升。基准结果按 `(rule_id, algorithm, period_key)` 缓存 5 分钟（Django cache，`_resource_stale_cache_key` 同款前缀风格），窗口内复用；命中/未命中判定仍每轮实时计算（只复用基准序列）

## 3. 各算法逻辑（基准全部 Prometheus range query 现查）

### yoy（同比）
- 评估时对 `query` 做 range 查询：`[now - period - window, now - period]`（period=day 取昨日同时段；period=week 取上周同日）
- baseline = 窗口内样本均值（空序列 → eligible=False，不误报）
- `delta = (current - baseline) / baseline`；命中条件：operator 方向 + `|delta| >= delta_pct/100`
- 参数：`period`（day/week，默认 day）、`delta_pct`（默认 30）、`operator`（`>`/`<`，默认 `>`）

### wow（环比）
- 当前窗口 `[now - window, now]` vs 对比窗口 `[now - period - window, now - period]`（period 默认 day）
- baseline = 对比窗口均值；delta/命中同上
- 参数：`period`（默认 day）、`delta_pct`（默认 30）、`operator`（默认 `>`）、`window_minutes`（默认 60）

### sigma（3-Sigma）
- range 查询历史窗口（默认 120 分钟，step 60s）取样本序列
- 复用 `anomaly_detection._sigma(history, current, threshold)`：样本 < 10 → eligible=False（不误报）
- 参数：`window_minutes`（默认 120）、`threshold`（默认 3.0）

### 适用范围
- 仅 Prometheus 规则支持非 threshold 算法（基准依赖 range query）
- ClickHouse 日志规则：detector 配置非 threshold 时回退 threshold 并 evidence 标注（日志告警以计数/关键字判定为主，不引入基准比较）

## 4. 评估链路改造（ops/alert_engine/evaluator.py）

- `_prometheus_results`（evaluator.py:96）命中判定从 `_compare` 改为 `run_detector(rule.detector, value, context)`；threshold 走注册表同一入口（内部仍调 _compare，行为不变）
- 每次评估的 results 携带 detector 输出；`matched` 由算法决定
- dry-run 响应原样携带 evidence.detector 明细（前端后续展示）
- 通知/收敛/抑制链路不感知算法差异（evidence 只读附加）

## 5. API 改动

| 端点 | 说明 |
|------|------|
| `/api/alert-rules/`（serializer） | 补 `detector` 字段（JSON，可写，校验算法名存在性） |
| `GET /api/alert-rules/detectors/` | 注册表列表：name/label/params 说明/是否已接入（前端配置页后续用） |
| `/api/alert-rules/{id}/evaluate/`（dry-run，已有） | 响应 evidence 含 detector 明细 |

## 6. 测试计划（新增 backend/ops/test_detectors.py）

1. **注册表路由**：合法算法正常路由；非法/未接入算法回退 threshold 且 evidence 标注；detector 缺省时行为与现状一致
2. **yoy/wow**：mock execute_promql_query 返回同期数据 → matched 与 delta 计算正确；空序列/样本不足 → 不误报；operator 方向（上升/下降）分别验证
3. **sigma**：样本 < 10 不误报（eligible=False）；正常命中验证
4. **日志规则回退**：ClickHouse 规则配 yoy → 回退 threshold 且标注
5. **API**：serializer 写入校验、detectors 列表端点、dry-run evidence 含 detector 段
6. **回归门禁**：test_multi_source_alerts / test_alert_quality / test_waiting_alert_stability 全绿（threshold 路径零变化）

## 7. 影响范围与回滚

- 新增：ops/alert_engine/detectors.py、迁移（AlertRule.detector 字段）、test_detectors.py
- 修改：evaluator.py `_prometheus_results`（命中判定路由到注册表）、serializers.py、views.py（detectors 端点）
- 不动：condition 字段语义、ClickHouse 规则行为、通知/收敛/抑制链路
- 回滚：撤销迁移；detector 缺省即旧行为，无需数据回填

## 8. 验收标准

1. 规则可选择 yoy/wow/sigma（只填算法名即可，参数有默认值）；阈值旧规则零迁移、行为不变
2. 基准由 Prometheus range query 现查同期/对比窗口，证据输出 algorithm/baseline/delta/score
3. 数据不足、非法配置、未接入算法一律不误报（eligible 语义 + 回退标注）
4. 后端 API + 自动化测试全绿
