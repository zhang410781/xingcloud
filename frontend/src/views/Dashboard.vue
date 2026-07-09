<template>
  <div v-loading="loading" class="dashboard-page workbench-page-shell">
    <section class="cockpit-header">
      <div class="header-copy">
        <span class="eyebrow">运行概览</span>
        <h1>{{ cockpitTitle }}</h1>
        <p>本月 SLA、年度 99.96% 达成预测、产品稳定性、工单及时性、告警与风险项。</p>
      </div>
      <div class="header-actions">
        <span class="refresh-time">{{ lastUpdatedText }}</span>
        <el-button size="small" plain :loading="loading" @click="loadDashboard">
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

    <section class="cockpit-layout">
      <div class="cockpit-panel product-panel">
        <div class="panel-head">
          <div>
            <span class="panel-title">各产品 SLA</span>
            <p>数据库、中间件、容器平台、网络、服务器本月稳定性。</p>
          </div>
          <el-tag size="small" effect="plain">目标 {{ formatPercent(sla.target) }}</el-tag>
        </div>

        <div class="product-table">
          <div class="product-header">
            <span>产品</span>
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
            <div class="product-cell numeric" data-label="故障时长">{{ formatMinutes(item.downtime_minutes) }}</div>
            <div class="product-cell numeric" data-label="告警">
              {{ formatNumber(item.alerts) }}
              <span v-if="item.critical_alerts"> / 严重 {{ formatNumber(item.critical_alerts) }}</span>
            </div>
            <div class="product-cell numeric" data-label="风险">{{ formatNumber(item.risk_count) }}</div>
          </div>
          <div v-if="!productSlaRows.length" class="empty-state">暂无产品 SLA 数据</div>
        </div>
      </div>

      <div class="cockpit-panel workorder-panel">
        <div class="panel-head">
          <div>
            <span class="panel-title">工单及时性</span>
            <p>本月发布工单与事务工单闭环情况。</p>
          </div>
        </div>
        <div class="stat-grid">
          <div v-for="item in workorderMetrics" :key="item.key" class="stat-tile" :class="`tone-${item.tone}`">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small>{{ item.helper }}</small>
          </div>
        </div>
        <div class="timely-line">
          <div class="timely-head">
            <span>及时处理率</span>
            <strong>{{ formatPercent(workorders.timely_rate) }}</strong>
          </div>
          <div class="progress-line" :style="{ '--bar-width': barWidth(workorders.timely_rate), '--bar-color': statusColor(workorderStatus) }">
            <span></span>
          </div>
        </div>
      </div>

      <div class="cockpit-panel alert-panel">
        <div class="panel-head">
          <div>
            <span class="panel-title">告警态势</span>
            <p>本月告警数量、级别分布与未确认告警。</p>
          </div>
        </div>
        <div class="alert-levels">
          <div v-for="item in alertLevelMetrics" :key="item.key" class="alert-level" :class="`tone-${item.tone}`">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
        <div class="alert-products">
          <div v-for="item in alertProductRows" :key="item.key" class="alert-product-row">
            <div>
              <strong>{{ item.product }}</strong>
              <span>严重 {{ formatNumber(item.critical) }} / 警告 {{ formatNumber(item.warning) }}</span>
            </div>
            <div class="progress-line" :style="{ '--bar-width': alertProductBarWidth(item.total), '--bar-color': '#2563eb' }">
              <span></span>
            </div>
            <em>{{ formatNumber(item.total) }}</em>
          </div>
          <div v-if="!alertProductRows.length" class="empty-state">暂无本月告警</div>
        </div>
      </div>

      <div class="cockpit-panel risk-panel">
        <div class="panel-head">
          <div>
            <span class="panel-title">风险项</span>
            <p>SLA、告警、工单与发布失败产生的管理风险。</p>
          </div>
          <el-tag size="small" :type="riskItems.length ? 'warning' : 'success'" effect="plain">
            {{ riskItems.length ? `${riskItems.length} 项` : '无风险' }}
          </el-tag>
        </div>
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
      </div>

      <div class="cockpit-panel recent-alert-panel">
        <div class="panel-head">
          <div>
            <span class="panel-title">告警明细</span>
            <p>本月最近需要关注的告警。</p>
          </div>
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
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { RefreshRight } from '@element-plus/icons-vue'
import { getDashboardStats } from '@/api/modules/ops'

const loading = ref(false)
const dashboard = ref({})
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
  annual_budget_remaining_minutes: 0,
}

const cockpitTitle = computed(() => dashboard.value?.cockpit_title || '智能运维平台驾驶舱')
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
const riskItems = computed(() => Array.isArray(dashboard.value?.risk_items) ? dashboard.value.risk_items : [])
const recentAlerts = computed(() => Array.isArray(alerts.value.recent) ? alerts.value.recent : [])
const alertProductRows = computed(() => Array.isArray(alerts.value.by_product) ? alerts.value.by_product : [])
const maxAlertProductTotal = computed(() => Math.max(...alertProductRows.value.map(item => toNumber(item.total)), 1))

const workorderStatus = computed(() => {
  if (toNumber(workorders.value.overdue) > 0 || toNumber(workorders.value.timely_rate) < 90) return '未达标'
  if (toNumber(workorders.value.timely_rate) < 98) return '风险'
  return '达标'
})

