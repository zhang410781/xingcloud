# 历史设计索引

> **历史状态：以下文档用于保留设计和演进过程，不代表当前产品能力。**
> 当前定义请从 [文档中心](../README.md) 和 [产品定义](../产品定义/README.md) 开始阅读。

## AIOps

- [AIOps 2.0 升级优化方案](AIOps/AIOps2.0升级优化方案.md)
- [AIOps 2.1 指标证据包设计](AIOps/AIOps2.1指标证据包设计.md)
- [Action Handler 与上下文 Copilot](AIOps/AIOps2.1.2-Action-Handler与上下文Copilot设计.md)
- [MCP + Skill 双阶段应答设计](AIOps/AIOps-MCP-Skill-双阶段应答设计.md)

## 可观测与告警

- [历史方案索引](可观测与告警/README.md)

## 日志

- [ClickHouse 日志集合设计](日志/2026-07-08-ClickHouse日志集合设计.md)

## 历史截图

- `screenshots/事件中心.png`：当前菜单已不包含独立事件中心。
- `screenshots/xing-cloud-operation-flow.png`：旧产品运转逻辑图，架构描述已被当前项目架构替代。

历史文档中出现的 Celery Beat、Redis Stream、七个独立智能体、Trace、看板编辑器或自动自愈等内容，均应结合当前代码重新判断，不能作为交付承诺。
