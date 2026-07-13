<template>
  <div v-loading="loading" class="dashboard-page workbench-page-shell">
    <section class="ops-hero">
      <div class="hero-copy">
        <span class="eyebrow">运行控制面</span>
        <h1>{{ cockpitTitle }}</h1>
        <p>一屏观测，全程闭环。统一呈现 SLA、告警、任务、资产与可观测接入的运行态势。</p>
        <div class="hero-facts">
          <span v-for="fact in heroFacts" :key="fact.label">
            <strong>{{ fact.value }}</strong>
            {{ fact.label }}
          </span>
        </div>
      </div>

      <div class="ops-score" :class="`tone-${opsHealthTone}`">
        <span>运行健康度</span>
        <strong>{{ opsHealthScore }}</strong>
        <small>{{ opsHealthSummary }}</small>
      </div>

      <div class="hero-actions">
        <span class="refresh-time">{{ lastUpdatedText }}</span>
        <el-button size="small" plain @click="go('/observability/overview')">
          <el-icon><DataBoard /></el-icon>
          可观测总览
        </el-button>
        <el-button size="small" plain @click="go('/observability/alerts')">
          <el-icon><Warning /></el-icon>
          告警中心
        </el-button>
        <el-button size="small" type="primary" :loading="loading" @click="loadDashboard">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
      </div>
    </section>

    <section class="headline-grid">
      <div v-for="metric in headlineMetrics" :key="metric.key" class="headline-card" :class="`tone-${metric.tone}`">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
        <small>{{ metric.helper }}</small>
      </div>
    </section>

    <section class="control-lanes">
      <button
        v-for="lane in operationLanes"
        :key="lane.key"
        type="button"
        class="lane-card"
        :class="`tone-${lane.tone}`"
        @click="go(lane.route)"
      >
        <span class="lane-icon">
          <el-icon><component :is="lane.icon" /></el-icon>
        </span>
        <span class="lane-body">
          <span class="lane-title">{{ lane.title }}</span>
          <strong>{{ lane.value }}</strong>
          <small>{{ lane.helper }}</small>
        </span>
        <el-tag size="small" :type="tagTypeFromTone(lane.tone)" effect="light">{{ lane.tag }}</el-tag>
      </button>
    </section>

    <section class="ops-layout">
      <div class="ops-panel product-panel">
        <div class="panel-head">
          <div>
            <span class="panel-title">产品稳定性</span>
            <p>按数据库、中间件、容器平台、网络和服务器聚合本月 SLA 与风险。</p>
          </div>
          <el-tag size="small" effect="plain">目标 {{ formatPercent(sla.target) }}</el-tag>
        </div>

        <div class="product-table">
          <div class="product-header">
            <span>产品域</span>
            <span>本月 SLA</span>
            <span>状态</span>
            <span>灾难级时长</span>
            <span>告警</span>
            <span>风险</span>
          </div>
          <div v-for="item in productSlaRows" :key="item.key" class="product-row">
            <div class="product-name">
              <strong>{{ item.name }}</strong>
              <span>目标 {{ formatPercent(item.target) }}</span>
            </div>
            <div class="product-sla product-cell" data-label="本月 SLA">
              <div class="progress-line" :style="{ '--bar-width': barWidth(item.month_sla), '--bar-color': statusColor(item.status) }">
                <span></span>
              </div>
              <strong>{{ formatPercent(item.month_sla) }}</strong>
            </div>
            <div class="product-cell" data-label="状态">
              <el-tag size="small" :type="statusTagType(item.status)" effect="light">{{ item.status }}</el-tag>
            </div>
            <div class="product-cell numeric" data-label="灾难级时长">{{ formatMinutes(item.downtime_minutes) }}</div>
            <div class="product-cell numeric" data-label="告警">
              {{ formatNumber(item.alerts) }}
              <span v-if="item.critical_alerts"> / 严重 {{ formatNumber(item.critical_alerts) }}</span>
            </div>
            <div class="product-cell numeric" data-label="风险">{{ formatNumber(item.risk_count) }}</div>
          </div>
          <div v-if="!productSlaRows.length" class="empty-state">暂无产品 SLA 数据</div>
        </div>
      </div>

      <div class="ops-panel">
        <div class="panel-head">
          <div>
            <span class="panel-title">告警压力</span>
            <p>本月告警级别、未确认数量与产品分布。</p>
          </div>
        </div>
        <div class="tile-grid two-columns">
          <div v-for="item in alertLevelMetrics" :key="item.key" class="mini-tile" :class="`tone-${item.tone}`">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
        <div class="rank-list">
          <div v-for="item in alertProductRows" :key="item.key" class="rank-row">
            <div>
              <strong>{{ item.product }}</strong>
              <span>严重 {{ formatNumber(item.critical) }} / 警告 {{ formatNumber(item.warning) }}</span>
            </div>
            <div class="progress-line" :style="{ '--bar-width': alertProductBarWidth(item.total), '--bar-color': '#2563eb' }">
              <span></span>
            </div>
            <em>{{ formatNumber(item.total) }}</em>
          </div>
          <div v-if="!alertProductRows.length" class="empty-state compact">暂无本月告警</div>
        </div>
      </div>

      <div class="ops-panel">
        <div class="panel-head">
          <div>
            <span class="panel-title">任务闭环</span>
            <p>发布、事务工单与超时任务的处理节奏。</p>
          </div>
        </div>
        <div class="tile-grid two-columns">
          <div v-for="item in workorderMetrics" :key="item.key" class="mini-tile" :class="`tone-${item.tone}`">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small>{{ item.helper }}</small>
          </div>
        </div>
        <div class="single-progress">
          <div>
            <span>及时处理率</span>
            <strong>{{ formatPercent(workorders.timely_rate) }}</strong>
          </div>
          <div class="progress-line" :style="{ '--bar-width': barWidth(workorders.timely_rate), '--bar-color': statusColor(workorderStatus) }">
            <span></span>
          </div>
        </div>
      </div>

      <div class="ops-panel">
        <div class="panel-head">
          <div>
            <span class="panel-title">观测接入</span>
            <p>Prometheus、ClickHouse 与告警规则引擎健康摘要。</p>
          </div>
          <el-tag size="small" :type="tagTypeFromTone(sourceHealthTone)" effect="plain">{{ sourceHealthTag }}</el-tag>
        </div>
        <div class="tile-grid two-columns">
          <div v-for="item in sourceHealthItems" :key="item.key" class="mini-tile" :class="`tone-${item.tone}`">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small>{{ item.helper }}</small>
          </div>
        </div>
      </div>

      <div class="ops-panel">
        <div class="panel-head">
          <div>
            <span class="panel-title">基础资源与发布</span>
            <p>主机在线率、资源均值和应用发布概况。</p>
          </div>
        </div>
        <div class="infra-list">
          <div v-for="item in infraMetrics" :key="item.key" class="infra-row">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small>{{ item.helper }}</small>
          </div>
        </div>
      </div>

      <div class="ops-panel risk-panel">
        <div class="panel-head">
          <div>
            <span class="panel-title">风险与最近告警</span>
            <p>把需要值班人员推进的风险项和最新告警放在同一视图。</p>
          </div>
          <el-tag size="small" :type="riskItems.length ? 'warning' : 'success'" effect="plain">
            {{ riskItems.length ? `${riskItems.length} 项风险` : '无风险' }}
          </el-tag>
        </div>
        <div class="risk-alert-grid">
          <div class="risk-list">
            <div v-for="item in riskItems" :key="`${item.level}-${item.title}`" class="risk-item" :class="`tone-${riskTone(item.level)}`">
              <span>{{ riskLevelText(item.level) }}</span>
              <div>
                <strong>{{ item.title }}</strong>
                <p>{{ item.description }}</p>
              </div>
            </div>
            <div v-if="!riskItems.length" class="empty-state">暂无风险项</div>
          </div>

          <div class="recent-alerts">
            <div v-for="item in recentAlerts" :key="item.id" class="recent-alert-row">
              <el-tag size="small" :type="alertLevelTagType(item.level)" effect="light">{{ alertLevelLabel(item.level) }}</el-tag>
              <div>
                <strong>{{ item.title }}</strong>
                <span>{{ item.product || '-' }} · {{ item.service || item.environment || '-' }} · {{ formatDateTime(item.created_at) }}</span>
              </div>
              <em>{{ item.is_acknowledged ? '已确认' : '未确认' }}</em>
            </div>
            <div v-if="!recentAlerts.length" class="empty-state">暂无告警明细</div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Connection, DataAnalysis, DataBoard, DataLine, Finished, Monitor, RefreshRight, Warning } from '@element-plus/icons-vue'
