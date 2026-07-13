# 中间件监控排障：镜像、RBAC、Target

## ServiceMonitor 存在但 Prometheus 没有指标

先看 Prometheus 是否加载了 job：

```bash
kubectl exec -n monitoring prometheus-k8s-0 -c prometheus -- \
  sh -c 'wget -qO- http://127.0.0.1:9090/api/v1/status/config | grep xing-cloud'
```

再看 target：

```bash
curl -s 'http://127.0.0.1:30003/api/v1/targets?state=any' | grep xing-cloud
```

如果配置里有 job，但 target 为空，优先查 RBAC：

```bash
kubectl logs -n monitoring prometheus-k8s-0 -c prometheus --tail=100 | egrep -i 'forbidden|services|endpoints|pods'
kubectl auth can-i --as=system:serviceaccount:monitoring:prometheus-k8s list services -n xing-cloud
kubectl auth can-i --as=system:serviceaccount:monitoring:prometheus-k8s list endpoints -n xing-cloud
kubectl auth can-i --as=system:serviceaccount:monitoring:prometheus-k8s list pods -n xing-cloud
```

Prometheus Operator 生成 scrape job 后，Prometheus 仍然需要目标 namespace 的 `services/endpoints/pods` list/watch 权限，否则 Kubernetes SD 会发现失败。

## Exporter 自身是否正常

从 Prometheus Pod 内直接访问 exporter：

```bash
kubectl exec -n monitoring prometheus-k8s-0 -c prometheus -- \
  sh -c 'wget -qO- --timeout=5 http://xing-cloud-redis-metrics.xing-cloud.svc:9121/metrics | head'

kubectl exec -n monitoring prometheus-k8s-0 -c prometheus -- \
  sh -c 'wget -qO- --timeout=5 http://xing-cloud-mysql-metrics.xing-cloud.svc:9104/metrics | head'
```

如果这里能返回指标，但 Prometheus 查询为空，继续查 target 和 RBAC。  
如果这里也访问失败，查 exporter Pod、Service selector、Endpoint。

## 镜像拉取失败

查看失败原因：

```bash
kubectl describe pod -n xing-cloud -l component=mysql-exporter
kubectl describe pod -n xing-cloud -l component=redis-exporter
```

优先使用当前集群已经能拉取的镜像源。例如当前 Redis exporter 已有可用镜像：

```text
swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/bitnami/redis-exporter:1.52.0-debian-11-r5
```

如果某个镜像源不可用，可以到 `https://docker.aityp.com/` 搜索同名镜像，再替换 `k8s/08-monitoring.yaml` 里的 `image`。常见候选：

```text
docker.aityp.com/prom/mysqld-exporter:v0.14.0
docker.aityp.com/bitnami/redis-exporter:1.52.0-debian-11-r5
```

替换后重新应用：

```bash
kubectl apply -f k8s/08-monitoring.yaml
kubectl rollout status deployment/xing-cloud-mysql-exporter -n xing-cloud --timeout=180s
kubectl rollout status deployment/xing-cloud-redis-exporter -n xing-cloud --timeout=180s
```

## MySQL 账号权限

第一阶段 exporter 使用 `xing-cloud-secret` 里已有的 MySQL 账号。这个账号需要至少能执行：

```sql
SHOW GLOBAL STATUS;
SHOW GLOBAL VARIABLES;
```

如果后续要改成 exporter 专用账号，建议用最小权限账号，并把账号密码写入新的 K8S Secret，而不是写进 manifest。
