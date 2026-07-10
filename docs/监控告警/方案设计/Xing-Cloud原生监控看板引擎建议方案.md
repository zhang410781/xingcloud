# Xing-Cloud 看板引擎 — 建设方案建议

## 1. 背景

当前 Xing-Cloud 的原生看板（`/observability/dashboards`）是**后端硬编码**的，3 类看板（服务器/K8S/日志）的 PromQL/SQL 写在 `observability_views.py` 中，用户无法创建、编辑或自定义看板。参考 Nightingale 和 Grafana 的看板引擎设计，建议建设一套**JSON 驱动的轻量看板引擎**。

---

## 2. 数据模型设计

```python
# backend/ops/models.py

class Dashboard(models.Model):
    """看板"""
    title = models.CharField(max_length=255, verbose_name="看板标题")
    description = models.TextField(blank=True, verbose_name="描述")
    tags = models.JSONField(default=list, verbose_name="标签")
    busi_group = models.ForeignKey(
        'BusiGroup', null=True, blank=True,
        on_delete=models.SET_NULL, verbose_name="业务组"
    )

    # 布局：存储面板排列方式 (rows/columns 坐标)
    # [
    #   {"key": "panel_cpu", "w": 6, "h": 4, "x": 0, "y": 0},
    #   {"key": "panel_mem", "w": 6, "h": 4, "x": 6, "y": 0}
    # ]
    layout = models.JSONField(default=list, verbose_name="面板布局")

    builtin = models.BooleanField(default=False, verbose_name="内置看板")
    enabled = models.BooleanField(default=True, verbose_name="启用")

    created_by = models.ForeignKey('User', null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = "看板"
        permissions = [
            ('manage_dashboard', '管理看板'),
        ]


class DashboardPanel(models.Model):
    """看板面板"""
    CHART_TYPES = [
        ('timeseries', '时序图'),
        ('stat', '统计值'),
        ('bar', '柱状图'),
        ('table', '表格'),
        ('pie', '饼图'),
        ('logs', '日志列表'),
    ]
    DATASOURCE_CATEGORIES = [
        ('prometheus', 'Prometheus'),
        ('zabbix', 'Zabbix'),
        ('loki', 'Loki'),
        ('elasticsearch', 'ELK'),
        ('clickhouse', 'ClickHouse'),
    ]

    key = models.CharField(max_length=64, db_index=True, verbose_name="面板标识")
    title = models.CharField(max_length=255, verbose_name="面板标题")
    description = models.TextField(blank=True)

    chart_type = models.CharField(max_length=32, choices=CHART_TYPES)
    datasource_category = models.CharField(
        max_length=32, choices=DATASOURCE_CATEGORIES
    )
    # 关联 MetricDataSource 或 LogDataSource
    datasource_id = models.IntegerField(verbose_name="数据源 ID")

    # 查询配置 — 支持多查询（类似 Grafana 的 targets）
    # [
    #   {"expr": "100 - avg(rate(...))", "legend_format": "{{instance}}"},
    # ]
    targets = models.JSONField(default=list, verbose_name="查询目标")

    # 可视化配置
    # {"unit": "percent", "min": 0, "max": 100, "colors": ["#FF0000"], "stack": false}
    options = models.JSONField(default=dict, verbose_name="可视化选项")

    dashboard = models.ForeignKey(
        Dashboard, related_name='panels',
        on_delete=models.CASCADE, verbose_name="所属看板"
    )
    sort_weight = models.IntegerField(default=0, verbose_name="排序")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_weight', 'id']
        verbose_name = "看板面板"
        unique_together = [('dashboard', 'key')]
```

---

## 3. JSON 导入导出格式

### 导出格式