import { getDashboardStats, getObservabilityOverview } from '@/api/modules/ops'

const router = useRouter()
const loading = ref(false)
const dashboard = ref({})
const overview = ref({})
const lastUpdatedAt = ref(null)

const defaultSla = {
  target: 99.96,
  month_status: '达标',
  month_sla: 100,
  annual_sla_to_date: 100,
  annual_forecast_sla: 100,
  annual_goal_status: '预计达成',
  downtime_basis: '灾难级告警持续时长',
  month_downtime_minutes: 0,
  annual_downtime_minutes: 0,
  annual_budget_remaining_minutes: 0,
}

const cockpitTitle = computed(() => dashboard.value?.cockpit_title || 'Xing-Cloud 运行总览')
const sla = computed(() => ({ ...defaultSla, ...(dashboard.value?.sla || {}) }))
const productSlaRows = computed(() => Array.isArray(dashboard.value?.product_slas) ? dashboard.value.product_slas : [])
const workorders = computed(() => ({
  total: 0,
  deployments: 0,
  transaction_tickets: 0,
  done: 0,
  pending: 0,
  failed: 0,
  overdue: 0,
  timely_rate: 100,
  ...(dashboard.value?.workorders || {}),
}))
const alerts = computed(() => ({
  total: 0,
  month_total: 0,
  unacknowledged: 0,
  month_critical: 0,
  month_warning: 0,
  month_info: 0,
  by_product: [],
  recent: [],
  ...(dashboard.value?.alerts || {}),
}))
const hosts = computed(() => ({
  total: 0,
  online: 0,
  offline: 0,
  warning: 0,
  avg_cpu: 0,
  avg_memory: 0,
  avg_disk: 0,
  ...(dashboard.value?.hosts || {}),
}))
const deployments = computed(() => ({
  total: 0,
  success: 0,
  failed: 0,
  running: 0,
  ...(dashboard.value?.deployments || {}),
}))
const riskItems = computed(() => Array.isArray(dashboard.value?.risk_items) ? dashboard.value.risk_items : [])
const recentAlerts = computed(() => Array.isArray(alerts.value.recent) ? alerts.value.recent : [])
const alertProductRows = computed(() => Array.isArray(alerts.value.by_product) ? alerts.value.by_product : [])
const maxAlertProductTotal = computed(() => Math.max(...alertProductRows.value.map(item => toNumber(item.total)), 1))
const sourceHealthSummary = computed(() => {
  const summary = overview.value?.datasource_health?.summary || {}
  return {
    ok: toNumber(summary.ok),
    error: toNumber(summary.error),
    not_configured: toNumber(summary.not_configured),
    unknown: toNumber(summary.unknown),
  }
})
const ruleEngine = computed(() => overview.value?.rule_engine || {})
const sourceHealthTotal = computed(() => sourceHealthSummary.value.ok + sourceHealthSummary.value.error + sourceHealthSummary.value.not_configured + sourceHealthSummary.value.unknown)
const sourceHealthTone = computed(() => {
  if (sourceHealthSummary.value.error || toNumber(ruleEngine.value.failed_rules)) return 'danger'
  if (!sourceHealthTotal.value || sourceHealthSummary.value.not_configured || sourceHealthSummary.value.unknown) return 'warning'
  return 'success'
})
const sourceHealthTag = computed(() => {
  if (sourceHealthTone.value === 'danger') return '需处理'
  if (sourceHealthTone.value === 'warning') return '待完善'
  return '可用'
})
const sourceHealthHeadline = computed(() => {
  if (!sourceHealthTotal.value) return '未接入'
  return `${formatNumber(sourceHealthSummary.value.ok)}/${formatNumber(sourceHealthTotal.value)}`
})

