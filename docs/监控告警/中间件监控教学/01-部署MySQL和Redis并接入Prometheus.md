# Xing-Cloud MySQL / Redis Prometheus 接入教程

## 目标

让当前部署中的 Xing-Cloud MySQL 和 Redis 被 Prometheus 原生采集，用于数据库/中间件看板、告警规则试运行和 AIOps 证据。

本文参考 `2. 部署mysql服务并监控mysql.md` 的结构，但适配当前 Xing-Cloud 已存在的 `xing-cloud` namespace，不重新创建业务数据库，也不把密码写入 exporter manifest。

## 环境清单

```bash
kubectl get nodes
kubectl get pod -n monitoring
kubectl get pod -n xing-cloud
kubectl get svc -n xing-cloud
kubectl get sc
```

期望状态：

- K8S 节点为 `Ready`。
- `monitoring/prometheus-k8s-*` 为 `Running`。
- `xing-cloud/xing-cloud-mysql-0` 为 `Running`。
- `xing-cloud/xing-cloud-redis-*` 为 `Running`。
- 集群已安装 `servicemonitors.monitoring.coreos.com` CRD。

## 当前对象

- namespace：`xing-cloud`
- MySQL Service：`xing-cloud-mysql:3306`
- Redis Service：`xing-cloud-redis:6379`
- Prometheus Service：`monitoring/prometheus-k8s:9090`
- Prometheus 查询地址：以当前环境在 `可观测性 / 数据源` 中登记的地址为准。

## 资源设计

`k8s/08-monitoring.yaml` 包含：

- `Role/RoleBinding`：允许 `monitoring/prometheus-k8s` 在 `xing-cloud` namespace 读取 `services/endpoints/pods/ingresses`。
- `xing-cloud-mysql-exporter`：使用 `prom/mysqld-exporter` 采集 MySQL 指标。
- `xing-cloud-mysql-metrics`：暴露 `9104/metrics`。
- `ServiceMonitor/xing-cloud-mysql`：让 Prometheus Operator 自动生成 scrape job。
- `xing-cloud-redis-exporter`：使用 redis exporter 采集 Redis 指标。
- `xing-cloud-redis-metrics`：暴露 `9121/metrics`。
- `ServiceMonitor/xing-cloud-redis`：让 Prometheus Operator 自动生成 scrape job。
- `PrometheusRule/xing-cloud-mysql-rules`：提供 MySQL 存活、连接数、慢查询示例规则。
- `PrometheusRule/xing-cloud-redis-rules`：提供 Redis 存活、内存、拒绝连接示例规则。

当前 `xing-cloud-mysql-exporter` 显式增加 `--no-collect.slave_status`。Xing-Cloud 内置 MySQL 作为平台测试库使用，不是主从复制拓扑；关闭 `SHOW SLAVE STATUS` 采集可以避免普通业务账号因缺少 `REPLICATION CLIENT` 权限而反复打印无价值错误，同时保留 `mysql_up`、连接数、慢查询等基础监控指标。

## 部署

在仓库根目录执行：

```bash
cd <仓库目录>/k8s
kubectl apply -f 08-monitoring.yaml
```

如果是完整部署，`deploy.sh` 会在基础 MySQL/Redis manifest 后自动尝试应用 `08-monitoring.yaml`。如果集群没有安装 ServiceMonitor CRD，会跳过中间件监控清单。

## 验证

确认 exporter 运行：

```bash
kubectl get pods -n xing-cloud | egrep 'mysql-exporter|redis-exporter'
kubectl get svc -n xing-cloud | egrep 'mysql-metrics|redis-metrics'
kubectl get servicemonitor -n monitoring | egrep 'xing-cloud-(mysql|redis)'
```

确认 Prometheus 有 namespace 发现权限：

```bash
kubectl auth can-i --as=system:serviceaccount:monitoring:prometheus-k8s list services -n xing-cloud
kubectl auth can-i --as=system:serviceaccount:monitoring:prometheus-k8s list endpoints -n xing-cloud
kubectl auth can-i --as=system:serviceaccount:monitoring:prometheus-k8s list pods -n xing-cloud
```

确认 Prometheus target：

```bash
curl -s 'http://127.0.0.1:30003/api/v1/targets?state=active' | grep xing-cloud
```

确认指标：

```bash
curl -sG 'http://127.0.0.1:30003/api/v1/query' --data-urlencode 'query=mysql_up'
curl -sG 'http://127.0.0.1:30003/api/v1/query' --data-urlencode 'query=redis_up'
curl -sG 'http://127.0.0.1:30003/api/v1/query' --data-urlencode 'query=mysql_global_status_threads_connected'
curl -sG 'http://127.0.0.1:30003/api/v1/query' --data-urlencode 'query=redis_memory_used_bytes'
```

确认规则：

```bash
kubectl get prometheusrules -n monitoring | egrep 'xing-cloud-(mysql|redis)-rules'
```

Prometheus UI 中打开 `Status -> Rules`，应能看到：

- `xing-cloud.mysql.rules`
- `xing-cloud.redis.rules`

## 平台侧使用

第一阶段可以先把这些指标用于规则 dry-run：

- MySQL 存活：`mysql_up == 0`
- MySQL 连接数：`mysql_global_status_threads_connected > 100`
- Redis 存活：`redis_up == 0`
- Redis 内存：`redis_memory_used_bytes / redis_memory_max_bytes > 0.85`

在平台 `资产管理 / 中间件资产` 登记真实实例，并在 `可观测性 / 监控看板` 选择数据库或中间件类型验证数据。

## 和参考教程的差异

- 参考教程会先创建独立 `mysql-test` / `postgresql-test` namespace；当前项目直接复用 `xing-cloud` 已部署的 MySQL/Redis。
- 参考教程使用 NodePort 连接数据库；当前 exporter 使用集群内 Service DNS，减少暴露面。
- 参考教程在文档中演示明文密码；当前 manifest 只引用 `xing-cloud-secret`。
- 参考教程部署 exporter 到 `monitoring` namespace；当前 exporter 放在 `xing-cloud` namespace，ServiceMonitor 放在 `monitoring` namespace，便于贴近被监控对象和后续平台治理。
