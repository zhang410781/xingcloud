# PostgreSQL 接入 Prometheus 模板

本文用于把已有或新部署的 PostgreSQL 接入 Prometheus。Xing-Cloud 不会默认创建 PostgreSQL 或伪造数据库资产，所有 namespace、凭据和资源参数都应替换为目标生产环境的真实配置。

## 建议结构

- namespace：`postgresql-test`
- Secret：保存 `POSTGRES_USER`、`POSTGRES_PASSWORD`
- PVC：保存 PostgreSQL 数据目录
- Deployment：单实例 PostgreSQL，更新策略使用 `Recreate`
- Service：集群内访问优先，确需外部访问时再启用 NodePort
- Exporter：`prometheuscommunity/postgres-exporter`
- ServiceMonitor：由 Prometheus Operator 自动生成 scrape job
- PrometheusRule：用于存活、连接数、锁等待、数据库大小等示例规则

## 部署前检查

```bash
kubectl get nodes
kubectl get pod -n monitoring
kubectl get crd servicemonitors.monitoring.coreos.com
kubectl get sc
```

## Exporter 示例

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres-exporter
  namespace: postgresql-test
  labels:
    app: postgresql
    component: postgres-exporter
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgresql
      component: postgres-exporter
  template:
    metadata:
      labels:
        app: postgresql
        component: postgres-exporter
    spec:
      containers:
        - name: postgres-exporter
          image: prometheuscommunity/postgres-exporter:v0.15.0
          env:
            - name: DATA_SOURCE_NAME
              valueFrom:
                secretKeyRef:
                  name: postgres-exporter-secret
                  key: DATA_SOURCE_NAME
          ports:
            - name: metrics
              containerPort: 9187
---
apiVersion: v1
kind: Service
metadata:
  name: postgres-exporter
  namespace: postgresql-test
  labels:
    app: postgresql
    component: postgres-exporter
spec:
  selector:
    app: postgresql
    component: postgres-exporter
  ports:
    - name: metrics
      port: 9187
      targetPort: metrics
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: postgres-exporter
  namespace: monitoring
  labels:
    prometheus: k8s
spec:
  namespaceSelector:
    matchNames:
      - postgresql-test
  selector:
    matchLabels:
      app: postgresql
      component: postgres-exporter
  endpoints:
    - port: metrics
      interval: 30s
```

## PromQL 验证

```bash
curl -sG 'http://127.0.0.1:30003/api/v1/query' --data-urlencode 'query=pg_up'
curl -sG 'http://127.0.0.1:30003/api/v1/query' --data-urlencode 'query=pg_stat_activity_count'
curl -sG 'http://127.0.0.1:30003/api/v1/query' --data-urlencode 'query=pg_database_size_bytes'
```

## 注意事项

- Prometheus 需要目标 namespace 的 `services/endpoints/pods` 读取权限。
- `DATA_SOURCE_NAME` 建议放到 Secret，不写入文档或 manifest 明文。
- 如果镜像无法拉取，可按 `02-image-rbac-target-troubleshooting.md` 中的方法替换为镜像站地址。
- 当前 Xing-Cloud 第一阶段不依赖 PostgreSQL；这个模板主要用于后续中间件测试和教学扩展。