const opsHealthScore = computed(() => {
  let score = 100
  if (sla.value.month_status === '风险') score -= 12
  if (sla.value.month_status === '未达标') score -= 28
  if (sla.value.annual_goal_status === '无法达成') score -= 12
  if (sourceHealthTone.value === 'danger') score -= 10
  if (sourceHealthTone.value === 'warning') score -= 4
  score -= Math.min(18, toNumber(alerts.value.unacknowledged) * 4)
  score -= Math.min(16, toNumber(workorders.value.overdue) * 4)
  score -= Math.min(12, toNumber(riskItems.value.length) * 3)
  return Math.max(0, Math.round(score))
})
const opsHealthTone = computed(() => {
  if (opsHealthScore.value < 70) return 'danger'
  if (opsHealthScore.value < 90) return 'warning'
  return 'success'
})
const opsHealthSummary = computed(() => {
  if (opsHealthTone.value === 'danger') return '存在高优先级风险，需要值班立即推进'
  if (opsHealthTone.value === 'warning') return '运行可控，但有风险项需要跟进'
  return '关键运行信号处于可控状态'
})

const workorderStatus = computed(() => {
  if (toNumber(workorders.value.overdue) > 0 || toNumber(workorders.value.timely_rate) < 90) return '未达标'
  if (toNumber(workorders.value.timely_rate) < 98) return '风险'
  return '达标'
})

