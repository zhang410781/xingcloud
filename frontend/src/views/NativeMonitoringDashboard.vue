<template>
  <div class="native-monitor-page workbench-page-shell">
    <section class="hero panel native-monitor-hero">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Histogram /></el-icon></span>
          <h2>监控看板</h2>
          <p class="page-inline-desc">Xing-Cloud JSON 看板引擎统一渲染基础设施、K8S、日志和中间件监控。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :icon="RefreshRight" :loading="loadingSources" @click="loadDataSources">刷新数据源</el-button>
        <el-button size="small" :icon="Upload" @click="importVisible = true">导入 JSON</el-button>
        <el-button size="small" :icon="Download" :disabled="!activeDefinitionId" @click="exportActiveDashboard">导出 JSON</el-button>
        <el-button size="small" type="primary" :icon="DataAnalysis" :loading="loadingDashboard" @click="loadDashboard">刷新看板</el-button>
      </div>
    </section>

    <ObservabilityRouteTabs group="observability" />

    <DashboardCatalog v-model="activeDefinitionId" :dashboards="dashboardDefinitions" />

    <section class="panel native-monitor-control">
      <div class="native-filter-grid">
        <div class="native-filter-item">
          <span>时间范围</span>
          <el-date-picker
            v-model="filters.timeRange"
            type="datetimerange"
            size="small"
            format="YYYY-MM-DD HH:mm:ss"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            :shortcuts="timeShortcuts"
          />
        </div>
        <div class="native-filter-item">
          <span>指标数据源</span>
          <el-select v-model="filters.metricDatasourceId" size="small" filterable clearable placeholder="默认 Prometheus">
            <el-option v-for="item in metricDataSources" :key="item.id" :label="sourceLabel(item)" :value="item.id" />
          </el-select>
        </div>
        <div class="native-filter-item">
          <span>日志数据源</span>
          <el-select v-model="filters.logDatasourceId" size="small" filterable clearable placeholder="ClickHouse 日志源">
            <el-option v-for="item in clickHouseSources" :key="item.id" :label="sourceLabel(item)" :value="item.id" />
          </el-select>
        </div>
      </div>

      <div class="native-filter-grid native-filter-grid--secondary">
        <el-input v-model.trim="filters.namespace" size="small" placeholder="命名空间，多个用逗号分隔" clearable />
        <el-input v-model.trim="filters.node" size="small" placeholder="节点，多个用逗号分隔" clearable />
        <el-input v-model.trim="filters.podName" size="small" placeholder="Pod，多个用逗号分隔" clearable />
        <el-input v-model.trim="filters.logLevel" size="small" placeholder="日志级别，例如 ERROR,INFO" clearable />
        <el-input v-model.trim="filters.domain" size="small" placeholder="域名，多个用逗号分隔" clearable />
        <el-input v-model.trim="filters.serverIp" size="small" placeholder="服务 IP，多个用逗号分隔" clearable />
        <el-input v-model.trim="filters.status" size="small" placeholder="状态码，例如 200,500" clearable />
        <el-input v-model.trim="filters.clientIp" size="small" placeholder="客户端 IP，多个用逗号分隔" clearable />
      </div>
    </section>

    <el-alert
      v-if="dashboardError"
      class="native-monitor-alert"
      type="error"
      show-icon
      :closable="false"
      :title="dashboardError"
    />

    <section v-loading="loadingDashboard || loadingDefinitions" class="native-dashboard-stage">
      <div class="native-dashboard-head">
        <div>
          <h3>{{ dashboardMeta.title || activeDefinition?.title || '请选择看板定义' }}</h3>
          <p>{{ dashboardMeta.description || activeDefinition?.description || '没有看板定义时，请导入 JSON 看板或启用内置看板。' }}</p>
        </div>
        <div class="dashboard-meta-pills">
          <span>{{ formatTimeRange(filters.timeRange) }}</span>
          <span>{{ sourceSummary }}</span>
          <span>{{ okPanelCount }}/{{ panels.length }} 正常</span>
        </div>
      </div>

      <div class="native-source-strip">
        <div v-for="item in sourceStatusItems" :key="item.label" class="native-source-item">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.detail }}</small>
        </div>
      </div>

      <div v-if="!activeDefinitionId && !loadingDefinitions" class="panel native-empty-panel">
        <el-empty description="暂无看板定义，请导入 JSON 看板或启用内置看板" :image-size="96">
          <el-button @click="importVisible = true">导入 JSON</el-button>
        </el-empty>
      </div>

      <div v-else-if="!panels.length && !loadingDashboard" class="panel native-empty-panel">
        <el-empty description="当前看板暂无数据，请检查数据源后刷新" :image-size="90" />
      </div>

      <div v-if="statPanels.length" class="native-stat-grid">
        <article v-for="panel in statPanels" :key="panel.key" class="panel native-stat-card" :class="panelTone(panel)">
          <span>{{ panel.title }}</span>
          <strong>{{ formatPanelValue(panel) }}</strong>
          <small v-if="panel.status === 'warning'">{{ panel.error || '查询失败' }}</small>
          <small v-else>{{ panel.unit || '实时值' }}</small>
        </article>
      </div>

      <div v-if="chartPanels.length" class="native-panel-grid">
        <article v-for="panel in chartPanels" :key="panel.key" class="panel native-data-panel">
          <div class="native-panel-head">
            <div>
              <h4>{{ panel.title }}</h4>
              <span>{{ panel.unit || 'value' }}</span>
            </div>
            <el-tag v-if="panel.status === 'warning'" type="warning" effect="plain" size="small">查询失败</el-tag>
          </div>
          <NativeDashboardChart v-if="panel.status !== 'warning'" :panel="panel" />
          <div v-else class="native-panel-warning">{{ panel.error }}</div>
        </article>
      </div>

      <div v-if="tablePanels.length" class="native-panel-grid native-panel-grid--wide">
        <article v-for="panel in tablePanels" :key="panel.key" class="panel native-data-panel native-table-panel">
          <div class="native-panel-head">
            <div>
              <h4>{{ panel.title }}</h4>
              <span>{{ tableRows(panel).length }} 行</span>
            </div>
            <el-tag v-if="panel.status === 'warning'" type="warning" effect="plain" size="small">查询失败</el-tag>
          </div>
          <div v-if="panel.status === 'warning'" class="native-panel-warning">{{ panel.error }}</div>
          <div v-else class="native-table-wrap">
            <table>
              <thead>
                <tr>
                  <th v-for="column in tableColumns(panel)" :key="`${panel.key}-${column}`">{{ column }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, index) in tableRows(panel).slice(0, 100)" :key="`${panel.key}-${index}`">
                  <td v-for="column in tableColumns(panel)" :key="`${panel.key}-${index}-${column}`">{{ formatCell(row[column]) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!tableRows(panel).length" class="native-table-empty">暂无数据</div>
          </div>
        </article>
      </div>
    </section>

    <JsonAssetImportDialog v-model="importVisible" @submit="importDashboardJson" />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { DataAnalysis, Download, Histogram, RefreshRight, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import ObservabilityRouteTabs from '@/components/observability/ObservabilityRouteTabs.vue'
import DashboardCatalog from '@/components/observability/DashboardCatalog.vue'
import JsonAssetImportDialog from '@/components/observability/JsonAssetImportDialog.vue'
import NativeDashboardChart from '@/components/observability/NativeDashboardChart.vue'
import {
  exportDashboardDefinition,
  getDashboardDefinitions,
  getLogDataSources,
  getMetricDataSources,
  importDashboardDefinition,
  queryDashboardDefinition,
} from '@/api/modules/ops'

const timeShortcuts = [
  { text: '最近 15 分钟', value: () => [new Date(Date.now() - 15 * 60 * 1000), new Date()] },
  { text: '最近 30 分钟', value: () => [new Date(Date.now() - 30 * 60 * 1000), new Date()] },
  { text: '最近 1 小时', value: () => [new Date(Date.now() - 60 * 60 * 1000), new Date()] },
  { text: '最近 3 小时', value: () => [new Date(Date.now() - 3 * 60 * 60 * 1000), new Date()] },
  { text: '最近 6 小时', value: () => [new Date(Date.now() - 6 * 60 * 60 * 1000), new Date()] },
  { text: '最近 24 小时', value: () => [new Date(Date.now() - 24 * 60 * 60 * 1000), new Date()] },
]

const loadingSources = ref(false)
const loadingDefinitions = ref(false)
const loadingDashboard = ref(false)
const importVisible = ref(false)
const dashboardError = ref('')
const metricDataSources = ref([])
const logDataSources = ref([])
const dashboardDefinitions = ref([])
const activeDefinitionId = ref('')
const dashboardPayload = ref({})
const initialized = ref(false)

const filters = reactive({
  metricDatasourceId: '',
  logDatasourceId: '',
  timeRange: [new Date(Date.now() - 60 * 60 * 1000), new Date()],
  namespace: '',
  node: '',
  podName: '',
  logLevel: '',
  domain: '',
  serverIp: '',
  status: '',
  clientIp: '',
})

const clickHouseSources = computed(() => logDataSources.value.filter((item) => item.provider === 'clickhouse'))
const activeDefinition = computed(() => dashboardDefinitions.value.find((item) => String(item.id) === String(activeDefinitionId.value)))
const dashboardMeta = computed(() => dashboardPayload.value.dashboard || {})
const panels = computed(() => Array.isArray(dashboardPayload.value.panels) ? dashboardPayload.value.panels : [])
const statPanels = computed(() => panels.value.filter((panel) => panel.type === 'stat'))
const chartPanels = computed(() => panels.value.filter((panel) => ['timeseries', 'bar'].includes(panel.type)))
const tablePanels = computed(() => panels.value.filter((panel) => ['table', 'logs'].includes(panel.type)))
const okPanelCount = computed(() => panels.value.filter((panel) => panel.status !== 'warning').length)
const currentMetricDatasource = computed(() => mergeDatasource(dashboardPayload.value.metric_datasource, metricDataSources.value, filters.metricDatasourceId))
const currentLogDatasource = computed(() => mergeDatasource(dashboardPayload.value.log_datasource, clickHouseSources.value, filters.logDatasourceId))
const sourceSummary = computed(() => {
  const metric = currentMetricDatasource.value?.name || '指标源未选择'
  const log = currentLogDatasource.value?.name || '日志源未选择'
  return `${metric} / ${log}`
})
const sourceStatusItems = computed(() => [
  { label: '看板定义', value: activeDefinition.value?.title || '未选择', detail: activeDefinition.value?.is_builtin ? '内置 JSON 看板' : '自定义 JSON 看板' },
  { label: '指标数据源', value: currentMetricDatasource.value?.name || '未选择', detail: sourceScope(currentMetricDatasource.value) },
  { label: '日志数据源', value: currentLogDatasource.value?.name || '未选择', detail: sourceScope(currentLogDatasource.value) },
])

function sourceLabel(item) {
  const extras = [item.environment, item.cluster_name].filter(Boolean).join(' / ')
  return extras ? `${item.name}（${extras}）` : item.name
}

function sourceScope(source) {
  if (!source) return '等待选择'
  return [source.environment, source.cluster_name].filter(Boolean).join(' / ') || '全局'
}

function mergeDatasource(primary, list, selectedId) {
  const sourceId = primary?.id || selectedId
  const fromList = list.find((item) => String(item.id) === String(sourceId))
  if (primary && fromList) return { ...fromList, ...primary }
  return primary || fromList || null
}

function commaList(value) {
  return String(value || '').split(',').map((item) => item.trim()).filter(Boolean)
}

function toTimestampMs(value) {
  if (!value) return Date.now()
  return value instanceof Date ? value.getTime() : new Date(value).getTime()
}

function buildDashboardPayload() {
  return {
    start_ms: toTimestampMs(filters.timeRange?.[0]),
    end_ms: toTimestampMs(filters.timeRange?.[1]),
    step: 60,
    metric_datasource_id: filters.metricDatasourceId || undefined,
    log_datasource_id: filters.logDatasourceId || undefined,
    namespace: commaList(filters.namespace),
    node: commaList(filters.node),
    pod_name: commaList(filters.podName),
    log_level: commaList(filters.logLevel),
    domain: commaList(filters.domain),
    server_ip: commaList(filters.serverIp),
    status: commaList(filters.status),
    client_ip: commaList(filters.clientIp),
  }
}

async function loadDataSources() {
  loadingSources.value = true
  try {
    const [metrics, logs] = await Promise.allSettled([
      getMetricDataSources({ is_enabled: true }, { skipErrorMessage: true }),
      getLogDataSources({ is_enabled: true }, { skipErrorMessage: true }),
    ])
    metricDataSources.value = listOf(metrics.value)
    logDataSources.value = listOf(logs.value)
    if (!filters.metricDatasourceId && metricDataSources.value.length) {
      filters.metricDatasourceId = metricDataSources.value.find((item) => item.is_default)?.id || metricDataSources.value[0].id
    }
    if (!filters.logDatasourceId && clickHouseSources.value.length) {
      filters.logDatasourceId = clickHouseSources.value.find((item) => item.is_default)?.id || clickHouseSources.value[0].id
    }
  } finally {
    loadingSources.value = false
  }
}

async function loadDashboardDefinitions() {
  loadingDefinitions.value = true
  try {
    const response = await getDashboardDefinitions({ is_enabled: true })
    dashboardDefinitions.value = listOf(response)
    if (!activeDefinitionId.value && dashboardDefinitions.value.length) {
      activeDefinitionId.value = dashboardDefinitions.value[0].id
    }
  } finally {
    loadingDefinitions.value = false
  }
}

async function importDashboardJson(definition) {
  const created = await importDashboardDefinition(definition)
  ElMessage.success('看板定义已导入')
  await loadDashboardDefinitions()
  activeDefinitionId.value = created.id
  await loadDashboard()
}

async function exportActiveDashboard() {
  if (!activeDefinitionId.value) return
  const definition = await exportDashboardDefinition(activeDefinitionId.value)
  const blob = new Blob([JSON.stringify(definition, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${definition.title || 'observability-dashboard'}.json`
  link.click()
  URL.revokeObjectURL(url)
}

async function loadDashboard() {
  dashboardError.value = ''
  if (!activeDefinitionId.value) {
    dashboardPayload.value = {}
    return
  }
  loadingDashboard.value = true
  try {
    dashboardPayload.value = await queryDashboardDefinition(activeDefinitionId.value, buildDashboardPayload(), { timeout: 60000 })
  } catch (error) {
    dashboardPayload.value = {}
    dashboardError.value = error.response?.data?.detail || error.message || '看板数据加载失败'
  } finally {
    loadingDashboard.value = false
  }
}

function reloadDashboardIfReady() {
  if (initialized.value) loadDashboard()
}

function listOf(response) {
  return Array.isArray(response) ? response : (response?.results || [])
}

function tableRows(panel) {
  return Array.isArray(panel?.data?.rows) ? panel.data.rows : []
}

function tableColumns(panel) {
  const first = tableRows(panel).find((row) => row && typeof row === 'object')
  if (!first) return ['time', 'body', 'level', 'namespace', 'pod_name']
  return Object.keys(first).slice(0, 8)
}

function formatCell(value) {
  if (value === null || value === undefined || value === '') return '--'
  if (typeof value === 'number') return Number(value.toFixed(2)).toLocaleString('zh-CN')
  return String(value)
}

function formatPanelValue(panel) {
  if (panel.status === 'warning') return '--'
  const value = Number(panel.data?.value)
  if (!Number.isFinite(value)) return '--'
  const decimals = Number(panel.decimals || 0)
  if (panel.unit === 'bytes') return formatBytes(value)
  const formatted = value.toLocaleString('zh-CN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  return panel.unit === '%' ? `${formatted}%` : `${formatted}${panel.unit && panel.unit.length <= 2 ? panel.unit : ''}`
}

function formatBytes(value) {
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)}GiB`
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)}MiB`
  if (value >= 1024) return `${(value / 1024).toFixed(1)}KiB`
  return `${Math.round(value)}B`
}

function formatTimeRange(range) {
  if (!Array.isArray(range) || range.length < 2) return '最近 1 小时'
  const minutes = Math.max(1, Math.round((toTimestampMs(range[1]) - toTimestampMs(range[0])) / 60000))
  if (minutes >= 1440) return `最近 ${Math.round(minutes / 1440)} 天`
  if (minutes >= 60) return `最近 ${Number((minutes / 60).toFixed(1))} 小时`
  return `最近 ${minutes} 分钟`
}

function panelTone(panel) {
  if (panel.status === 'warning') return 'is-warning'
  const value = Number(panel.data?.value)
  if (panel.unit === '%' && value >= 90) return 'is-danger'
  if (panel.unit === '%' && value >= 75) return 'is-caution'
  return 'is-ok'
}

watch(activeDefinitionId, () => reloadDashboardIfReady())

watch(
  () => [
    filters.metricDatasourceId,
    filters.logDatasourceId,
    filters.namespace,
    filters.node,
    filters.podName,
    filters.logLevel,
    filters.domain,
    filters.serverIp,
    filters.status,
    filters.clientIp,
  ],
  () => reloadDashboardIfReady(),
)

watch(
  () => filters.timeRange,
  () => reloadDashboardIfReady(),
  { deep: true },
)

onMounted(async () => {
  await loadDataSources()
  await loadDashboardDefinitions()
  await loadDashboard()
  initialized.value = true
  if (!metricDataSources.value.length && !clickHouseSources.value.length) {
    ElMessage.warning('未发现可用指标或 ClickHouse 日志数据源')
  }
})
</script>

<style scoped>
.native-monitor-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.native-monitor-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.native-monitor-control {
  display: grid;
  gap: 12px;
}

.native-filter-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(220px, 1fr));
  gap: 12px;
}

.native-filter-grid--secondary {
  grid-template-columns: repeat(4, minmax(180px, 1fr));
}

.native-filter-item {
  display: grid;
  gap: 6px;
}

.native-filter-item span {
  color: #64748b;
  font-size: 12px;
}

.native-dashboard-stage {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 320px;
}

.native-dashboard-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 4px 2px;
}

.native-dashboard-head h3 {
  margin: 0;
  color: #0f172a;
  font-size: 20px;
}

.native-dashboard-head p {
  margin: 6px 0 0;
  color: #64748b;
}

.dashboard-meta-pills {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.dashboard-meta-pills span {
  padding: 6px 10px;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
}

.native-source-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.native-source-item {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid rgba(226, 232, 240, 0.86);
  border-radius: 8px;
  background: #fff;
}

.native-source-item span,
.native-source-item small {
  color: #64748b;
  font-size: 12px;
}

.native-source-item strong {
  color: #0f172a;
}

.native-empty-panel {
  display: grid;
  place-items: center;
  min-height: 280px;
}

.native-stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
}

.native-stat-card {
  display: grid;
  gap: 8px;
  padding: 14px;
  border-radius: 8px;
}

.native-stat-card span,
.native-stat-card small {
  color: #64748b;
}

.native-stat-card strong {
  color: #0f172a;
  font-size: 28px;
}

.native-stat-card.is-danger {
  border-color: rgba(239, 68, 68, 0.2);
}

.native-stat-card.is-caution,
.native-stat-card.is-warning {
  border-color: rgba(245, 158, 11, 0.24);
}

.native-panel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 14px;
}

.native-panel-grid--wide {
  grid-template-columns: 1fr;
}

.native-data-panel {
  min-width: 0;
  padding: 14px;
  border-radius: 8px;
}

.native-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.native-panel-head h4 {
  margin: 0;
  color: #0f172a;
  font-size: 15px;
}

.native-panel-head span {
  display: block;
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.native-panel-warning {
  min-height: 260px;
  display: grid;
  place-items: center;
  color: #b45309;
  background: #fffbeb;
  border-radius: 8px;
  padding: 18px;
}

.native-table-wrap {
  overflow: auto;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.native-table-wrap table {
  width: 100%;
  border-collapse: collapse;
  min-width: 720px;
}

.native-table-wrap th,
.native-table-wrap td {
  padding: 9px 10px;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
  color: #475569;
  font-size: 12px;
  vertical-align: top;
}

.native-table-wrap th {
  background: #f8fafc;
  color: #334155;
  font-weight: 700;
}

.native-table-empty {
  padding: 28px;
  text-align: center;
  color: #94a3b8;
}

@media (max-width: 920px) {
  .native-monitor-hero,
  .native-dashboard-head {
    align-items: stretch;
    flex-direction: column;
  }

  .native-filter-grid,
  .native-filter-grid--secondary,
  .native-source-strip {
    grid-template-columns: 1fr;
  }
}
</style>