```json
{
  "version": "1.0",
  "title": "Linux 主机监控",
  "description": "预置 Linux 主机监控看板",
  "tags": ["linux", "host", "builtin"],
  "layout": [
    {"key": "cpu_usage", "w": 6, "h": 4, "x": 0, "y": 0},
    {"key": "mem_usage", "w": 6, "h": 4, "x": 6, "y": 0},
    {"key": "disk_top5", "w": 6, "h": 3, "x": 0, "y": 4},
    {"key": "net_traffic", "w": 6, "h": 3, "x": 6, "y": 4}
  ],
  "panels": [
    {
      "key": "cpu_usage",
      "title": "CPU 使用率",
      "chart_type": "timeseries",
      "datasource_category": "prometheus",
      "targets": [
        {
          "expr": "100 - avg by(instance)(rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100",
          "legend_format": "{{instance}}"
        }
      ],
      "options": {"unit": "percent", "min": 0, "max": 100}
    },
    {
      "key": "mem_usage",
      "title": "内存使用率",
      "chart_type": "stat",
      "datasource_category": "prometheus",
      "targets": [
        {
          "expr": "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100"
        }
      ],
      "options": {"unit": "percent"}
    },
    {
      "key": "disk_top5",
      "title": "磁盘使用率 TOP5",
      "chart_type": "bar",
      "datasource_category": "prometheus",
      "targets": [
        {
          "expr": "topk(5, 100 - (node_filesystem_avail_bytes{!~\"tmpfs|devtmpfs\"} / node_filesystem_size_bytes{!~\"tmpfs|devtmpfs\"}) * 100)"
        }
      ],
      "options": {"unit": "percent", "orientation": "horizontal"}
    },
    {
      "key": "net_traffic",
      "title": "网络流量",
      "chart_type": "timeseries",
      "datasource_category": "prometheus",
      "targets": [
        {
          "expr": "rate(node_network_receive_bytes_total[5m])",
          "legend_format": "{{device}} RX"
        },
        {
          "expr": "rate(node_network_transmit_bytes_total[5m])",
          "legend_format": "{{device}} TX"
        }
      ],
      "options": {"unit": "bytes"}
    }
  ]
}
```

### 导入逻辑

```python
# backend/ops/views/dashboard_views.py
from django.db import transaction

class DashboardImportView(APIView):

    def post(self, request):
        serializer = DashboardImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data['json_data']
        busi_group = serializer.validated_data.get('busi_group')

        with transaction.atomic():
            dashboard = Dashboard.objects.create(
                title=data['title'],
                description=data.get('description', ''),
                tags=data.get('tags', []),
                layout=data.get('layout', []),
                builtin=False,
                busi_group=busi_group,
                created_by=request.user,
            )

            for panel_data in data.get('panels', []):
                DashboardPanel.objects.create(
                    dashboard=dashboard,
                    key=panel_data['key'],
                    title=panel_data['title'],
                    chart_type=panel_data['chart_type'],
                    datasource_category=panel_data['datasource_category'],
                    datasource_id=serializer.validated_data['datasource_id'],
                    targets=panel_data['targets'],
                    options=panel_data.get('options', {}),
                )

            # 如导入时无 layout，自动计算
            if not dashboard.layout:
                dashboard.layout = _auto_layout(dashboard.panels.count())
                dashboard.save(update_fields=['layout'])

        return Response(
            DashboardDetailSerializer(dashboard).data,
            status=status.HTTP_201_CREATED
        )


def _auto_layout(panel_count: int) -> list:
    """无 layout 时自动生成 2 列布局"""
    cols = 2
    positions = []
    for i in range(panel_count):
        positions.append({
            "key": f"panel_{i}",
            "w": 12 // cols,
            "h": 4,
            "x": (i % cols) * (12 // cols),
            "y": (i // cols) * 4,
        })
    return positions
```

---

## 4. 看板查询接口

核心接口：接收看板 ID + 时间范围，遍历所有面板依次查询数据源并返回。

```python
class DashboardQueryView(APIView):
    """执行看板所有面板的查询"""

    def post(self, request, pk):
        try:
            dashboard = Dashboard.objects.get(pk=pk, enabled=True)
        except Dashboard.DoesNotExist:
            return Response({"error": "看板不存在"}, status=404)

        serializer = DashboardQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        start = serializer.validated_data['start_ms']
        end = serializer.validated_data['end_ms']
        step = serializer.validated_data.get('step', 60)

        results = []
        for panel in dashboard.panels.all().order_by('sort_weight'):
            result = self._execute_panel(panel, start, end, step)
            results.append(result)

        return Response({
            "dashboard": DashboardBriefSerializer(dashboard).data,
            "panels": results,
            "time_range": {"start": start, "end": end},
        })

    def _execute_panel(self, panel, start, end, step):
        """执行单个面板的查询"""
        if panel.datasource_category == 'prometheus':
            return self._query_prometheus(panel, start, end, step)
        elif panel.datasource_category == 'clickhouse':
            return self._query_clickhouse(panel, start, end)
        # ... 其他数据源

    def _query_prometheus(self, panel, start, end, step):
        """对 panel 的每个 target 执行 PromQL 查询"""
        series = []
        for target in panel.targets:
            expr = target.get('expr', '')
            # 调用已有 methods_promql_query 逻辑
            result = prometheus_query_range(
                expr=expr, start=start, end=end, step=step
            )
            series.append({
                "expr": expr,
                "legend_format": target.get('legend_format', ''),
                "data": result,
            })
        return {
            "key": panel.key,
            "title": panel.title,
            "chart_type": panel.chart_type,
            "options": panel.options,
            "status": "ok",
            "series": series,
        }
```