const annualBudgetText = computed(() => {
  const minutes = toNumber(sla.value.annual_budget_remaining_minutes)
  if (minutes < 0) return `超出 ${formatMinutes(Math.abs(minutes))}`
  return formatMinutes(minutes)
})

const hostOnlineRate = computed(() => {
  const total = toNumber(hosts.value.total)
  if (!total) return 100
  return (toNumber(hosts.value.online) / total) * 100
})

const heroFacts = computed(() => [
  { label: '产品域', value: formatNumber(productSlaRows.value.length || 5) },
  { label: '本月告警', value: formatNumber(alerts.value.month_total) },
  { label: '未确认', value: formatNumber(alerts.value.unacknowledged) },
])

const headlineMetrics = computed(() => [
  {
    key: 'month-sla',
    label: '本月实际 SLA',
    value: formatPercent(sla.value.month_sla),
    helper: `${sla.value.downtime_basis || '灾难级告警持续时长'} ${formatMinutes(sla.value.month_downtime_minutes)}`,
    tone: statusTone(sla.value.month_status),
  },
  {
    key: 'annual-forecast',
    label: '年度达成预测',
    value: sla.value.annual_goal_status || '预计达成',
    helper: `预测 ${formatPercent(sla.value.annual_forecast_sla)} / 累计 ${formatPercent(sla.value.annual_sla_to_date)}`,
    tone: statusTone(sla.value.annual_goal_status),
  },
  {
    key: 'budget-left',
    label: '剩余 SLA 预算',
    value: annualBudgetText.value,
    helper: `年度灾难级时长 ${formatMinutes(sla.value.annual_downtime_minutes)}`,
    tone: toNumber(sla.value.annual_budget_remaining_minutes) < 0 ? 'danger' : 'success',
  },
  {
    key: 'alert-pressure',
    label: '未确认告警',
    value: formatNumber(alerts.value.unacknowledged),
    helper: `严重 ${formatNumber(alerts.value.month_critical)} / 警告 ${formatNumber(alerts.value.month_warning)}`,
    tone: toNumber(alerts.value.unacknowledged) ? 'danger' : 'success',
  },
  {
    key: 'task-closure',
    label: '任务及时率',
    value: formatPercent(workorders.value.timely_rate),
    helper: `超时 ${formatNumber(workorders.value.overdue)} / 待处理 ${formatNumber(workorders.value.pending)}`,
    tone: statusTone(workorderStatus.value),
  },
  {
    key: 'source-health',
    label: '观测接入健康',
    value: sourceHealthHeadline.value,
    helper: `异常 ${formatNumber(sourceHealthSummary.value.error)} / 规则失败 ${formatNumber(ruleEngine.value.failed_rules)}`,
    tone: sourceHealthTone.value,
  },
])

