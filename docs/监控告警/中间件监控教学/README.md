# 中间件监控教学目录

这个目录用于沉淀 Xing-Cloud 中间件创建、Exporter 部署、Prometheus 接入和平台可观测性验证的教学文档。

当前第一阶段聚焦项目自带中间件：

- MySQL：`xing-cloud/xing-cloud-mysql`
- Redis：`xing-cloud/xing-cloud-redis`
- Prometheus：`monitoring/prometheus-k8s`

推荐阅读顺序：

1. `01-部署MySQL和Redis并接入Prometheus.md`：从部署对象到 PromQL 验证的完整接入流程。
2. `02-镜像RBAC与采集目标排障.md`：镜像拉取、Prometheus RBAC、target 发现、指标为空的排障方法。
3. `03-部署PostgreSQL测试服务监控模板.md`：参考 PostgreSQL 教程整理出的后续测试服务模板。

配套清单：

- `k8s/08-monitoring.yaml`：Xing-Cloud 自带 MySQL/Redis 的 exporter、ServiceMonitor 和 Prometheus 命名空间发现权限。

参考资料：

- `C:/Users/zhang/Downloads/2. 部署mysql服务并监控mysql.md`
- `C:/Users/zhang/Downloads/4. 部署postgresql服务并监控postgresql.md`

本目录沿用上面两篇文档的教学结构：环境清单、服务部署、监控账号/exporter、资源验证、Prometheus target、PromQL、告警规则、排障。

注意事项：

- 文档中不记录真实密码。Exporter 使用 K8S Secret 引用数据库账号。
- Prometheus Operator 场景下，ServiceMonitor 创建成功不代表 Prometheus 已经能抓取，还要检查 Prometheus ServiceAccount 对目标 namespace 的 `services/endpoints/pods` 读取权限。
- 如果镜像无法拉取，可先使用当前集群已有镜像源；仍失败时再去 `https://docker.aityp.com/` 查找可替代镜像。