---

## 5. 完整 API 清单

| 功能 | 方法 | 接口 | 说明 |
|------|------|------|------|
| 看板列表 | GET | `/api/dashboards/` | 支持按 busi_group/tags 过滤 |
| 看板创建 | POST | `/api/dashboards/` | 创建看板 |
| 看板详情 | GET | `/api/dashboards/{id}/` | 含面板列表和布局 |
| 看板更新 | PUT | `/api/dashboards/{id}/` | 更新标题/描述/布局 |
| 看板删除 | DELETE | `/api/dashboards/{id}/` | 级联删除面板 |
| 看板查询 | POST | `/api/dashboards/{id}/query/` | 执行所有面板查询 |
| 看板导出 | GET | `/api/dashboards/{id}/export/` | 导出为标准 JSON |
| 看板导入 | POST | `/api/dashboards/import/` | 从 JSON 创建看板 |
| 面板创建 | POST | `/api/dashboards/{id}/panels/` | 添加面板 |
| 面板更新 | PUT | `/api/dashboards/{id}/panels/{key}/` | 修改面板配置 |
| 面板删除 | DELETE | `/api/dashboards/{id}/panels/{key}/` | 删除面板 |
| 集成导入 | POST | `/api/integrations/{slug}/install/` | 一键导入集成包(含规则+看板) |

---

## 6. 前端组件设计

在现有 `NativeMonitoringDashboard.vue` + `NativeDashboardChart.vue` (ECharts) 基础上新增：

### 新增组件

```
frontend/src/views/
├── DashboardList.vue           # 看板列表页
├── DashboardViewer.vue         # 看板展示页（核心）
├── DashboardEditor.vue         # 看板编辑器（拖拽布局）
├── PanelEditor.vue             # 面板配置（PromQL/图表类型）
└── DashboardImport.vue         # JSON 导入对话框
```

### DashboardEditor.vue 交互流程

```
用户点击"新建看板" → 输入标题/描述/数据源
  → 进入编辑器页面
    → 左侧面板库 (可选图表类型)
    → 中间画布 (vue-grid-layout 拖拽)
    → 右侧配置 (选中面板的 PromQL/选项)
  → 保存 → POST /api/dashboards/
```

### 渲染复用

`DashboardViewer.vue` 可**直接复用** `NativeDashboardChart.vue` 的 ECharts 渲染逻辑：

```vue
<template>
  <grid-layout :layout="dashboard.layout">
    <grid-item v-for="panel in panels" :key="panel.key">
      <NativeDashboardChart
        :chartType="panel.chart_type"
        :series="panel.queryResult.series"
        :options="panel.options"
      />
    </grid-item>
  </grid-layout>
</template>
```

### 依赖

推荐使用 `vue-grid-layout` (或 `gridstack.js`) 实现拖拽布局。

---

## 7. 集成包的看板 JSON 示例

### Linux 主机看板 (`integrations/linux/dashboard.json`)