const operationLanes = computed(() => [
  {
    key: 'slo',
    title: 'SLA 与预算',
    value: formatPercent(sla.value.month_sla),
    tag: sla.value.month_status || '达标',
    helper: `年度预测 ${formatPercent(sla.value.annual_forecast_sla)}，预算剩余 ${annualBudgetText.value}`,
    tone: statusTone(sla.value.month_status),
    icon: DataLine,
    route: '/observability/overview',
  },
  {
    key: 'alerts',
    title: '告警压力',
    value: formatNumber(alerts.value.unacknowledged),
    tag: '未确认',
    helper: `本月 ${formatNumber(alerts.value.month_total)} 条，严重 ${formatNumber(alerts.value.month_critical)} 条`,
    tone: toNumber(alerts.value.unacknowledged) ? 'danger' : 'success',
    icon: Warning,
    route: '/observability/alerts',
  },
  {
    key: 'tasks',
    title: '任务闭环',
    value: formatPercent(workorders.value.timely_rate),
    tag: workorderStatus.value,
    helper: `本月工单 ${formatNumber(workorders.value.total)}，超时 ${formatNumber(workorders.value.overdue)}`,
    tone: statusTone(workorderStatus.value),
    icon: Finished,
    route: '/tasks/workbench',
  },
  {
    key: 'sources',
    title: '证据源健康',
    value: sourceHealthHeadline.value,
    tag: sourceHealthTag.value,
    helper: `可用 ${formatNumber(sourceHealthSummary.value.ok)}，异常 ${formatNumber(sourceHealthSummary.value.error)}，未接入 ${formatNumber(sourceHealthSummary.value.not_configured)}`,
    tone: sourceHealthTone.value,
    icon: Connection,
    route: '/observability/overview',
  },
])

const workorderMetrics = computed(() => [
  {
    key: 'total',
    label: '本月工单',
    value: formatNumber(workorders.value.total),
    helper: `发布 ${formatNumber(workorders.value.deployments)} / 事务 ${formatNumber(workorders.value.transaction_tickets)}`,
    tone: 'info',
  },
  {
    key: 'done',
    label: '已完成',
    value: formatNumber(workorders.value.done),
    helper: `待处理 ${formatNumber(workorders.value.pending)}`,
    tone: 'success',
  },
  {
    key: 'overdue',
    label: '超时',
    value: formatNumber(workorders.value.overdue),
    helper: '超过 24 小时未闭环',
    tone: toNumber(workorders.value.overdue) ? 'danger' : 'success',
  },
  {
    key: 'failed',
    label: '失败发布',
    value: formatNumber(workorders.value.failed),
    helper: '纳入稳定性风险',
    tone: toNumber(workorders.value.failed) ? 'warning' : 'success',
  },
])

const alertLevelMetrics = computed(() => [
  { key: 'total', label: '本月告警', value: formatNumber(alerts.value.month_total), tone: 'info' },
  { key: 'critical', label: '严重', value: formatNumber(alerts.value.month_critical), tone: toNumber(alerts.value.month_critical) ? 'danger' : 'success' },
  { key: 'warning', label: '警告', value: formatNumber(alerts.value.month_warning), tone: toNumber(alerts.value.month_warning) ? 'warning' : 'success' },
  { key: 'unacknowledged', label: '未确认', value: formatNumber(alerts.value.unacknowledged), tone: toNumber(alerts.value.unacknowledged) ? 'danger' : 'success' },
])

const sourceHealthItems = computed(() => [
  {
    key: 'ok',
    label: '可用数据源',
    value: formatNumber(sourceHealthSummary.value.ok),
    helper: '最近一次检测成功',
    tone: 'success',
  },
  {
    key: 'error',
    label: '异常数据源',
    value: formatNumber(sourceHealthSummary.value.error),
    helper: '需要检查连接或凭据',
    tone: sourceHealthSummary.value.error ? 'danger' : 'success',
  },
  {
    key: 'not-configured',
    label: '未接入',
    value: formatNumber(sourceHealthSummary.value.not_configured),
    helper: '测试环境不伪造数据',
    tone: sourceHealthSummary.value.not_configured ? 'warning' : 'success',
  },
  {
    key: 'rule-failed',
    label: '规则失败',
    value: formatNumber(ruleEngine.value.failed_rules),
    helper: ruleEngine.value.last_scan_at ? `扫描 ${formatDateTime(ruleEngine.value.last_scan_at)}` : '等待调度器扫描',
    tone: toNumber(ruleEngine.value.failed_rules) ? 'danger' : 'info',
  },
])

