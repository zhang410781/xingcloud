<template>
  <div class="monitor-dashboard" :class="{ 'is-log-dashboard': scope === 'logs' }">
    <header class="dashboard-header">
      <div>
        <div class="eyebrow">可观测 / 监控看板</div>
        <h1>{{ scopeLabel }}</h1>
        <p>{{ activeDefinition?.description || '统一查看基础设施与应用运行状态' }}</p>
      </div>
      <div class="header-actions">
        <span class="live-state"><i />{{ loadingDashboard ? '查询中' : '实时数据' }}</span>
        <el-button size="small" :loading="loadingDashboard" @click="loadDashboard">
          <el-icon><RefreshRight /></el-icon>刷新
        </el-button>
      </div>
    </header>

    <ObservabilityRouteTabs group="observability" />

    <nav class="scope-switch" role="tablist" aria-label="监控对象">
      <button v-for="item in scopeItems" :key="item.key" type="button" :class="{ active: scope === item.key }" @click="changeScope(item.key)">
        <el-icon><component :is="item.icon" /></el-icon>{{ item.label }}
      </button>
    </nav>

    <section class="monitor-toolbar">
      <div v-if="scope !== 'logs'" class="toolbar-field">
        <span>指标数据源</span>
        <div class="bound-resource">{{ boundMetricName || '当前上下文未绑定' }}</div>
      </div>
      <div v-else class="toolbar-field">
        <span>日志数据源</span>
        <div class="bound-resource">{{ boundLogName || '当前上下文未绑定' }}</div>
      </div>
      <div v-if="scope === 'logs'" class="toolbar-field">
        <span>日志集合 / 索引</span>
        <el-input v-model="logSourceName" size="small" placeholder="使用默认集合或索引模式" clearable />
      </div>
      <div v-if="scope === 'k8s'" class="toolbar-field">
        <span>命名空间</span>
        <el-select v-model="namespaceFilter" size="small" clearable filterable placeholder="全部命名空间">
          <el-option v-for="item in namespaceOptions" :key="item" :label="item" :value="item" />
        </el-select>
      </div>
      <div v-if="scope === 'k8s' || scope === 'server'" class="toolbar-field">
        <span>{{ scope === 'k8s' ? '节点' : '服务器节点' }}</span>
        <el-select v-model="nodeFilter" size="small" clearable filterable placeholder="全部节点">
          <el-option v-for="item in nodeOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </div>
      <div v-if="scope === 'database' || scope === 'middleware'" class="toolbar-field">
        <span>{{ scope === 'database' ? '数据库类型' : '中间件类型' }}</span>
        <el-select v-model="subtype" size="small" @change="selectSubtype">
          <el-option v-for="item in subtypeItems" :key="item.key" :label="item.label" :value="item.key" />
        </el-select>
      </div>
      <div class="toolbar-field toolbar-field--time">
        <span>时间范围</span>
        <el-segmented v-model="timeRangeKey" size="small" :options="timeRangeOptions" />
      </div>
      <el-button type="primary" size="small" :loading="loadingDashboard" @click="loadDashboard">查询</el-button>
    </section>

    <section v-if="!loadingDashboard && !panels.length" class="empty-dashboard">
      <el-icon><DataAnalysis /></el-icon>
      <strong>暂无可展示的面板数据</strong>
      <span>{{ emptyHint }}</span>
    </section>

    <main v-else class="dashboard-canvas">
      <article
        v-for="panel in panels"
        :key="panel.key"
        class="dashboard-panel"
        :class="[`panel-type-${panel.type}`, panel.status !== 'ok' ? 'panel-has-error' : '']"
        :style="panelStyle(panel)"
      >
        <div class="panel-heading">
          <div><h2>{{ panelTitle(panel) }}</h2><p>{{ panelSubtitle(panel) }}</p></div>
          <div class="panel-tools"><span v-if="panel.status !== 'ok'" class="panel-status">{{ panel.error || '数据异常' }}</span><el-button text size="small" title="刷新面板" @click="loadDashboard"><el-icon><RefreshRight /></el-icon></el-button></div>
        </div>
        <div v-if="panel.type === 'stat'" class="stat-value" :class="panelTone(panel)">{{ formatPanelValue(panel) }}<small>{{ unitLabel(panel) }}</small></div>
        <NativeDashboardChart v-else-if="!['table', 'logs'].includes(panel.type)" :panel="panel" :dark="false" />
        <div v-if="['table', 'logs'].includes(panel.type)" class="panel-table-wrap">
          <table v-if="tableRows(panel).length">
            <thead><tr><th v-for="column in tableColumns(panel)" :key="column">{{ column }}</th></tr></thead>
            <tbody><tr v-for="(row, index) in tableRows(panel).slice(0, 50)" :key="index" @dblclick="openLogRow(row)"><td v-for="column in tableColumns(panel)" :key="column" :class="cellTone(row[column], column)">{{ formatCell(row[column], column, panel) }}</td></tr></tbody>
          </table>
          <div v-else class="panel-empty">暂无明细数据</div>
        </div>
      </article>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { Connection, DataAnalysis, DataBoard, Monitor, RefreshRight, Search, SetUp } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import ObservabilityRouteTabs from '@/components/observability/ObservabilityRouteTabs.vue'