```json
{
  "title": "Linux 主机监控",
  "description": "基于 node_exporter 的 Linux 主机资源监控看板",
  "tags": ["linux", "host", "builtin"],
  "panels": [
    {
      "key": "cpu_usage",
      "title": "CPU 使用率",
      "chart_type": "timeseries",
      "datasource_category": "prometheus",
      "targets": [
        {"expr": "100 - avg by(instance)(rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100",
         "legend_format": "{{instance}}"}
      ],
      "options": {"unit": "percent"}
    },
    {
      "key": "mem_usage",
      "title": "内存使用率",
      "chart_type": "timeseries",
      "datasource_category": "prometheus",
      "targets": [
        {"expr": "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100",
         "legend_format": "{{instance}}"}
      ],
      "options": {"unit": "percent"}
    },
    {
      "key": "disk_top5",
      "title": "磁盘使用率 TOP5",
      "chart_type": "bar",
      "datasource_category": "prometheus",
      "targets": [
        {"expr": "topk(5, 100 - (node_filesystem_avail_bytes / node_filesystem_size_bytes) * 100)",
         "legend_format": "{{mountpoint}}"}
      ],
      "options": {"unit": "percent"}
    },
    {
      "key": "load",
      "title": "系统负载",
      "chart_type": "timeseries",
      "datasource_category": "prometheus",
      "targets": [
        {"expr": "node_load1", "legend_format": "{{instance}} load1"},
        {"expr": "node_load5", "legend_format": "{{instance}} load5"},
        {"expr": "node_load15", "legend_format": "{{instance}} load15"}
      ],
      "options": {}
    },
    {
      "key": "net_traffic",
      "title": "网络流量",
      "chart_type": "timeseries",
      "datasource_category": "prometheus",
      "targets": [
        {"expr": "rate(node_network_receive_bytes_total[5m])", "legend_format": "{{device}} RX"},
        {"expr": "rate(node_network_transmit_bytes_total[5m])", "legend_format": "{{device}} TX"}
      ],
      "options": {"unit": "Bps"}
    }
  ]
}
```

### K8S 集群看板 (`integrations/kubernetes/dashboard.json`)

```json
{
  "title": "K8S 集群监控",
  "description": "基于 kube-state-metrics 的 K8S 集群监控看板",
  "tags": ["kubernetes", "k8s", "cluster", "builtin"],
  "panels": [
    {
      "key": "node_status",
      "title": "节点状态",
      "chart_type": "stat",
      "datasource_category": "prometheus",
      "targets": [
        {"expr": "count(kube_node_status_condition{condition=\"Ready\",status=\"true\"})",
         "legend_format": "Ready"},
        {"expr": "count(kube_node_status_condition{condition=\"Ready\",status=\"false\"})",
         "legend_format": "NotReady"}
      ],
      "options": {}
    },
    {
      "key": "pod_status",
      "title": "Pod 状态分布",
      "chart_type": "pie",
      "datasource_category": "prometheus",
      "targets": [
        {"expr": "count by (phase) (kube_pod_status_phase)", "legend_format": "{{phase}}"}
      ],
      "options": {}
    },
    {
      "key": "namespace_cpu",
      "title": "命名空间 CPU 使用 TOP10",
      "chart_type": "bar",
      "datasource_category": "prometheus",
      "targets": [
        {"expr": "topk(10, sum by (namespace) (rate(container_cpu_usage_seconds_total{container!=\"\"}[5m])))",
         "legend_format": "{{namespace}}"}
      ],
      "options": {"unit": "cores"}
    },
    {
      "key": "namespace_mem",
      "title": "命名空间内存使用 TOP10",
      "chart_type": "bar",
      "datasource_category": "prometheus",
      "targets": [
        {"expr": "topk(10, sum by (namespace) (container_memory_working_set_bytes{container!=\"\"}))",
         "legend_format": "{{namespace}}"}
      ],
      "options": {"unit": "bytes"}
    },
    {
      "key": "cluster_events",
      "title": "集群事件",
      "chart_type": "table",
      "datasource_category": "clickhouse",
      "targets": [
        {"sql": "SELECT timestamp, type, reason, object, message FROM k8s_events WHERE timestamp >= now() - INTERVAL 1 HOUR ORDER BY timestamp DESC LIMIT 50"}
      ],
      "options": {}
    }
  ]
}
```

### 日志看板 (`integrations/logs/dashboard.json`)

```json
{
  "title": "日志监控",
  "description": "多数据源日志聚合看板",
  "tags": ["logs", "builtin"],
  "panels": [
    {
      "key": "log_volume",
      "title": "日志量时序",
      "chart_type": "timeseries",
      "datasource_category": "clickhouse",
      "targets": [
        {"sql": "SELECT toStartOfInterval(timestamp, INTERVAL 1 MINUTE) AS t, count(*) AS c FROM container_logs WHERE timestamp >= now() - INTERVAL 1 HOUR GROUP BY t ORDER BY t"}
      ],
      "options": {}
    },
    {
      "key": "error_trend",
      "title": "错误日志趋势",
      "chart_type": "timeseries",
      "datasource_category": "loki",
      "targets": [
        {"expr": "sum by (level) (rate({level=\"error\"}[5m]))", "legend_format": "error"}
      ],
      "options": {}
    },
    {
      "key": "top_errors",
      "title": "Top N 错误",
      "chart_type": "table",
      "datasource_category": "elasticsearch",
      "targets": [
        {"dsl": {"size": 0, "query": {"range": {"@timestamp": {"gte": "now-1h"}}}, "aggs": {"errors": {"terms": {"field": "message.keyword", "size": 10}}}}
      ],
      "options": {}
    },
    {
      "key": "source_distribution",
      "title": "日志来源分布",
      "chart_type": "pie",
      "datasource_category": "clickhouse",
      "targets": [
        {"sql": "SELECT namespace, count(*) AS c FROM container_logs WHERE timestamp >= now() - INTERVAL 1 HOUR GROUP BY namespace ORDER BY c DESC"}
      ],
      "options": {}
    }
  ]
}
```

