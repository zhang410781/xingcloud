# XingCloud

XingCloud 是一个面向真实运维现场的智能运维平台。它把资产登记、平台管理、可观测性、事件中心、任务中心、工单系统、AIOps 和 RBAC 组织成可审计、可确认、可执行的工作流。

## 核心能力

| 模块 | 能力 |
| --- | --- |
| 运行概览 | 智能运维平台驾驶舱，聚焦 SLA、产品 SLA、工单及时率、告警和风险项。 |
| 资产登记 | 维护一级业务、环境、资产、运维负责人和项目负责人。 |
| 平台管理 | K8S 集群、kubeconfig 引导、容器环境、容器和镜像管理。 |
| 可观测性 | 平台总览、监控看板、日志中心、告警中心。 |
| 任务中心 | 主机和 K8S 执行任务、批量命令、Playbook、任务模板和执行记录。 |
| 工单系统 | 应用发布、审批流、SQL 审计和事务工单。 |
| 事件中心 | 平台事件、外部事件、事件环境、事件源和排障复盘时间线。 |
| AIOps | 智能助手、知识图谱、模型/MCP/Skill/Action 配置、智能体审计。 |
| 权限审计 | 后端 RBAC、前端路由、菜单、按钮和 WebSocket 权限统一控制。 |

## 可观测性边界

当前可观测性以监控和日志作为主要数据源：

- 指标源：Prometheus 兼容接口。
- 日志源：Loki、ELK/Elasticsearch、ClickHouse。
- 告警：平台内置告警规则主动触发，支持 AI 研判和通知推送。

当前不提供 Jaeger、SkyWalking、Tempo、Zipkin、SLS 接入，也不提供客户系统反向写入告警中心的 Webhook 能力。外部事件仍可接入事件中心。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | Django、Django REST framework、Channels、Daphne |
| 前端 | Vue 3、Vue Router、Pinia、Element Plus、ECharts、Vite |
| 数据库 | MySQL |
| 缓存与实时通信 | Redis、Channels Redis |
| 平台集成 | Kubernetes API、Docker、SSH、Prometheus 兼容接口、Loki、ELK、ClickHouse |

## 快速启动

后端：

```bash
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_templates
python -m daphne -b 0.0.0.0 -p 8000 xing_cloud.asgi:application
```

前端：

```bash
cd frontend
npm install
npm run dev
```

本地开发地址：

- 前端：`http://localhost:3000`
- 后端：`http://localhost:8000`

## 部署说明

生产部署建议显式配置：

- `SECRET_KEY`
- `DEBUG=0`
- `ALLOWED_HOSTS`
- MySQL 连接参数
- Redis 连接参数
- 默认域名和公网访问地址
- 日志源、指标源、通知渠道等运行时配置

当前测试阶段不保留历史演示数据，可以使用全新的数据库和 Redis。

## 文档

- [项目架构](docs/项目架构.md)
- [用户使用文档](docs/用户使用文档.md)
- [可观测性模块架构](process/observability-module-architecture.md)
