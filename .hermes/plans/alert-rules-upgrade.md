# 告警规则与通知系统升级计划

> **实现方式**: 通过 Codex CLI 分步实现，Hermes 负责拆解与审查。

**目标**: 为 AlertRule 增加分类（服务器/K8S/存储/数据库），提供双阈值 UI（警告/严重级别），完善告警通知链路，连接线上 Prometheus 验证。

**已有基础**: 完整的 AlertRule/Alert/AlertNotificationChannel 等模型、alert_engine 评估器管线、Alerts.vue 前端已有规则/事件标签页。

---

## Task 1: 后端 — AlertRule 增加 category 分类

**文件**: `backend/ops/models.py`

修改:
- 在 `AlertRule` 模型新增 `CATEGORY_CHOICES` 和 `category` 字段:
  - choices: `('server', '服务器'), ('k8s', 'K8S'), ('storage', '存储'), ('database', '数据库')`
  - default 空字符串
  - 加 db_index
- 同步更新 `AlertRuleTemplate` 模型同样增加 `category` 字段
- 创建 migration: `python manage.py makemigrations ops`

**文件**: `backend/ops/serializers.py`
- `AlertRuleSerializer` 加上 `category` 字段
- `AlertRuleTemplateSerializer` 加上 `category` 字段

**文件**: `backend/ops/views.py`
- `AlertRuleViewSet` 的 `list` 增加 `?category=` 过滤参数
- 添加 `@action(detail=False, methods=['get'], url_path='by-category')` 按分类统计规则数量

---

## Task 2: 后端 — 服务器/系统默认告警规则预设

**文件**: `backend/ops/alert_rule_presets.py`

添加内置预设模板，按分类：

### 服务器 (server)
- CPU 使用率 > 80% → warning, > 90% → critical (PromQL: `100 - (avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)`)
- 内存使用率 > 80% → warning, > 90% → critical
- 磁盘使用率 > 85% → warning, > 92% → critical
- 磁盘 IO 等待 > 50% → warning
- 系统负载 5m > CPU 核心数*2 → warning

### K8S
- Pod 重启次数 > 5次/10m → warning
- Pod 状态 CrashLoopBackOff → critical
- Node 状态 NotReady → critical
- PVC 使用率 > 85% → warning, > 90% → critical

### 存储
- 存储节点 down → critical
- 存储延迟 > 50ms → warning
- 存储容量 > 85% → warning

### 数据库
- 连接数 > 80% 上限 → warning
- 复制延迟 > 30s → warning
- 慢查询 > 50/5m → warning

每个预设设置 `is_builtin=True` 和 `category`。

**文件**: `backend/ops/alert_rules.py`
- 新增 API 端点或 action: `POST /api/ops/alert-rules/apply-preset/` — 将预设模板一键转为活跃规则
- 支持用户在 UI 点击"添加预设规则"后调整阈值再保存

---

## Task 3: 后端 — 双阈值告警规则逻辑

**文件**: `backend/ops/alert_engine/evaluator.py`

目前规则有一个 `condition`（单阈值）。需要支持双阈值结构:
```json
{
  "levels": [
    {"level": "warning", "operator": ">", "threshold": 80, "duration": 300},
    {"level": "critical", "operator": ">", "threshold": 90, "duration": 120}
  ]
}
```
- 评估时按阈值从低到高检查，触发的最高级别作为告警级别
- 兼容现有单阈值 `condition` 格式

---

## Task 4: 后端 — 告警通知链完善

**文件**: `backend/ops/alerting.py`
- 检查 `dispatch_alert_batch_notifications` 函数能否正确发送多渠道（wechat/dingtalk/feishu/email）
- 添加 Webhook 通知测试端点：`POST /api/ops/notification-channels/{id}/test/`
- 确保通知日志 `AlertNotificationLog` 能记录发送结果和错误

**文件**: `backend/ops/models.py`
- 如有必要，补充通知渠道的配置字段

---

## Task 5: 前端 — 告警规则分类Tab和双阈值UI

**文件**: `frontend/src/views/Alerts.vue`

告警规则标签页增强:
1. 添加分类导航 tabs: 全部 | 服务器 | K8S | 存储 | 数据库
2. 每个规则卡片显示分类标签 badge
3. 按分类过滤

规则创建/编辑对话框增强:
1. 分类选择器 (server/k8s/storage/database)
2. 双阈值配置组:
   - 警告阈值: 运算符(>/>=/</<=), 阈值(%), 持续时间(秒)
   - 严重阈值: 运算符(>/>=/</<=), 阈值(%), 持续时间(秒)
   - 示例: CPU > 80% 持续5分 → 警告 | CPU > 90% 持续2分 → 严重
3. 从预设模板选择(一键填充阈值)
4. 指标选择器(从 Prometheus 拉取可用指标列表)

**文件**: `frontend/src/router/index.js`
- 确认告警页面路由已配置 (应已存在)

---

## Task 6: 前端 — 通知渠道管理页面

**文件**: 新增 `frontend/src/views/AlertNotificationChannels.vue`
或者集成到 Alerts.vue 的第三个标签页

功能:
1. 通知渠道列表（企业微信/钉钉/飞书/邮件）
2. 添加/编辑 Webhook URL 和 Token
3. 测试发送按钮
4. 通知规则配置：哪些告警规则触发时通知哪个渠道

---

## 验证计划

### 后端验证
1. `python manage.py test ops.tests.test_alert_rules -v 2`
2. 手动测试 API: `GET /api/ops/alert-rules/?category=server`
3. 创建双阈值规则 → 推送测试告警 → 检查通知

### 前端验证
1. `cd frontend && npm run build` 无报错
2. 在浏览器中检查分类 tab 切换
3. 创建规则: 选分类 → 填阈值 → 保存 → 列表显示

### 端到端验证（线上服务器）
1. SSH 登录 10.132.46.52
2. 拉取代码，构建前端
3. 重启 Django 服务
4. 配置 Prometheus 数据源指向 `http://10.132.46.52:30003/`
5. 创建一条 CPU > 1% 告警规则（快速触发）
6. 等待 engine 评估 → 确认告警产生
7. 配置通知渠道 → 确认通知送达

---

## 注意事项
- 不破坏现有单阈值 `condition` 兼容性
- 不引入新的依赖
- 所有 API 变更向后兼容
- 通知渠道 Webhook URL 存储在服务端，不在前端明文暴露
- 线上验证前先在本地 migrations 测试
