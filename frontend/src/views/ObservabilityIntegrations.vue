<template>
  <div class="observability-integrations workbench-page-shell">
    <section class="hero panel integrations-hero">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Connection /></el-icon></span>
          <h2>监控集成</h2>
          <p class="page-inline-desc">统一管理 Prometheus、ClickHouse、SLA 与中间件监控对象。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :icon="RefreshRight" :loading="loading" @click="loadIntegrations">刷新</el-button>
        <el-button size="small" type="primary" :icon="Histogram" @click="$router.push('/observability/dashboards')">打开看板</el-button>
      </div>
    </section>

    <ObservabilityRouteTabs group="observability" />

    <section class="panel integration-toolbar">
      <el-segmented v-model="category" :options="categoryOptions" size="small" />
      <el-input v-model="keyword" clearable size="small" placeholder="搜索 MySQL / Redis / Kafka" :prefix-icon="Search" />
    </section>

    <div v-loading="loading" class="integration-grid">
      <IntegrationCard
        v-for="item in filteredIntegrations"
        :key="item.key"
        :integration="item"
        :installing-rules="installingKey === `${item.key}:rules`"
        :installing-dashboards="installingKey === `${item.key}:dashboards`"
        @install-rules="installRules"
        @install-dashboards="installDashboards"
        @open-guide="openGuide"
      />
    </div>

    <el-empty v-if="!loading && !filteredIntegrations.length" description="暂无匹配集成" :image-size="92" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Histogram, RefreshRight, Search } from '@element-plus/icons-vue'
import ObservabilityRouteTabs from '@/components/observability/ObservabilityRouteTabs.vue'
import IntegrationCard from '@/components/observability/IntegrationCard.vue'
import {
  getObservabilityIntegrations,
  installIntegrationDashboards,
  installIntegrationRules,
} from '@/api/modules/ops'

const loading = ref(false)
const installingKey = ref('')
const integrations = ref([])
const category = ref('all')
const keyword = ref('')

const categoryOptions = [
  { label: '全部', value: 'all' },
  { label: '中间件', value: 'middleware' },
  { label: '平台', value: 'platform' },
  { label: '基础设施', value: 'infrastructure' },
  { label: '日志', value: 'logs' },
  { label: 'SLA', value: 'sla' },
]

const filteredIntegrations = computed(() => integrations.value.filter((item) => {
  const categoryOk = category.value === 'all' || item.category === category.value
  const text = `${item.title || ''} ${item.key || ''} ${(item.tags || []).join(' ')}`.toLowerCase()
  const keywordOk = !keyword.value || text.includes(keyword.value.toLowerCase())
  return categoryOk && keywordOk
}))

async function loadIntegrations() {
  loading.value = true
  try {
    const response = await getObservabilityIntegrations()
    integrations.value = response.integrations || []
  } finally {
    loading.value = false
  }
}

async function installRules(integration) {
  installingKey.value = `${integration.key}:rules`
  try {
    const result = await installIntegrationRules(integration.key, {
      template_codes: integration.template_codes || [],
    })
    ElMessage.success(`规则安装完成：新增 ${result.created_count || 0}，跳过 ${result.skipped_count || 0}`)
    await loadIntegrations()
  } finally {
    installingKey.value = ''
  }
}

async function installDashboards(integration) {
  installingKey.value = `${integration.key}:dashboards`
  try {
    const result = await installIntegrationDashboards(integration.key)
    ElMessage.success(`看板已启用：${result.enabled_count || 0} 个`)
    await loadIntegrations()
  } finally {
    installingKey.value = ''
  }
}

async function openGuide(integration) {
  await ElMessageBox.alert(integration.guide_path || '暂无文档路径', `${integration.title} 教学文档`, {
    confirmButtonText: '知道了',
  })
}

onMounted(loadIntegrations)
</script>

<style scoped>
.observability-integrations {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.integrations-hero,
.integration-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.integration-toolbar .el-input {
  width: 320px;
}

.integration-grid {
  min-height: 280px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}

@media (max-width: 760px) {
  .integrations-hero,
  .integration-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .integration-toolbar .el-input {
    width: 100%;
  }
}
</style>
