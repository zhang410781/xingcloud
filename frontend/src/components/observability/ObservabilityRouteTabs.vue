<template>
  <div v-if="visibleTabs.length" class="observability-route-tabs neo-tabs theme-blue">
    <button
      v-for="tab in visibleTabs"
      :key="tab.key"
      type="button"
      class="neo-tab-btn"
      :class="{ active: isActiveTab(tab) }"
      @click="goTab(tab)"
    >
      <el-icon><component :is="tab.icon" /></el-icon>
      <span>{{ tab.title }}</span>
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const props = defineProps({
  group: {
    type: String,
    default: 'observability',
  },
})

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const overviewPermissions = [
  'ops.dashboard.view',
  'ops.monitor.dashboard.view',
  'ops.metric.query',
  'ops.metric.datasource.view',
  'ops.log.query',
  'ops.log.datasource.view',
  'ops.alert.view',
  'ops.alert.config.view',
]

const mainTabs = [
  { key: 'overview', title: '总览', icon: 'DataLine', path: '/observability/overview', anyPermissions: overviewPermissions },
  { key: 'alerts', title: '告警中心', icon: 'Bell', path: '/observability/alerts', anyPermissions: ['ops.alert.view', 'ops.alert.config.view'] },
  { key: 'rules', title: '告警规则', icon: 'Operation', path: '/observability/rules', permission: 'ops.alert.config.view' },
  { key: 'dashboards', title: '监控看板', icon: 'Histogram', path: '/observability/dashboards', permission: 'ops.monitor.dashboard.view' },
  { key: 'metrics-query', title: '指标查询', icon: 'DataAnalysis', path: '/observability/metrics', permission: 'ops.metric.query' },
  { key: 'logs-query', title: '日志查询', icon: 'Search', path: '/observability/logs', permission: 'ops.log.query' },
  { key: 'datasources', title: '数据源', icon: 'DataBoard', path: '/observability/data-sources', anyPermissions: ['ops.metric.datasource.view', 'ops.log.datasource.view'] },
]

const tabGroups = {
  observability: mainTabs,
  boards: mainTabs,
  query: mainTabs,
  datasources: mainTabs,
}

function canAccess(tab) {
  if (tab.permission) return authStore.hasPermission(tab.permission)
  if (tab.anyPermissions) return authStore.hasAnyPermission(tab.anyPermissions)
  return true
}

const visibleTabs = computed(() => (tabGroups[props.group] || mainTabs).filter(canAccess))

function isActiveTab(tab) {
  return route.path === tab.path
}

function goTab(tab) {
  router.push({ path: tab.path, query: tab.query || {} })
}
</script>

<style scoped>
.observability-route-tabs {
  margin: 0;
}
</style>