import NativeDashboardChart from '@/components/observability/NativeDashboardChart.vue'
import { getDashboardDefinitions, getLogDataSources, getMetricDataSources, queryDashboardDefinition, queryMetrics } from '@/api/modules/ops'
import { useBusinessContextStore } from '@/stores/businessContext'

const router = useRouter()
const businessContextStore = useBusinessContextStore()
const { currentContext, currentContextId } = storeToRefs(businessContextStore)
const scope = ref('k8s')
const subtype = ref('mysql')
const definitions = ref([])
const payload = ref({})
const metricDataSources = ref([])
const logDataSources = ref([])
const selectedMetricId = ref('')
const selectedLogId = ref('')
const logSourceName = ref('')
const namespaceFilter = ref('')
const namespaceOptions = ref([])
const nodeFilter = ref('')
const nodeOptions = ref([])
const activeDefinitionId = ref('')
const loadingDashboard = ref(false)
let dashboardRequestVersion = 0
let dashboardMounted = false
const timeRangeKey = ref('5m')
const timeRangeOptions = [{ label: '5m', value: '5m' }, { label: '15m', value: '15m' }, { label: '1h', value: '1h' }, { label: '6h', value: '6h' }]
const scopeItems = [
  { key: 'k8s', label: 'K8S 集群', icon: Connection },
  { key: 'server', label: '服务器', icon: Monitor },
  { key: 'database', label: '数据库', icon: DataBoard },
  { key: 'middleware', label: '中间件', icon: SetUp },
  { key: 'logs', label: '日志', icon: Search },
]
const subtypeItems = computed(() => scope.value === 'database' ? [{ key: 'mysql', label: 'MySQL' }, { key: 'postgresql', label: 'PostgreSQL' }] : [{ key: 'redis', label: 'Redis' }, { key: 'kafka', label: 'Kafka' }])
const activeDefinition = computed(() => definitions.value.find((item) => String(item.id) === String(activeDefinitionId.value)))
const panels = computed(() => Array.isArray(payload.value.panels) ? payload.value.panels : [])
const scopeLabel = computed(() => ({ k8s: 'Kubernetes 集群监控', server: 'Linux 服务器监控', database: `${subtype.value === 'postgresql' ? 'PostgreSQL' : 'MySQL'} 数据库监控`, middleware: `${subtype.value === 'kafka' ? 'Kafka' : 'Redis'} 中间件监控`, logs: '日志分析看板' }[scope.value]))
const boundMetricName = computed(() => currentContext.value?.metric_datasource_name || metricDataSources.value.find(item => String(item.id) === String(selectedMetricId.value))?.name || '')
const boundLogName = computed(() => {
  const source = logDataSources.value.find(item => String(item.id) === String(selectedLogId.value))
  const name = currentContext.value?.log_datasource_name || source?.name || ''
  return name && source ? `${name} · ${providerLabel(source.provider)}` : name
})
const emptyHint = computed(() => {
  if (!currentContext.value) return '请先在顶部选择业务上下文'
  if (scope.value === 'logs' && !selectedLogId.value) return '当前业务上下文未绑定日志数据源'
  if (scope.value !== 'logs' && !selectedMetricId.value) return '当前业务上下文未绑定指标数据源'
  return '请检查时间范围或筛选条件'
})