const infraMetrics = computed(() => [
  {
    key: 'hosts',
    label: '主机在线率',
    value: formatPercent(hostOnlineRate.value),
    helper: `在线 ${formatNumber(hosts.value.online)} / 总数 ${formatNumber(hosts.value.total)}`,
  },
  {
    key: 'host-warning',
    label: '异常主机',
    value: formatNumber(toNumber(hosts.value.offline) + toNumber(hosts.value.warning)),
    helper: `离线 ${formatNumber(hosts.value.offline)} / 告警 ${formatNumber(hosts.value.warning)}`,
  },
  {
    key: 'resource',
    label: '资源均值',
    value: `${formatNumber(hosts.value.avg_cpu)}% / ${formatNumber(hosts.value.avg_memory)}%`,
    helper: `CPU / 内存，磁盘 ${formatNumber(hosts.value.avg_disk)}%`,
  },
  {
    key: 'deployments',
    label: '应用发布',
    value: formatNumber(deployments.value.total),
    helper: `成功 ${formatNumber(deployments.value.success)} / 失败 ${formatNumber(deployments.value.failed)} / 运行 ${formatNumber(deployments.value.running)}`,
  },
])

function toNumber(value) {
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue : 0
}

function formatNumber(value) {
  return Math.round(toNumber(value)).toLocaleString('zh-CN')
}

function trimNumber(value, digits = 1) {
  return Number(value.toFixed(digits)).toLocaleString('zh-CN')
}

function formatPercent(value) {
  const numberValue = toNumber(value)
  const digits = numberValue >= 99 ? 4 : 1
  return `${Number(numberValue.toFixed(digits)).toLocaleString('zh-CN')}%`
}

function formatMinutes(value) {
  const minutes = Math.abs(toNumber(value))
  if (minutes >= 1440) return `${trimNumber(minutes / 1440, 1)} 天`
  if (minutes >= 60) return `${trimNumber(minutes / 60, 1)} 小时`
  return `${trimNumber(minutes, 1)} 分钟`
}

function barWidth(value) {
  const numberValue = Math.max(0, Math.min(100, toNumber(value)))
  return `${numberValue}%`
}

function alertProductBarWidth(value) {
  const percent = (toNumber(value) / maxAlertProductTotal.value) * 100
  return `${Math.max(8, Math.min(100, percent))}%`
}

function statusTone(status) {
  if (['未达标', '无法达成'].includes(status)) return 'danger'
  if (['风险', '存在风险'].includes(status)) return 'warning'
  if (['达标', '预计达成'].includes(status)) return 'success'
  return 'info'
}

function statusColor(status) {
  const tone = statusTone(status)
  if (tone === 'danger') return '#dc2626'
  if (tone === 'warning') return '#d97706'
  if (tone === 'success') return '#16a34a'
  return '#2563eb'
}

function statusTagType(status) {
  return tagTypeFromTone(statusTone(status))
}

function tagTypeFromTone(tone) {
  if (tone === 'danger') return 'danger'
  if (tone === 'warning') return 'warning'
  if (tone === 'success') return 'success'
  return 'info'
}

function riskTone(level) {
  if (level === 'critical') return 'danger'
  if (level === 'warning') return 'warning'
  return 'info'
}

function riskLevelText(level) {
  if (level === 'critical') return '高'
  if (level === 'warning') return '中'
  return '低'
}

function alertLevelLabel(level) {
  if (level === 'critical') return '严重'
  if (level === 'warning') return '警告'
  return '提示'
}

