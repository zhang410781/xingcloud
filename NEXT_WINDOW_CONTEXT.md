# XingCloud 下一窗口交接备忘

更新时间：2026-07-09

## 当前阶段状态

本阶段已经完成并上线。当前窗口可以归档，下一阶段建议新开窗口从可观测模块重新设计开始。

项目本地路径：

```text
C:\Users\zhang\Desktop\百度\Agent\Master\xing-cloud-ops-agent-skill\devops-main\xing-cloud-main
```

线上源码路径：

```text
/xing/devops
```

线上部署镜像：

```text
registry.cn-hangzhou.aliyuncs.com/xinghaik8s/ops-agent:a1.05
```

线上命名空间：

```text
xing-cloud
```

线上访问：

```text
Host: xinghai.example.com
Ingress Address: 10.105.118.19
```

最近一次上线验证结果：

- `xing-cloud-app`：Running `1/1`
- `xing-cloud-scheduler`：Running `1/1`
- `xing-cloud-mysql-0`：Running `1/1`
- `xing-cloud-redis`：Running `1/1`
- Ingress HTTP 探活返回 `HTTP/1.1 200 OK`

## 已清理边界

当前项目不需要以下能力，后续不要再按旧设计恢复：

- Jaeger
- SkyWalking
- Tempo
- Zipkin
- 阿里云 SLS / Logstore
- Grafana 配置、跳转、嵌入、面板导入兼容
- 告警中心客户反向写入 Webhook

保留但要注意区分：

- 事件中心 Webhook：保留，这是事件墙/事件中心能力，不属于告警中心反向写入。
- 告警通知渠道 `webhook_url`：保留，这是平台主动推送飞书、钉钉、企微，不是客户系统写入平台告警。
- Loki 支持：保留。代码里 `grafana/loki` 只是 Loki 官方镜像名，不代表启用 Grafana。
- 日志里的 `trace_id`、`span_id`、`request_id` 可以作为普通检索字段，不代表平台有链路追踪模块。

历史 migration 中可能还会出现旧模型名，这是 Django 迁移链记录，不代表运行功能仍存在。

## 数据库和数据状态

本阶段上线时已删除并重建 `xing-cloud` 命名空间，旧 MySQL/Redis 数据不保留。

当前 K8S 配置：

- MySQL database：`xing_cloud_main`
- Redis cache：`redis://xing-cloud-redis:6379/2`
- Redis channel layer：`redis://xing-cloud-redis:6379/3`
- Cache key prefix：`xing-cloud-main`

线上 `/xing/devops` 已清理为源码部署最小集合，只保留：

- `backend`
- `frontend`
- `docker/entrypoint.sh`
- `Dockerfile`
- `.dockerignore`
- `k8s`

## 当前默认数据源

日志源：

- `智能运维平台 ClickHouse 日志`
- provider：`clickhouse`
- endpoint：`http://10.132.46.52:30812`
- 用户名：`xinghai`
- 密码在 `k8s/02-secret.yaml` 中配置
- collections：
  - `container-logs`
  - `k8s-events`
  - `ingress-access`

指标源：

- `智能运维平台 Prometheus`
  - environment：`智能运维平台`
  - query_url：`http://10.132.46.52:30003`
  - 默认指标源：是
- `测试环境 Prometheus`
  - environment：`测试环境`
  - query_url：`http://10.132.46.66:30003`
  - 默认指标源：否

测试环境日志源目前缺失，不要伪造测试环境日志数据。

## 环境清单

智能运维平台 K8S 集群：

```text
k8s-master      10.132.46.52  control-plane
10-132-46-53    10.132.46.53  worker
k8s-gpu-01      10.132.46.80  worker
k8s-gpu-02      10.132.46.81  worker
```

测试环境 K8S 集群：

```text
master1         10.132.46.64  control-plane
master2         10.132.46.65  control-plane
master3         10.132.46.66  control-plane
10.132.46.59    10.132.46.59  worker
gpu-worker1     10.132.46.57  worker
gpu-worker2     10.132.46.58  worker
work1           10.132.46.67  worker
```

## 上线流程

常用部署命令：

```bash
cd /xing/devops
TAG=a1.06 bash k8s/deploy.sh
```

如果需要彻底清空线上数据重建：

```bash
cd /xing/devops
RESET_DATA=1 TAG=a1.06 bash k8s/deploy.sh
```

镜像仓库：

```text
registry.cn-hangzhou.aliyuncs.com/xinghaik8s/ops-agent
```

基础镜像要求：

```text
swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim
swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/node:20-alpine
swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/mysql:8.0.28
swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/redis:7-alpine
```

线上验证命令：

```bash
kubectl get pods,svc,ingress -n xing-cloud -o wide
kubectl logs -n xing-cloud deploy/xing-cloud-app --tail=100
kubectl logs -n xing-cloud deploy/xing-cloud-scheduler --tail=100
curl --noproxy '*' -I -m 10 -H 'Host: xinghai.example.com' http://10.105.118.19/
```

## 下一阶段建议：可观测模块

下一阶段建议围绕“平台原生可观测”重新设计，不要沿用旧 Grafana/Trace 兼容路径。

建议模块边界：

- 平台总览
- 监控看板
- 日志中心
- 告警中心
- 数据源配置

建议数据源模型：

- 指标：Prometheus-compatible HTTP API
- 日志：ClickHouse，后续可继续保留 Loki / ELK 扩展
- 告警：平台内置规则计算，不接收客户系统反向 Webhook

领导驾驶舱已明确关注：

- 本月 SLA 状态：达标 / 风险 / 未达标
- 年度 99.96% 目标能否达成
- 数据库、中间件、容器平台、网络、服务器等产品 SLA
- 工单数量和处理及时性
- 告警数量、告警分类、风险项
- 灾难级别持续时长可用于 SLA 计算

下一窗口开场可以直接说：

```text
请读取 NEXT_WINDOW_CONTEXT.md，基于当前已上线的 XingCloud，重新设计并实现可观测模块。不要恢复 Jaeger/SkyWalking/Tempo/Zipkin/SLS/Grafana/Webhook 告警接入。当前数据源以 Prometheus 指标和 ClickHouse 日志为主。
```
