<template>
  <div class="native-monitor-page workbench-page-shell">
    <section class="hero panel native-monitor-hero">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Histogram /></el-icon></span>
          <h2>监控看板</h2>
          <p class="page-inline-desc">平台原生服务器、K8S 集群与日志看板，统一展示关键运行指标。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" @click="loadDataSources" :loading="loadingSources">
          <el-icon><RefreshRight /></el-icon>
          刷新数据源
        </el-button>
        <el-button size="small" type="primary" @click="loadDashboard" :loading="loadingDashboard">
          <el-icon><DataAnalysis /></el-icon>
          刷新看板
        </el-button>
      </div>
    </section>

    <ObservabilityRouteTabs group="boards" />

    <section class="panel native-monitor-control">
      <div class="dashboard-switcher">
        <button
          v-for="item in dashboardOptions"
          :key="item.key"
          type="button"
          class="dashboard-switch"
          :class="{ active: filters.dashboard === item.key }"
          @click="changeDashboard(item.key)"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
          <small>{{ item.hint }}</small>
        </button>
      </div>

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
        <div v-if="isMetricDashboard" class="native-filter-item">
          <span>指标数据源</span>
          <el-select v-model="filters.metricDatasourceId" size="small" filterable clearable placeholder="自动选择默认 Prometheus">
            <el-option v-for="item in metricDataSources" :key="item.id" :label="sourceLabel(item)" :value="item.id" />
          </el-select>
        </div>
        <template v-else>
          <div class="native-filter-item">
            <span>日志数据源</span>
            <el-select v-model="filters.logDatasourceId" size="small" filterable clearable placeholder="选择 ClickHouse 日志源">
              <el-option v-for="item in clickHouseSources" :key="item.id" :label="sourceLabel(item)" :value="item.id" />
            </el-select>
          </div>
          <div class="native-filter-item">
            <span>日志看板</span>
            <el-segmented v-model="filters.logVariant" :options="logVariantOptions" size="small" />
          </div>
        </template>
      </div>

      <div v-if="filters.dashboard === 'logs'" class="native-filter-grid native-filter-grid--secondary">
        <template v-if="filters.logVariant === 'container'">
          <el-input v-model.trim="filters.namespace" size="small" placeholder="命名空间，多个用逗号分隔" clearable />
          <el-input v-model.trim="filters.node" size="small" placeholder="节点，多个用逗号分隔" clearable />
          <el-input v-model.trim="filters.podName" size="small" placeholder="Pod，多个用逗号分隔" clearable />
          <el-input v-model.trim="filters.logLevel" size="small" placeholder="日志级别，例如 ERROR,INFO" clearable />
        </template>
        <template v-else>
          <el-input v-model.trim="filters.domain" size="small" placeholder="域名，多个用逗号分隔" clearable />
          <el-input v-model.trim="filters.serverIp" size="small" placeholder="服务 IP，多个用逗号分隔" clearable />
          <el-input v-model.trim="filters.status" size="small" placeholder="状态码，例如 200,500" clearable />
          <el-input v-model.trim="filters.clientIp" size="small" placeholder="客户端 IP，多个用逗号分隔" clearable />
        </template>
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

    <section v-loading="loadingDashboard" class="native-dashboard-stage">
      <div class="native-dashboard-head">
        <div>
          <h3>{{ dashboardMeta.title || activeDashboardOption.label }}</h3>
          <p>{{ dashboardMeta.description || activeDashboardOption.hint }}</p>
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

      <div v-if="!panels.length && !loadingDashboard" class="panel native-empty-panel">
        <el-empty description="暂无看板数据，请选择数据源后刷新" :image-size="90" />
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
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { DataAnalysis, Histogram, Monitor, RefreshRight, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import ObservabilityRouteTabs from '@/components/observability/ObservabilityRouteTabs.vue'
import NativeDashboardChart from '@/components/observability/NativeDashboardChart.vue'
import { getLogDataSources, getMetricDataSources, queryMonitoringDashboard } from '@/api/modules/ops'

const dashboardOptions = [
  { key: 'server', label: '服务器看板', hint: '服务器 CPU、内存、磁盘、网络', icon: Monitor },
  { key: 'kubernetes', label: 'K8S 集群看板', hint: '节点、Pod、命名空间、资源用量', icon: Histogram },
  { key: 'logs', label: '日志看板', hint: '容器日志与 WEB 请求日志', icon: Search },
]

const logVariantOptions = [
  { label: '容器日志', value: 'container' },
  { label: 'WEB 请求', value: 'web' },
]

const timeShortcuts = [
  { text: '最近 15 分钟', value: () => [new Date(Date.now() - 15 * 60 * 1000), new Date()] },
  { text: '最近 30 分钟', value: () => [new Date(Date.now() - 30 * 60 * 1000), new Date()] },
  { text: '最近 1 小时', value: () => [new Date(Date.now() - 60 * 60 * 1000), new Date()] },
  { text: '最近 3 小时', value: () => [new Date(Date.now() - 3 * 60 * 60 * 1000), new Date()] },
  { text: '最近 6 小时', value: () => [new Date(Date.now() - 6 * 60 * 60 * 1000), new Date()] },
  { text: '最近 24 小时', value: () => [new Date(Date.now() - 24 * 60 * 60 * 1000), new Date()] },
]

const loadingSources = ref(false)
const loadingDashboard = ref(false)
const dashboardError = ref('')
const metricDataSources = ref([])
const logDataSources = ref([])
const dashboardPayload = ref({})
const initialized = ref(false)

const filters = reactive({
  dashboard: 'kubernetes',
  logVariant: 'container',
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

const activeDashboardOption = computed(() => dashboardOptions.find((item) => item.key === filters.dashboard) || dashboardOptions[1])
const isMetricDashboard = computed(() => filters.dashboard !== 'logs')
const clickHouseSources = computed(() => logDataSources.value.filter((item) => item.provider === 'clickhouse'))
const dashboardMeta = computed(() => dashboardPayload.value.dashboard || {})
const panels = computed(() => Array.isArray(dashboardPayload.value.panels) ? dashboardPayload.value.panels : [])
const statPanels = computed(() => panels.value.filter((panel) => panel.type === 'stat'))
const chartPanels = computed(() => panels.value.filter((panel) => ['timeseries', 'bar'].includes(panel.type)))
const tablePanels = computed(() => panels.value.filter((panel) => ['table', 'logs'].includes(panel.type)))
const okPanelCount = computed(() => panels.value.filter((panel) => panel.status !== 'warning').length)
const currentMetricDatasource = computed(() => mergeDatasource(dashboardPayload.value.metric_datasource, metricDataSources.value, filters.metricDatasourceId))
const currentLogDatasource = computed(() => mergeDatasource(dashboardPayload.value.log_datasource, clickHouseSources.value, filters.logDatasourceId))
const currentDatasource = computed(() => (isMetricDashboard.value ? currentMetricDatasource.value : currentLogDatasource.value))
const sourceSummary = computed(() => {
  const source = currentDatasource.value
  if (!source) return isMetricDashboard.value ? '未选择指标数据源' : '未选择日志数据源'
  return source.is_default ? `${source.name}（默认）` : source.name
})
const sourceStatusItems = computed(() => {
  const source = currentDatasource.value
  const sourceKind = isMetricDashboard.value ? 'Prometheus 指标源' : 'ClickHouse 日志源'
  const scope = [source?.environment, source?.cluster_name].filter(Boolean).join(' / ') || '全局'
  return [
    { label: '看板类型', value: activeDashboardOption.value.label, detail: dashboardMeta.value.source_type || activeDashboardOption.value.hint },
    { label: '当前数据源', value: source?.name || '未选择', detail: source ? `${sourceKind} / ${scope}` : sourceKind },
    { label: '查询窗口', value: formatTimeRange(filters.timeRange), detail: `${okPanelCount.value}/${panels.value.length || 0} 个面板正常` },
  ]
})

function sourceLabel(item) {
  const extras = [item.environment, item.cluster_name].filter(Boolean).join(' / ')
  return extras ? `${item.name}（${extras}）` : item.name
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
  const payload = {
    dashboard: filters.dashboard,
    start_ms: toTimestampMs(filters.timeRange?.[0]),
    end_ms: toTimestampMs(filters.timeRange?.[1]),
    step: 60,
  }
  if (isMetricDashboard.value) {
    payload.metric_datasource_id = filters.metricDatasourceId || undefined
  } else {
    payload.log_datasource_id = filters.logDatasourceId || undefined
    payload.log_dashboard = filters.logVariant
    if (filters.logVariant === 'container') {
      payload.namespace = commaList(filters.namespace)
      payload.node = commaList(filters.node)
      payload.pod_name = commaList(filters.podName)
      payload.log_level = commaList(filters.logLevel)
    } else {
      payload.domain = commaList(filters.domain)
      payload.server_ip = commaList(filters.serverIp)
      payload.status = commaList(filters.status)
      payload.client_ip = commaList(filters.clientIp)
    }
  }
  return payload
}

async function loadDataSources() {
  loadingSources.value = true
  try {
    const [metrics, logs] = await Promise.allSettled([
      getMetricDataSources({ is_enabled: true }, { skipErrorMessage: true }),
      getLogDataSources({ is_enabled: true }, { skipErrorMessage: true }),
    ])
    metricDataSources.value = Array.isArray(metrics.value) ? metrics.value : metrics.value?.results || []
    logDataSources.value = Array.isArray(logs.value) ? logs.value : logs.value?.results || []
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

async function loadDashboard() {
  dashboardError.value = ''
  loadingDashboard.value = true
  try {
    dashboardPayload.value = await queryMonitoringDashboard(buildDashboardPayload(), { timeout: 60000 })
  } catch (error) {
    dashboardPayload.value = {}
    dashboardError.value = error.response?.data?.detail || error.message || '看板数据加载失败'
  } finally {
    loadingDashboard.value = false
  }
}

function changeDashboard(key) {
  filters.dashboard = key
  loadDashboard()
}

function reloadDashboardIfReady() {
  if (initialized.value) loadDashboard()
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

watch(
  () => [filters.metricDatasourceId, filters.logDatasourceId, filters.logVariant],
  () => reloadDashboardIfReady(),
)

watch(
  () => filters.timeRange,
  () => reloadDashboardIfReady(),
  { deep: true },
)

onMounted(async () => {
  await loadDataSources()
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

.hero-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.hero-title-row h2 {
  margin: 0;
  font-size: 22px;
  color: #0f172a;
}

.hero-icon {
  width: 34px;
  height: 34px;
  display: inline-grid;
  place-items: center;
  border-radius: 8px;
  background: #e0f2fe;
  color: #0369a1;
}

.page-inline-desc {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.hero-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.native-monitor-control {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.dashboard-switcher {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.dashboard-switch {
  min-height: 82px;
  border: 1px solid #dbe3ef;
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  display: grid;
  grid-template-columns: 28px 1fr;
  grid-template-areas: "icon title" "icon hint";
  gap: 3px 10px;
  text-align: left;
  color: #334155;
  cursor: pointer;
}

.dashboard-switch :deep(.el-icon) {
  grid-area: icon;
  align-self: center;
  font-size: 22px;
  color: #2563eb;
}

.dashboard-switch span {
  grid-area: title;
  font-weight: 700;
  color: #0f172a;
}

.dashboard-switch small {
  grid-area: hint;
  color: #64748b;
  line-height: 1.4;
}

.dashboard-switch.active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.08);
}

.native-filter-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  align-items: end;
}

.native-filter-grid--secondary {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.native-filter-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.native-filter-item > span {
  color: #475569;
  font-size: 12px;
  font-weight: 700;
}

.native-filter-item :deep(.el-select),
.native-filter-item :deep(.el-date-editor) {
  width: 100%;
}

.native-monitor-alert {
  margin: 0;
}

.native-dashboard-stage {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 260px;
}

.native-dashboard-head {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: flex-start;
}

.native-dashboard-head h3 {
  margin: 0;
  color: #0f172a;
  font-size: 20px;
}

.native-dashboard-head p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
}

.dashboard-meta-pills {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.dashboard-meta-pills span {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  padding: 5px 9px;
  color: #475569;
  font-size: 12px;
}

.native-source-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.native-source-item {
  min-height: 72px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.native-source-item span {
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.native-source-item strong {
  color: #0f172a;
  font-size: 15px;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.native-source-item small {
  color: #64748b;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.native-empty-panel {
  min-height: 240px;
  display: grid;
  place-items: center;
}

.native-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.native-stat-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 112px;
  border-left: 4px solid #2563eb;
}

.native-stat-card span {
  color: #64748b;
  font-size: 13px;
}

.native-stat-card strong {
  color: #0f172a;
  font-size: 28px;
  line-height: 1;
}

.native-stat-card small {
  color: #64748b;
  line-height: 1.4;
}

.native-stat-card.is-danger {
  border-left-color: #dc2626;
}

.native-stat-card.is-caution {
  border-left-color: #d97706;
}

.native-stat-card.is-warning {
  border-left-color: #f59e0b;
  background: #fffbeb;
}

.native-panel-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.native-panel-grid--wide {
  grid-template-columns: 1fr;
}

.native-data-panel {
  min-width: 0;
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
  display: inline-block;
  margin-top: 3px;
  color: #64748b;
  font-size: 12px;
}

.native-panel-warning {
  min-height: 220px;
  display: grid;
  place-items: center;
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  padding: 18px;
  text-align: center;
}

.native-table-wrap {
  overflow: auto;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.native-table-wrap table {
  width: 100%;
  border-collapse: collapse;
  min-width: 760px;
  font-size: 12px;
}

.native-table-wrap th,
.native-table-wrap td {
  padding: 9px 10px;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
  color: #334155;
  vertical-align: top;
  max-width: 320px;
  overflow-wrap: anywhere;
}

.native-table-wrap th {
  background: #f8fafc;
  color: #475569;
  font-weight: 700;
  white-space: nowrap;
}

.native-table-empty {
  padding: 30px;
  text-align: center;
  color: #94a3b8;
}

@media (max-width: 1100px) {
  .dashboard-switcher,
  .native-filter-grid,
  .native-filter-grid--secondary,
  .native-source-strip,
  .native-stat-grid,
  .native-panel-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 720px) {
  .native-monitor-hero,
  .native-dashboard-head {
    flex-direction: column;
  }

  .dashboard-switcher,
  .native-filter-grid,
  .native-filter-grid--secondary,
  .native-source-strip,
  .native-stat-grid,
  .native-panel-grid {
    grid-template-columns: 1fr;
  }

  .dashboard-meta-pills {
    justify-content: flex-start;
  }
}
</style>
