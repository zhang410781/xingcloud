# 参考代码索引

本目录包含从 Nightingale v6 (github.com/ccfos/nightingale) 提取的核心参考代码，用于指导 XingCloud 告警引擎和看板引擎建设。

> Nightingale 是 Apache 2.0 开源项目，本目录仅用于参考学习。

---

## 告警引擎核心

| 文件 | 来源 | 参考价值 |
|------|------|---------|
| `alert-process.go` | `alert/process/process.go` | 告警事件状态机：pending/firing/resolved 生命周期管理，事件去重，与 eval 和 dispatch 的衔接 |
| `alert-dispatch.go` | `alert/dispatch/dispatch.go` | 通知分发编排器：sender 注册、渠道选择、订阅匹配、通知规则评估、回调执行 |
| `mute.go` | `alert/mute/mute.go` | 静默策略：时间窗口、标签匹配、业务组过滤，多策略 OR/AND 组合 |
| `hashring.go` | `alert/naming/hashring.go` | 一致性哈希：告警引擎水平扩展的分片机制，多实例负载均衡 |

## 告警流水线

| 文件 | 来源 | 参考价值 |
|------|------|---------|
| `pipeline.go` | `alert/pipeline/pipeline.go` | 处理器注册模式：插件式架构，所有 processor 通过 import 自注册 |
| `pipeline-engine.go` | `alert/pipeline/engine/engine.go` | DAG 工作流引擎：拓扑排序、节点执行、重试、超时、执行记录 |
| `event_processor.go` | `models/event_processor.go` | 处理器接口定义：`Processor.Init()` / `Process()`，注册表 `RegisterProcessor()` |
| `ai_summary.go` | `alert/pipeline/processor/aisummary/ai_summary.go` | AI 摘要处理器：调用 LLM OpenAI 兼容接口，提示词模板，可配置 model/params |

## 数据源抽象

| 文件 | 来源 | 参考价值 |
|------|------|---------|
| `datasource.go` | `datasource/datasource.go` | 数据源分类(timeseries/logging)、插件类型注册、init() 自注册模式 |

## 数据模型

| 文件 | 来源 | 参考价值 |
|------|------|---------|
| `alert_mute.go` | `models/alert_mute.go` | 静默规则模型：TagFilter( key/func/value ) + 时间窗口，标签操作符体系 |
| `dashboard.go` | `models/dashboard.go` | 看板模型：layout + panels + targets 存储结构，面板查询方法 |

## 看板 API

| 文件 | 来源 | 参考价值 |
|------|------|---------|
| `router_dashboard.go` | `center/router/router_dashboard.go` | 看板 CRUD + 查询接口：面板遍历 → 数据源查询 → 结果聚合 |

## 配置参考

| 文件 | 来源 | 参考价值 |
|------|------|---------|
| `config.toml` | `etc/config.toml` | 完整配置参考：HTTP/DB/Redis/Alert/Pushgw/Auth/Logging |

---

## 文件说明

所有文件保留原始代码内容，未做修改。Go 代码与 XingCloud 的 Python/Django 技术栈不同，但**架构模式和设计思路**可直接参考：

1. **处理器注册模式** (`pipeline.go` + `event_processor.go`) — Django 中可用 `AppConfig.ready()` + 装饰器实现
2. **静默标签匹配** (`mute.go`) — TagFilter 操作符设计可复用到 Django ORM
3. **看板 JSON 结构** (`dashboard.go`) — layout/panels/targets 的序列化结构直接参考
4. **DAG 工作流** (`pipeline-engine.go`) — 适合降噪管线的责任链和条件分支
