<template>
  <div class="observability-page workbench-page-shell">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Share /></el-icon></span>
          <h2>平台总览</h2>
          <span class="page-inline-desc">统一查看监控看板、日志中心与告警中心的接入状态。</span>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :loading="loading" @click="loadOverview">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
      </div>
    </section>

    <div class="audit-grid">
      <div v-for="card in capabilityCards" :key="card.label" class="audit-card audit-card--inline" :class="card.tone">
        <div class="stat-value">{{ card.value }}</div>
        <div class="stat-label">{{ card.label }}</div>
      </div>
    </div>

    <section class="workbench-card datasource-config-panel">
      <div class="section-toolbar">
        <div class="toolbar-head">
          <span class="toolbar-title">数据源配置</span>
          <span class="toolbar-desc">从这里维护可观测性接入源，日志、指标和告警统一进入平台能力。</span>
        </div>
        <el-button size="small" :loading="loading" @click="loadOverview">
          <el-icon><RefreshRight /></el-icon>
          刷新状态
        </el-button>
      </div>

      <div class="datasource-grid">
        <button
          v-for="item in datasourceCards"
          :key="item.key"
          type="button"
          class="datasource-card"
          :class="item.tone"
          @click="openDatasourceConfig(item)"
        >
          <span class="datasource-card__icon">
            <el-icon><component :is="item.icon" /></el-icon>
          </span>
          <span class="datasource-card__body">
            <span class="datasource-card__title">{{ item.title }}</span>
            <span class="datasource-card__desc">{{ item.description }}</span>
            <span class="datasource-card__meta">
              <span>总数 {{ item.total }}</span>
              <span>启用 {{ item.enabled }}</span>
            </span>
          </span>
          <span class="datasource-card__action">配置</span>
        </button>
      </div>
    </section>

  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Connection, DataAnalysis, DataBoard, RefreshRight, Share } from '@element-plus/icons-vue'
import { getAlertRules, getLogDataSources, getMetricDataSources, getObservabilityOverview } from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const overview = ref({ modules: {}, summary: {} })
const logDataSources = ref([])
const metricDataSources = ref([])
const alertRules = ref([])

const capabilityCards = computed(() => [
  {
    label: '监控看板',
    value: overview.value.modules?.dashboards?.dashboard_count || 0,
    tone: '',
  },
  {
    label: '日志数据源',
    value: overview.value.modules?.logs?.datasource_count || 0,
    tone: 'audit-card--success',
  },
  {
    label: '未确认告警',
    value: overview.value.modules?.alerts?.unacknowledged || 0,
    tone: 'audit-card--danger',
  },
])

function listOf(response) {
  if (Array.isArray(response)) return response
  if (Array.isArray(response?.results)) return response.results
  return []
}

const datasourceCards = computed(() => [
  {
    key: 'logs',
    title: '日志数据源',
    description: '配置 ClickHouse、Loki、ELK 等日志检索入口。',
    icon: DataBoard,
    tone: 'is-log',
    total: logDataSources.value.length || overview.value.modules?.logs?.datasource_count || 0,
    enabled: logDataSources.value.filter(item => item.is_enabled).length || overview.value.modules?.logs?.enabled_count || 0,
    route: '/logs/datasources',
  },
  {
    key: 'metrics',
    title: '指标数据源',
    description: '配置 Prometheus 兼容指标查询源，用于监控看板和指标证据。',
    icon: DataAnalysis,
    tone: 'is-metric',
    total: metricDataSources.value.length || overview.value.modules?.metrics?.datasource_count || 0,
    enabled: metricDataSources.value.filter(item => item.is_enabled).length || overview.value.modules?.metrics?.enabled_count || 0,
    route: { path: '/observability/metrics', query: { tab: 'datasources' } },
  },
  {
    key: 'alerts',
    title: '告警规则',
    description: '配置 Prometheus、ClickHouse、K8S 和 SLA 等平台主动告警规则。',
    icon: Connection,
    tone: 'is-alert',
    total: alertRules.value.length,
    enabled: alertRules.value.filter(item => item.is_enabled).length,
    route: { path: '/alerts', query: { tab: 'rules' } },
  },
])