---

## 8. 与现有原生看板的迁移策略

1. **不保留旧前端入口** — `/observability/dashboards` 统一切换到新看板引擎，不再展示原有服务器、K8S、日志硬编码看板切换器
2. **迁移为内置 JSON 看板** — 把 `observability_views.py` 中的硬编码 PromQL/SQL 迁移到 JSON 格式，作为 `builtin=True` 的内置看板定义
3. **统一渲染路径** — 前端只通过看板定义查询接口获取面板数据，并统一复用新看板渲染组件
4. **后端兼容窗口** — 旧 `/observability/dashboards/query/` 接口可以短期保留给兼容脚本或测试，但不再作为前端入口

---

## 9. 对比 Grafana 的能力映射

| 能力 | Grafana | Xing-Cloud (目标) | 实现方式 |
|------|---------|-----------------|---------|
| JSON 导入/导出 | ✅ | ✅ | DashboardImportView / ExportView |
| 多数据源面板混合 | ✅ | ✅ | datasource_category 字段 |
| 拖拽布局 | ✅ | ✅ | vue-grid-layout |
| 变量/模板 ($var) | ✅ | ⏳ P2 | 参考 Grafana templating 设计 |
| 告警关联 | ✅ | ✅ | 已有告警体系 |
| 看板分享 (public) | ✅ | ⏳ P2 | is_public 字段 + 分享 token |
| 看板文件夹 | ✅ | ⏳ P2 | 可选，busi_group 可替代 |
| 插件生态 | ✅ | ❌ | 不追求，内置数据源即够 |
| 注解 (annotations) | ✅ | ⏳ P2 | 告警事件可渲染为看板注解 |
| 内置 PromQL 编辑器 | ✅ | ✅ 已有 | MetricsQuery.vue |

---

## 10. 实施路线

| 阶段 | 内容 | 工作量 | 依赖 |
|------|------|--------|------|
| **P0** | Dashboard + DashboardPanel 模型 + migration | 1 天 | — |
| **P0** | CRUD API + import/export + query 接口 | 2-3 天 | 模型 |
| **P0** | DashboardList.vue + DashboardViewer.vue (复用现有图表) | 2 天 | API |
| **P0** | 原生看板迁移为 builtin JSON 种子数据，旧前端入口下线 | 1 天 | DashboardViewer |
| **P1** | DashboardEditor.vue (拖拽布局) | 3-5 天 | vue-grid-layout |
| **P1** | PanelEditor.vue (PromQL 编辑 + 图表配置) | 2-3 天 | 编辑器组件 |
| **P1** | DashboardImport.vue (JSON 导入对话框) | 1 天 | import API |
| **P1** | 集成包与看板打通 (一键导入) | 1-2 天 | 集成中心 |
| **P2** | 变量/模板系统 | 3-5 天 | — |
| **P2** | 看板分享 + 注解 | 2-3 天 | — |

---

## 11. 参考代码索引

看板引擎实现时可参考以下 Nightingale 代码：

| 参考内容 | Nightingale 文件 | 参考价值 |
|---------|-----------------|---------|
| 数据源注册模式 | `datasource/datasource.go` | DatasourceType 分类 + init() 注册 |
| Prometheus 查询 | `datasource/prom/prom.go` | PromQL 查询配置结构 |
| 看板模型设计 | `models/dashboard.go` | 面板 layout + targets 存储方式 |
| 看板查询 API | `center/router/dashboard.go` | panels 遍历 → 数据源查询模式 |
| 日志看板查询 | `datasource/ck/clickhouse.go` | ClickHouse SQL 时间序列查询 |
| 集成目录结构 | `integrations/Linux/` | 预置看板 + 告警规则 + 指标采集 |

> 具体参考文件已复制到本目录 `reference-code/` 子目录中。
