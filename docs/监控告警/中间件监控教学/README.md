# 中间件监控教学

> 本目录说明如何让真实中间件 Exporter 被 Prometheus 采集。执行前请按当前集群、命名空间、镜像源和认证方式复核示例。

## 当前文档

1. [MySQL 和 Redis 接入 Prometheus](01-部署MySQL和Redis并接入Prometheus.md)
2. [镜像、RBAC 与采集目标排障](02-镜像RBAC与采集目标排障.md)
3. [PostgreSQL 接入 Prometheus 模板](03-PostgreSQL接入Prometheus模板.md)

配套清单 `k8s/08-monitoring.yaml` 包含当前项目 MySQL/Redis exporter、ServiceMonitor 和 Prometheus 读取权限。

## 平台接入流程

1. 部署并验证 exporter。
2. 在 Prometheus 原始接口确认指标存在。
3. 在 `可观测性 / 数据源` 测试 Prometheus。
4. 在 `资产管理 / 中间件资产` 登记真实实例。
5. 在业务上下文中选择该 Prometheus。
6. 在数据库/中间件看板验证指标。
7. 从内置模板创建规则实例并先试运行。

## 注意事项

- 不在文档、manifest 或仓库中记录真实密码，使用 Kubernetes Secret。
- ServiceMonitor 存在不代表 Prometheus 已成功抓取，还要检查 target、标签选择器和 ServiceAccount 权限。
- 新交付环境不自动创建演示中间件资产。
- 示例中的 namespace 和对象名对应当前仓库清单；接入其他业务实例时必须替换为真实值。
