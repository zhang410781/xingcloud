<template>
  <div class="data-sources-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><DataBoard /></el-icon></span>
          <div>
            <h2>数据源</h2>
            <p>统一维护指标和日志数据源，并在保存前完成连接验证。</p>
          </div>
        </div>
      </div>
    </section>

    <ObservabilityRouteTabs group="datasources" />

    <el-tabs v-model="activeTab" class="data-source-tabs">
      <el-tab-pane label="指标数据源" name="metrics">
        <MetricsQuery embedded initial-tab="datasources" />
      </el-tab-pane>
      <el-tab-pane label="日志数据源" name="logs">
        <LogDataSources embedded />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { DataBoard } from '@element-plus/icons-vue'
import ObservabilityRouteTabs from '@/components/observability/ObservabilityRouteTabs.vue'
import MetricsQuery from './MetricsQuery.vue'
import LogDataSources from './LogDataSources.vue'

const activeTab = ref('metrics')
</script>

<style scoped>
.data-sources-page {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 100%;
}

.hero {
  display: flex;
  align-items: center;
  min-height: 72px;
  padding: 14px 16px;
}

.hero-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.hero-icon {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 8px;
  color: #2563eb;
  background: #eff6ff;
}

h2, p {
  margin: 0;
}

h2 { font-size: 18px; color: #0f172a; }
p { margin-top: 4px; color: #64748b; font-size: 13px; }

.data-source-tabs :deep(.el-tabs__header) { margin-bottom: 10px; }
</style>