function alertLevelTagType(level) {
  if (level === 'critical') return 'danger'
  if (level === 'warning') return 'warning'
  return 'info'
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

const lastUpdatedText = computed(() => {
  if (!lastUpdatedAt.value) return '尚未刷新'
  return `刷新于 ${formatDateTime(lastUpdatedAt.value)}`
})

async function loadDashboard() {
  loading.value = true
  try {
    const [dashboardResult, overviewResult] = await Promise.allSettled([
      getDashboardStats(),
      getObservabilityOverview(),
    ])
    if (dashboardResult.status === 'fulfilled') dashboard.value = dashboardResult.value || {}
    if (overviewResult.status === 'fulfilled') overview.value = overviewResult.value || {}
    lastUpdatedAt.value = new Date()
  } finally {
    loading.value = false
  }
}

function go(path) {
  router.push(path)
}

onMounted(loadDashboard)
</script>

<style scoped>
.dashboard-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.ops-hero,
.headline-card,
.lane-card,
.ops-panel {
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #fff;
}

.ops-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, 240px) auto;
  gap: 14px;
  align-items: stretch;
  padding: 16px;
}

.hero-copy {
  min-width: 0;
}

.eyebrow {
  color: #2563eb;
  font-size: 12px;
  font-weight: 800;
}

.hero-copy h1 {
  margin: 5px 0 6px;
  color: #111827;
  font-size: 24px;
  font-weight: 850;
  line-height: 1.2;
  letter-spacing: 0;
}

.hero-copy p,
.panel-head p {
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.hero-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.hero-facts span {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  min-height: 26px;
  padding: 0 9px;
  border: 1px solid #e5ecf6;
  border-radius: 999px;
  background: #f8fafc;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.hero-facts strong {
  color: #111827;
  font-size: 13px;
}

.ops-score {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
  border: 1px solid #e5ecf6;
  border-left-width: 4px;
  border-radius: 8px;
  background: #f8fafc;
  padding: 12px;
}

.ops-score span,
.headline-card span,
.mini-tile span,
.infra-row span {
  display: block;
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
}

.ops-score strong {
  margin-top: 6px;
  color: #111827;
  font-size: 40px;
  font-weight: 900;
  line-height: 1;
}

.ops-score small,
.headline-card small,
.mini-tile small,
.lane-card small,
.infra-row small {
  display: block;
  margin-top: 7px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

.hero-actions {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  justify-content: center;
  gap: 8px;
  min-width: 138px;
}

.refresh-time {
  color: #64748b;
  font-size: 12px;
  text-align: right;
}

.headline-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}

.headline-card {
  min-height: 104px;
  padding: 12px;
  border-left-width: 4px;
}

.headline-card strong {
  display: block;
  overflow-wrap: anywhere;
  margin-top: 9px;
  color: #111827;
  font-size: 22px;
  font-weight: 850;
  line-height: 1.15;
}

.control-lanes {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.lane-card {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-width: 0;
  min-height: 84px;
  padding: 11px;
  border-left-width: 4px;
  text-align: left;
  cursor: pointer;
}

.lane-card:hover {
  border-color: #bfdbfe;
  background: #f8fbff;
}

.lane-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: #eef4ff;
  color: #2563eb;
}

.lane-body {
  min-width: 0;
}

.lane-title {
  display: block;
  color: #111827;
  font-size: 13px;
  font-weight: 850;
}

.lane-card strong {
  display: block;
  overflow-wrap: anywhere;
  margin-top: 5px;
  color: #111827;
  font-size: 20px;
  font-weight: 850;
  line-height: 1.15;
}

.tone-success {
  border-left-color: #16a34a;
}

.tone-warning {
  border-left-color: #d97706;
}

.tone-danger {
  border-left-color: #dc2626;
}

.tone-info {
  border-left-color: #2563eb;
}

.ops-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.18fr) minmax(320px, 0.82fr);
  gap: 12px;
  align-items: start;
}

.ops-panel {
  min-width: 0;
  padding: 14px;
}