const headlineMetrics = computed(() => [
  {
    key: 'month-status',
    label: '本月 SLA 状态',
    value: sla.value.month_status || '达标',
    helper: `实际 ${formatPercent(sla.value.month_sla)} / 目标 ${formatPercent(sla.value.target)}`,
    tone: statusTone(sla.value.month_status),
  },
  {
    key: 'month-sla',
    label: '本月实际 SLA',
    value: formatPercent(sla.value.month_sla),
    helper: `${sla.value.downtime_basis || '灾难级告警持续时长'} ${formatMinutes(sla.value.month_downtime_minutes)}`,
    tone: statusTone(sla.value.month_status),
  },
  {
    key: 'annual-target',
    label: '年度目标',
    value: formatPercent(sla.value.target),
    helper: '年度期望 99.96%',
    tone: 'info',
  },
  {
    key: 'annual-forecast',
    label: '年度达成预测',
    value: sla.value.annual_goal_status || '预计达成',
    helper: `预测 ${formatPercent(sla.value.annual_forecast_sla)}`,
    tone: statusTone(sla.value.annual_goal_status),
  },
  {
    key: 'annual-to-date',
    label: '年度累计 SLA',
    value: formatPercent(sla.value.annual_sla_to_date),
    helper: `年度灾难级时长 ${formatMinutes(sla.value.annual_downtime_minutes)}`,
    tone: statusTone(sla.value.annual_goal_status),
  },
  {
    key: 'budget-left',
    label: '剩余 SLA 预算',
    value: annualBudgetText.value,
    helper: '按年度目标折算',
    tone: toNumber(sla.value.annual_budget_remaining_minutes) < 0 ? 'danger' : 'success',
  },
])

const annualBudgetText = computed(() => {
  const minutes = toNumber(sla.value.annual_budget_remaining_minutes)
  if (minutes < 0) return `超出 ${formatMinutes(Math.abs(minutes))}`
  return formatMinutes(minutes)
})

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
    label: '超时工单',
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
  const tone = statusTone(status)
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
  })
}

const lastUpdatedText = computed(() => {
  if (!lastUpdatedAt.value) return '尚未刷新'
  return `刷新于 ${formatDateTime(lastUpdatedAt.value)}`
})

async function loadDashboard() {
  loading.value = true
  try {
    dashboard.value = await getDashboardStats() || {}
    lastUpdatedAt.value = new Date()
  } finally {
    loading.value = false
  }
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

.cockpit-header,
.cockpit-panel,
.headline-card {
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #fff;
}

.cockpit-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
}

.header-copy {
  min-width: 0;
}

.eyebrow {
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
}

.header-copy h1 {
  margin: 5px 0 6px;
  color: #111827;
  font-size: 22px;
  font-weight: 800;
  line-height: 1.2;
  letter-spacing: 0;
}

.header-copy p,
.panel-head p {
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.header-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
}

.refresh-time {
  color: #64748b;
  font-size: 12px;
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

.headline-card span,
.stat-tile span,
.alert-level span {
  display: block;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.headline-card strong {
  display: block;
  overflow-wrap: anywhere;
  margin-top: 10px;
  color: #111827;
  font-size: 23px;
  font-weight: 800;
  line-height: 1.15;
}

.headline-card small,
.stat-tile small {
  display: block;
  margin-top: 8px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.4;
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

.cockpit-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(340px, 0.9fr);
  gap: 12px;
  align-items: start;
}

.cockpit-panel {
  min-width: 0;
  padding: 14px;
}

.product-panel,
.recent-alert-panel {
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
  font-weight: 800;
}

.product-table {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.product-header,
.product-row {
  display: grid;
  grid-template-columns: minmax(120px, 1.2fr) minmax(150px, 1fr) 86px 96px 110px 64px;
  gap: 10px;
  align-items: center;
}

.product-header {
  padding: 0 10px;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.product-row {
  min-height: 60px;
  padding: 10px;
  border: 1px solid #e5ecf6;
  border-radius: 8px;
  background: #f8fafc;
}

.product-name strong,
.alert-product-row strong,
.recent-alert-row strong,
.risk-item strong {
  display: block;
  min-width: 0;
  overflow: hidden;
  color: #111827;
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.product-name span,
.alert-product-row span,
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

.product-sla strong {
  color: #111827;
  font-size: 13px;
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

.numeric {
  color: #111827;
  font-size: 13px;
  font-weight: 700;
}

.numeric span {
  color: #dc2626;
  font-weight: 700;
}

.stat-grid,
.alert-levels {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.stat-tile,
.alert-level {
  min-width: 0;
  border: 1px solid #e5ecf6;
  border-left-width: 4px;
  border-radius: 8px;
  background: #f8fafc;
  padding: 10px;
}

.stat-tile strong,
.alert-level strong {
  display: block;
  margin-top: 8px;
  color: #111827;
  font-size: 22px;
  font-weight: 800;
}

.timely-line {
  margin-top: 12px;
}

.timely-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
  color: #111827;
  font-size: 12px;
  font-weight: 800;
}

.alert-products,
.risk-list,
.recent-alerts {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

.alert-product-row {
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

.alert-product-row em {
  color: #111827;
  font-size: 13px;
  font-style: normal;
  font-weight: 800;
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
  font-weight: 800;
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
  font-weight: 700;
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

@media (max-width: 1180px) {
  .headline-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .cockpit-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .cockpit-header,
  .panel-head {
    flex-direction: column;
  }

  .header-actions {
    width: 100%;
    justify-content: space-between;
  }

  .headline-grid,
  .stat-grid,
  .alert-levels {
    grid-template-columns: 1fr;
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
    font-weight: 700;
  }

  .product-sla {
    grid-template-columns: minmax(100px, 1fr) auto;
  }

  .alert-product-row,
  .recent-alert-row {
    grid-template-columns: 1fr;
  }
}
</style>
