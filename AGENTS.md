# Xing-Cloud 项目说明与工作准则

## 项目定位
Xing-Cloud 是面向真实运维场景的智能运维平台，不是静态演示系统。
产品需要形成"资产与环境 -> 可观测性 -> 告警研判 -> 处置任务/工单 -> 审计复盘"的闭环。

## 技术基线
- 后端：Django、Django REST framework、Channels、Daphne、MySQL、Redis。
- 前端：Vue 3、Vue Router、Pinia、Element Plus、ECharts、Vite。
- 平台集成：Kubernetes API、SSH、Docker、Prometheus 兼容 API、ClickHouse；日志后续可扩展 Loki / ELK。
- 代码路径：backend/、frontend/、k8s/、docs/。
- 中文源文件必须使用 UTF-8。

## 当前研发优先级
第一优先级是补齐原生可观测性：
1. 原生监控面板：基于真实 Prometheus 指标和平台数据源，不依赖 Grafana 嵌入或跳转。
2. 告警规则：补齐规则模型、模板、阈值、持续时间、分级、聚合、通知、静默/抑制、状态流转和证据展示。
3. 告警闭环：告警应能关联指标、日志、K8s 资源/事件、变更和工单，并进入 AI 研判、确认、任务/工单和复盘。
4. 数据源体验：Prometheus 指标源、ClickHouse 日志源的配置、健康检查、查询失败提示和前端可用性必须完整。

## 已确认边界
- 当前以 Prometheus 指标与 ClickHouse 日志为主要数据源。
- 不恢复 Jaeger、SkyWalking、Tempo、Zipkin、阿里云 SLS、Grafana 嵌入/跳转/配置能力。
- 不建设客户系统反向写入告警中心的 Webhook；外部事件通过事件中心接入。
- 日志中的 trace_id、span_id、request_id 仅作为检索字段，不代表平台提供链路追踪。
- RBAC 必须以后端校验为准；前端隐藏不是安全控制。

## 工作方式
- 先阅读当前实现、测试和相关设计文档，再判断问题；不依据文件名或旧设计臆测功能已存在。
- 面对模糊需求，先输出：现状、问题、2—3 个方案、推荐方案、影响范围和验收标准；得到确认后实现。
- 面对明确需求，直接实施，但先说明改动范围和验证计划。
- 复杂或多文件编码工作委派 Codex；Hermes 负责拆解、上下文传递、架构决策、结果审查与集成验证。
- 不做无关重构；不以模拟数据掩盖数据源、接口或流程缺失。
- 不编造测试、构建、接口、数据源或部署结果。

## 完成标准
每项功能完成必须包含：
- 后端 API、数据模型、权限与异常处理（如适用）。
- 前端状态、空态、加载态、失败提示和权限体验（如适用）。
- 相关自动化测试；后端运行相关测试，前端运行构建。
- 关键用户路径的人工验证说明。
- 必要时同步更新设计文档和用户文档。

## 安全与授权
- 不提交密钥、真实凭证、kubeconfig、SSH 私钥或生产配置。
- 不未经明确授权执行生产部署、删除数据、重置数据库、修改线上 Kubernetes 资源或执行不可逆操作。
- 涉及数据迁移、权限模型、告警语义或大范围架构调整时，先说明兼容性风险和回滚方式。

---

# AI 调度体系（内部参考）

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                    Hermes Agent (调度中心)                    │
│  - 多模型路由: stepfun / zen / sail-cloud / agnes / openrouter│
│  - 持久化记忆: 跨会话记忆 + Skill 提炼                        │
│  - 子代理委派: delegate_task 并行调度                         │
└──────────┬──────────────────────────────┬───────────────────┘
           │                              │
           ▼                              ▼
┌─────────────────────┐      ┌──────────────────────────┐
│   Codex CLI (写代码)  │      │   724AI 中转 (gpt-5.6-terra) │
│   - 功能开发          │      │   Codex 桌面端默认模型     │
│   - 重构             │      │                          │
│   - Bug 修复          │      │                          │
└─────────────────────┘      └──────────────────────────┘
```

## 模型回退配置（已生效）

在 `~/.hermes/config.yaml` 中配置了完整的混合模型群组，当主模型配额用尽时自动切换到下一个：

```yaml
model:
  default: step-3.5-flash
  provider: custom:stepfun
  groups:
    - provider: custom:stepfun      # StepFun (主供应商)
      models:
        - step-3.5-flash
        - step-3.7-flash
        - step-3.5-flash-2603
    - provider: custom:zen          # Zen Free (opencode.ai)
      models:
        - deepseek-v4-flash-free
    - provider: custom:sail-cloud  # Sail Cloud
      models:
        - Qwen3.6-35B-A3B
    - provider: custom:apihub.agnes-ai.com  # AGNES
      models:
        - agnes-2.0-flash
    - provider: openrouter          # OpenRouter (13个免费模型)
      models:
        - cohere/north-mini-code:free
        - tencent/hy3:free
        - google/gemma-4-26b-a4b-it:free
        - nvidia/nemotron-3-ultra-550b-a55b:free
        - nvidia/nemotron-3-super-120b-a12b:free
        - nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
        - nvidia/nemotron-nano-9b-v2:free
        - nvidia/nemotron-3.5-content-safety:free
        - nvidia/nemotron-3-nano-30b-a3b:free
        - openai/gpt-oss-120b:free
        - openai/gpt-oss-20b:free
        - poolside/laguna-m.1:free
        - poolside/laguna-xs-2.1:free
```

回退优先级: StepFun → Zen → Sail Cloud → AGNES → OpenRouter

## Codex CLI 配置

- **已安装**: Codex CLI v0.144.1
- **登录方式**: `codex login --with-api-key`（724AI 中转站密钥 `sk-IJFM...cNi5`）
- **默认模型**: `gpt-5.6-terra`（724AI 中转站）
- **端点**: `https://api.724ai.org/v1`
- **在项目目录下使用**: `cd /c/Users/zhang/Desktop/百度/Agent/xing-cloud-main/xing-cloud-main && codex`
- **桌面端**: 需在模型选择器中手动选 `gpt-5.6-terra`

## 多代理协作模式

### 典型工作流

#### 场景 1: 新功能开发
1. **Hermes** 分析需求，拆解任务
2. **Hermes** 使用 `delegate_task` 并行派发多个 Codex 实例
3. 每个 Codex 负责一个模块的开发
4. **Hermes** 整合结果，运行测试，提交 PR

#### 场景 2: 大规模重构
1. **Hermes** 制定重构计划
2. **Hermes** 使用 `delegate_task` 按模块并行派发给 Codex
3. **Hermes** 协调冲突，统一代码风格
4. **Hermes** 运行完整测试套件

#### 场景 3: 问题排查
1. **Hermes** 初步分析日志和代码
2. 根因确认后，**Codex** 实施修复
3. **Hermes** 验证修复，更新相关文档

## 项目工作目录

```
C:/Users/zhang/Desktop/百度/Agent/xing-cloud-main/xing-cloud-main/
├── backend/           # Django 后端
├── frontend/          # Vue 3 前端
├── k8s/              # Kubernetes 部署配置
├── docs/             # 项目文档
├── tools/            # 开发工具脚本
└── .runlogs/         # 运行时日志
```

## 开发命令速查

### 后端
```bash
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
python -m daphne -b 0.0.0.0 -p 8000 xing_cloud.asgi:application
```

### 前端
```bash
cd frontend
npm install
npm run dev
```

### 测试
```bash
cd backend && python manage.py test
cd frontend && npm run build
```

### Docker
```bash
docker compose up -d --build
```