function openDatasourceConfig(item) {
  router.push(item.route)
}

async function loadOverview() {
  loading.value = true
  try {
    const tasks = [
      getObservabilityOverview(),
      authStore.hasPermission('ops.log.datasource.view') ? getLogDataSources() : Promise.resolve([]),
      authStore.hasPermission('ops.metric.datasource.view') ? getMetricDataSources() : Promise.resolve([]),
      authStore.hasPermission('ops.alert.config.view') ? getAlertRules() : Promise.resolve([]),
    ]
    const [overviewResult, logsResult, metricsResult, alertsResult] = await Promise.allSettled(tasks)
    if (overviewResult.status === 'fulfilled') overview.value = overviewResult.value
    if (logsResult.status === 'fulfilled') logDataSources.value = listOf(logsResult.value)
    if (metricsResult.status === 'fulfilled') metricDataSources.value = listOf(metricsResult.value)
    if (alertsResult.status === 'fulfilled') alertRules.value = listOf(alertsResult.value)
  } finally {
    loading.value = false
  }
}

onMounted(loadOverview)
</script>

<style scoped>
.observability-page {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.panel {
  background: linear-gradient(135deg, #fbfdff 0%, #f7faff 52%, #f9fbfd 100%);
  border: 1px solid rgba(36, 91, 219, 0.09);
  border-radius: 20px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
  padding: 14px 16px;
}

.hero {
  align-items: center;
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.hero-title-row {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.hero-icon {
  align-items: center;
  background: rgba(51, 112, 255, 0.1);
  border-radius: 14px;
  color: #245bdb;
  display: inline-flex;
  height: 42px;
  justify-content: center;
  width: 42px;
}

.observability-page h2 {
  color: #0f172a;
  font-size: 23px;
  margin: 0;
}

.page-inline-desc {
  color: #475569;
  font-size: 13px;
}

.audit-grid {
  display: grid;
  gap: 6px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.datasource-config-panel {
  padding: 14px 16px 16px;
}

.section-toolbar {
  align-items: center;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.toolbar-head {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.toolbar-title {
  color: #0f172a;
  font-size: 15px;
  font-weight: 700;
}

.toolbar-desc {
  color: #64748b;
  font-size: 12px;
}

.datasource-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.datasource-card {
  align-items: flex-start;
  background: #ffffff;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  gap: 10px;
  min-height: 124px;
  padding: 14px;
  text-align: left;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.datasource-card:hover {
  border-color: rgba(51, 112, 255, 0.28);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.06);
  transform: translateY(-1px);
}

.datasource-card__icon {
  align-items: center;
  border-radius: 8px;
  display: inline-flex;
  flex: 0 0 auto;
  height: 34px;
  justify-content: center;
  width: 34px;
}

.datasource-card.is-log .datasource-card__icon {
  background: rgba(16, 185, 129, 0.1);
  color: #059669;
}

.datasource-card.is-metric .datasource-card__icon {
  background: rgba(59, 130, 246, 0.1);
  color: #2563eb;
}

.datasource-card.is-alert .datasource-card__icon {
  background: rgba(239, 68, 68, 0.1);
  color: #dc2626;
}

.datasource-card__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.datasource-card__title {
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
}

.datasource-card__desc {
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.datasource-card__meta {
  color: #475569;
  display: flex;
  flex-wrap: wrap;
  font-size: 12px;
  gap: 8px;
  margin-top: auto;
}

.datasource-card__action {
  color: #2563eb;
  flex: 0 0 auto;
  font-size: 12px;
  font-weight: 700;
}

.hero-actions :deep(.el-button) {
  border-radius: 10px;
  font-weight: 500;
  min-height: 32px;
  padding: 0 14px;
}

@media (max-width: 900px) {
  .audit-grid,
  .datasource-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .section-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 560px) {
  .hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .audit-grid,
  .datasource-grid {
    grid-template-columns: 1fr;
  }
}
</style>