function listOf(response) { return Array.isArray(response) ? response : (response?.results || []) }
function providerLabel(provider) { return { elk: 'Elasticsearch', clickhouse: 'ClickHouse' }[provider] || provider || '日志' }
function hasExplicitGrid(panel) {
  const grid = panel.grid || panel.options?.grid || {}
  return Number(grid.w) > 0
}
function panelStyle(panel) {
  const grid = panel.grid || panel.options?.grid || {}
  if (grid.w) return { '--grid-x': grid.x || 0, '--grid-y': grid.y || 0, '--grid-w': grid.w, '--grid-h': grid.h || 6 }
  const fallbackPanels = panels.value.filter((item) => !hasExplicitGrid(item))
  const stats = fallbackPanels.filter((item) => item.type === 'stat')
  const content = fallbackPanels.filter((item) => item.type !== 'stat')
  const statColumns = Math.max(1, Math.min(stats.length, 6))
  const statWidth = 24 / statColumns
  const statRows = Math.ceil(stats.length / statColumns)
  if (panel.type === 'stat') {
    const statIndex = Math.max(0, stats.indexOf(panel))
    return { '--grid-x': (statIndex % statColumns) * statWidth, '--grid-y': Math.floor(statIndex / statColumns) * 4, '--grid-w': statWidth, '--grid-h': 4 }
  }
  const contentIndex = Math.max(0, content.indexOf(panel))
  return { '--grid-x': (contentIndex % 2) * 12, '--grid-y': statRows * 4 + Math.floor(contentIndex / 2) * 8, '--grid-w': 12, '--grid-h': 8 }
}
function panelTitle(panel) { return panel.title || panel.key || '监控面板' }
function panelSubtitle(panel) { if (panel.error) return panel.error; if (panel.type === 'stat') return '当前值'; if (panel.type === 'table' || panel.type === 'logs') return '按当前筛选条件展示'; return unitLabel(panel) || '趋势与分布' }
function panelTone(panel) { const value = Number(panel.data?.value); const isPercent = ['percent', '%'].includes(panel.unit); if (panel.status !== 'ok') return 'muted'; if (isPercent && value >= 90) return 'danger'; if (isPercent && value >= 75) return 'warning'; return 'normal' }
function unitLabel(panel) { return { short: '', percent: '%', '%': '%', cores: '核', bytes: '字节', Bps: '', 'B/s': '', pps: '包/秒', reqps: '次/秒', 'req/s': '次/秒', qps: '次/秒', tps: '次/秒', logs: '条', services: '个', pods: '个', nodes: '台' }[panel.unit] ?? panel.unit ?? '' }
function formatByteRate(value) { if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MiB/s`; if (value >= 1024) return `${(value / 1024).toFixed(1)} KiB/s`; return `${value.toFixed(1)} B/s` }
function formatPanelValue(panel) { const value = Number(panel.data?.value); if (!Number.isFinite(value) || panel.status !== 'ok') return '--'; if (/-up$/.test(panel.key || '')) return value >= 1 ? '正常' : '异常'; if (['Bps', 'B/s'].includes(panel.unit)) return formatByteRate(value); return value.toLocaleString('zh-CN', { maximumFractionDigits: panel.decimals ?? 1 }) }
function tableRows(panel) { return Array.isArray(panel.data?.rows) ? panel.data.rows : [] }
function tableColumns(panel) { const row = tableRows(panel).find((item) => item && typeof item === 'object'); return row ? Object.keys(row).filter((key) => !key.startsWith('__')).slice(0, 8) : ['name', 'value'] }
function formatBytes(value) { const number = Number(value); if (!Number.isFinite(number)) return '--'; if (number >= 1024 ** 3) return `${(number / 1024 ** 3).toFixed(1)} GiB`; if (number >= 1024 ** 2) return `${(number / 1024 ** 2).toFixed(1)} MiB`; if (number >= 1024) return `${(number / 1024).toFixed(1)} KiB`; return `${number.toFixed(0)} B` }
function formatDuration(value) { const seconds = Number(value); if (!Number.isFinite(seconds)) return '--'; const days = Math.floor(seconds / 86400); const hours = Math.floor((seconds % 86400) / 3600); return days ? `${days}天 ${hours}小时` : `${hours}小时` }
function formatCell(value, column, panel) { if (value === null || value === undefined || value === '') return '--'; if (column === 'Ready' || column === '状态') return Number(value) >= 1 ? '正常' : '异常'; if (/内存|磁盘|根盘/.test(column) && !/使用率/.test(column) && typeof value === 'number') return formatBytes(value); if (/运行秒数/.test(column)) return formatDuration(value); if (/使用率|错误率/.test(column) && Number.isFinite(Number(value))) return `${Number(value).toFixed(1)}%`; if (typeof value === 'number') return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }); return String(value) }
function cellTone(value, column) { const n = Number(value); if ((column === 'Ready' || column === '状态') && Number.isFinite(n)) return n >= 1 ? 'cell-success' : 'cell-danger'; if (/使用率|错误率/.test(column) && Number.isFinite(n)) return n >= 90 ? 'cell-danger' : n >= 75 ? 'cell-warning' : ''; return '' }
function timeRange() { const minutes = { '5m': 5, '15m': 15, '1h': 60, '6h': 360 }[timeRangeKey.value] || 5; const end = Date.now(); return [end - minutes * 60 * 1000, end] }
function selectedDefinition() { const names = { k8s: 'K8S Cluster Health', server: 'Linux Server Resources', database: subtype.value === 'postgresql' ? 'PostgreSQL Overview' : 'MySQL Overview', middleware: subtype.value === 'kafka' ? 'Kafka Overview' : 'Redis Overview', logs: 'Observability Logs Overview' }; return definitions.value.find((item) => item.title === names[scope.value]) || definitions.value.find((item) => (item.tags || []).includes(scope.value)) || definitions.value[0] }
function refreshDefinition() { activeDefinitionId.value = selectedDefinition()?.id || '' }
async function changeScope(value) { dashboardRequestVersion += 1; payload.value = {}; scope.value = value; if (value === 'database') subtype.value = 'mysql'; if (value === 'middleware') subtype.value = 'redis'; namespaceFilter.value = ''; nodeFilter.value = ''; refreshDefinition(); if (value === 'k8s' || value === 'server') await loadFilterOptions(); await loadDashboard() }
async function selectSubtype() { refreshDefinition(); await loadDashboard() }
async function loadFilterOptions() {
  if (!selectedMetricId.value) return
  const [nodes, namespaces] = await Promise.allSettled([
    queryMetrics({ query: scope.value === 'k8s' ? 'kube_node_info' : 'node_uname_info', metric_datasource_id: selectedMetricId.value }),
    queryMetrics({ query: 'kube_namespace_labels', metric_datasource_id: selectedMetricId.value }),
  ])
  if (nodes.status === 'fulfilled') { const unique = new Map(); for (const item of nodes.value?.result || []) { const metric = item.metric || {}; const value = String(scope.value === 'k8s' ? metric.node : (metric.instance || metric.nodename) || '').trim(); if (value) unique.set(value, metric.nodename || metric.node || value) } nodeOptions.value = Array.from(unique, ([value, label]) => ({ value, label })) }
  if (namespaces.status === 'fulfilled') namespaceOptions.value = [...new Set((namespaces.value?.result || []).map((item) => String(item.metric?.namespace || '').trim()).filter(Boolean))].sort()
}
async function loadSources() {
  const [metrics, logs] = await Promise.allSettled([getMetricDataSources({ is_enabled: true }, { skipErrorMessage: true }), getLogDataSources({ is_enabled: true }, { skipErrorMessage: true })])
  metricDataSources.value = metrics.status === 'fulfilled' ? listOf(metrics.value) : []
  logDataSources.value = logs.status === 'fulfilled' ? listOf(logs.value).filter((item) => ['elk', 'clickhouse'].includes(item.provider)) : []
  selectedMetricId.value = currentContext.value?.metric_datasource || ''
  selectedLogId.value = currentContext.value?.log_datasource || ''
  await loadFilterOptions()
}
async function loadDashboard() {
  if (!activeDefinitionId.value) return
  if ((scope.value === 'logs' && !selectedLogId.value) || (scope.value !== 'logs' && !selectedMetricId.value)) {
    payload.value = {}
    return
  }
  const requestVersion = ++dashboardRequestVersion
  loadingDashboard.value = true
  try {
    const [start_ms, end_ms] = timeRange()
    const response = await queryDashboardDefinition(activeDefinitionId.value, { start_ms, end_ms, step: 30, metric_datasource_id: selectedMetricId.value || undefined, log_datasource_id: selectedLogId.value || undefined, source: logSourceName.value || undefined, namespace: namespaceFilter.value ? [namespaceFilter.value] : [], node: nodeFilter.value ? [nodeFilter.value] : [] }, { timeout: 60000 })
    if (requestVersion === dashboardRequestVersion) payload.value = response
  } catch (error) { if (requestVersion === dashboardRequestVersion) { payload.value = {}; ElMessage.warning(error.response?.data?.detail || '暂时无法读取看板数据') } } finally { if (requestVersion === dashboardRequestVersion) loadingDashboard.value = false }
}
function openLogRow(row) { if (scope.value !== 'logs') return; router.push({ path: '/observability/logs', query: { datasource: selectedLogId.value || '', q: row.message || '', from: timeRange()[0], to: timeRange()[1] } }) }

async function applyBusinessContext() {
  dashboardRequestVersion += 1
  payload.value = {}
  selectedMetricId.value = currentContext.value?.metric_datasource || ''
  selectedLogId.value = currentContext.value?.log_datasource || ''
  namespaceFilter.value = ''
  nodeFilter.value = ''
  namespaceOptions.value = []
  nodeOptions.value = []
  logSourceName.value = ''
  if (!dashboardMounted) return
  await loadFilterOptions()
  await loadDashboard()
}

watch(currentContextId, applyBusinessContext)

onMounted(async () => {
  await businessContextStore.loadContexts()
  await Promise.all([loadSources(), getDashboardDefinitions({ is_enabled: true }).then((response) => { definitions.value = listOf(response); refreshDefinition() })])
  dashboardMounted = true
  await loadDashboard()
})
</script>

<style scoped>
:global(body) { background: #f3f6fa; }
.monitor-dashboard { min-height: 100%; padding: 18px 22px 36px; color: #25364a; background: #f3f6fa; }
.dashboard-header, .monitor-toolbar, .scope-switch { max-width: 1800px; margin: 0 auto 12px; }
.dashboard-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 8px 0 12px; }
.eyebrow { color: #7890aa; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
h1 { margin: 5px 0 0; color: #1b3047; font-size: 24px; font-weight: 700; } .dashboard-header p { margin: 5px 0 0; color: #7489a0; font-size: 12px; }
.header-actions { display: flex; align-items: center; gap: 10px; } .live-state { display: inline-flex; align-items: center; gap: 6px; color: #647b94; font-size: 12px; } .live-state i { width: 7px; height: 7px; border-radius: 50%; background: #20b486; box-shadow: 0 0 0 3px rgba(32,180,134,.13); }
.scope-switch { display: flex; gap: 4px; overflow-x: auto; padding: 4px; border: 1px solid #d8e2ed; background: #fff; box-shadow: 0 4px 14px rgba(42,68,98,.05); } .scope-switch button { display: inline-flex; align-items: center; gap: 7px; min-width: 126px; justify-content: center; padding: 9px 14px; border: 0; color: #667d96; background: transparent; cursor: pointer; white-space: nowrap; } .scope-switch button.active { color: #fff; background: #3478d4; box-shadow: 0 4px 12px rgba(52,120,212,.22); }
.monitor-toolbar { display: grid; grid-template-columns: minmax(170px,1.2fr) minmax(150px,1fr) minmax(150px,1fr) minmax(180px,1.2fr) auto; align-items: end; gap: 10px; padding: 11px; border: 1px solid #d8e2ed; background: #fff; box-shadow: 0 4px 14px rgba(42,68,98,.05); } .toolbar-field { display: grid; gap: 5px; min-width: 0; } .toolbar-field > span { color: #617891; font-size: 11px; } .monitor-toolbar :deep(.el-input__wrapper), .monitor-toolbar :deep(.el-select__wrapper) { background: #f8fafc; box-shadow: 0 0 0 1px #d5e0eb inset; } .monitor-toolbar :deep(.el-input__inner), .monitor-toolbar :deep(.el-select__selected-item) { color: #30465d; }
.bound-resource { min-height: 32px; overflow: hidden; padding: 7px 10px; border: 1px solid #d5e0eb; background: #f8fafc; color: #30465d; font-size: 12px; line-height: 16px; text-overflow: ellipsis; white-space: nowrap; }
.dashboard-canvas { display: grid; grid-template-columns: repeat(24, minmax(0, 1fr)); grid-auto-rows: 26px; gap: 8px; max-width: 1800px; margin: 0 auto; } .dashboard-panel { grid-column: calc(var(--grid-x,0) + 1) / span var(--grid-w, 24); grid-row: calc(var(--grid-y,0) + 1) / span var(--grid-h, 8); min-width: 0; min-height: 0; overflow: hidden; padding: 11px 13px 9px; border: 1px solid #d7e2ed; border-top: 2px solid #6fa6e8; background: #fff; box-shadow: 0 5px 16px rgba(42,68,98,.07); } .dashboard-panel.panel-type-stat { padding-bottom: 9px; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; min-height: 27px; } .panel-heading h2 { margin: 0; color: #253c54; font-size: 13px; font-weight: 600; } .panel-heading p { margin: 3px 0 0; color: #8497aa; font-size: 10px; } .panel-tools { display: flex; align-items: center; color: #7890aa; } .panel-tools :deep(.el-button) { color: #7890aa; } .panel-status { max-width: 180px; overflow: hidden; color: #d85260; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.stat-value { display: flex; align-items: baseline; gap: 6px; margin-top: 7px; color: #253c54; font-size: 28px; font-weight: 700; } .stat-value small { color: #8194a8; font-size: 11px; font-weight: 400; } .stat-value.normal { color: #2878cf; } .stat-value.warning { color: #c98719; } .stat-value.danger { color: #d84f5d; } .stat-value.muted { color: #8999aa; }
.dashboard-panel :deep(.native-chart-canvas) { height: calc(var(--grid-h,8) * 26px - 50px); min-height: 130px; } .dashboard-panel :deep(.native-chart-shell) { min-height: 130px; } .panel-table-wrap { max-height: calc(var(--grid-h,8) * 26px - 48px); overflow: auto; } table { width: 100%; border-collapse: collapse; } th, td { padding: 6px 8px; border-bottom: 1px solid #e6edf4; color: #526a82; font-size: 11px; text-align: left; white-space: nowrap; } th { position: sticky; top: 0; color: #304962; background: #f1f5f9; } .cell-success { color: #158765; font-weight: 600; } .cell-warning { color: #c98719; } .cell-danger { color: #d84f5d; font-weight: 600; } .panel-empty, .empty-dashboard { display: grid; place-items: center; gap: 8px; color: #8295a9; font-size: 12px; } .panel-empty { min-height: 70px; } .empty-dashboard { min-height: 300px; } .empty-dashboard strong { color: #526a82; font-size: 15px; }
@media (max-width: 1100px) { .monitor-toolbar { grid-template-columns: repeat(3,minmax(0,1fr)); } .scope-switch { display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); overflow: visible; } .scope-switch button { min-width: 0; padding-left: 6px; padding-right: 6px; } .dashboard-canvas { grid-template-columns: repeat(12,minmax(0,1fr)); } .dashboard-panel { grid-column: 1 / span 12; grid-row: auto; min-height: 260px; } }
@media (max-width: 700px) { .monitor-dashboard { padding: 12px; } .dashboard-header { flex-direction: column; } .monitor-toolbar { grid-template-columns: 1fr; } .scope-switch button { min-width: 108px; } .dashboard-canvas { display: grid; grid-template-columns: 1fr; grid-auto-rows: auto; padding: 0; } .dashboard-panel { grid-column: 1; grid-row: auto; min-height: 230px; } .dashboard-panel :deep(.native-chart-canvas) { height: 220px; } }
</style>