.product-panel,
.risk-panel {
  grid-column: 1 / -1;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.panel-title {
  display: block;
  color: #111827;
  font-size: 14px;
  font-weight: 850;
}

.product-table {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.product-header,
.product-row {
  display: grid;
  grid-template-columns: minmax(120px, 1.2fr) minmax(150px, 1fr) 86px 104px 112px 64px;
  gap: 10px;
  align-items: center;
}

.product-header {
  padding: 0 10px;
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
}

.product-row {
  min-height: 60px;
  padding: 10px;
  border: 1px solid #e5ecf6;
  border-radius: 8px;
  background: #f8fafc;
}

.product-name strong,
.rank-row strong,
.recent-alert-row strong,
.risk-item strong {
  display: block;
  min-width: 0;
  overflow: hidden;
  color: #111827;
  font-size: 13px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.product-name span,
.rank-row span,
.recent-alert-row span {
  display: block;
  min-width: 0;
  overflow: hidden;
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.product-sla {
  display: grid;
  grid-template-columns: minmax(70px, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.product-sla strong,
.numeric {
  color: #111827;
  font-size: 13px;
  font-weight: 800;
}

.numeric span {
  color: #dc2626;
  font-weight: 800;
}

.progress-line {
  overflow: hidden;
  height: 7px;
  border-radius: 999px;
  background: #e5ecf6;
}

.progress-line span {
  display: block;
  width: var(--bar-width);
  height: 100%;
  border-radius: inherit;
  background: var(--bar-color);
}

.tile-grid {
  display: grid;
  gap: 8px;
}

.two-columns {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.mini-tile {
  min-width: 0;
  min-height: 74px;
  border: 1px solid #e5ecf6;
  border-left-width: 4px;
  border-radius: 8px;
  background: #f8fafc;
  padding: 10px;
}

.mini-tile strong {
  display: block;
  margin-top: 7px;
  color: #111827;
  font-size: 22px;
  font-weight: 850;
  line-height: 1.1;
}

.rank-list,
.infra-list,
.risk-list,
.recent-alerts {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rank-list {
  margin-top: 12px;
}

.rank-row {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) minmax(80px, 0.8fr) auto;
  gap: 10px;
  align-items: center;
  min-height: 48px;
  padding: 9px 10px;
  border: 1px solid #e5ecf6;
  border-radius: 8px;
  background: #f8fafc;
}

.rank-row em {
  color: #111827;
  font-size: 13px;
  font-style: normal;
  font-weight: 850;
}

.single-progress {
  margin-top: 12px;
}

.single-progress > div:first-child {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
  color: #111827;
  font-size: 12px;
  font-weight: 850;
}

.infra-row {
  display: grid;
  grid-template-columns: minmax(92px, 0.55fr) minmax(86px, 0.45fr) minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  min-height: 46px;
  padding: 9px 10px;
  border: 1px solid #e5ecf6;
  border-radius: 8px;
  background: #f8fafc;
}

.infra-row strong {
  color: #111827;
  font-size: 17px;
  font-weight: 850;
}

.risk-alert-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.05fr);
  gap: 12px;
}

.risk-item {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 10px;
  padding: 10px;
  border: 1px solid #e5ecf6;
  border-left-width: 4px;
  border-radius: 8px;
  background: #f8fafc;
}

.risk-item > span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #fff;
  color: #111827;
  font-size: 12px;
  font-weight: 850;
}

.risk-item p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.recent-alert-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-height: 50px;
  padding: 9px 10px;
  border: 1px solid #e5ecf6;
  border-radius: 8px;
  background: #f8fafc;
}

.recent-alert-row em {
  color: #64748b;
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 80px;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  color: #94a3b8;
  font-size: 12px;
}

.empty-state.compact {
  min-height: 54px;
}

@media (max-width: 1280px) {
  .headline-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .control-lanes {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1180px) {
  .ops-hero,
  .ops-layout,
  .risk-alert-grid {
    grid-template-columns: 1fr;
  }

  .hero-actions {
    flex-direction: row;
    flex-wrap: wrap;
    justify-content: flex-start;
  }

  .refresh-time {
    width: 100%;
    text-align: left;
  }
}

@media (max-width: 760px) {
  .headline-grid,
  .control-lanes,
  .two-columns {
    grid-template-columns: 1fr;
  }

  .panel-head {
    flex-direction: column;
  }

  .product-header {
    display: none;
  }

  .product-row {
    grid-template-columns: 1fr;
  }

  .product-cell {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
  }

  .product-cell::before {
    flex: 0 0 auto;
    color: #64748b;
    content: attr(data-label);
    font-size: 12px;
    font-weight: 800;
  }

  .product-sla,
  .rank-row,
  .recent-alert-row,
  .infra-row,
  .lane-card {
    grid-template-columns: 1fr;
  }

  .hero-actions {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
