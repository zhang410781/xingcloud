<template>
  <section class="panel alert-source-matrix">
    <div class="section-head">
      <div>
        <h3>告警来源</h3>
        <p>从监控对象、来源状态、模板和规则数量进入配置。</p>
      </div>
      <el-button size="small" :icon="RefreshRight" @click="$emit('refresh')">刷新</el-button>
    </div>

    <el-table :data="sources" size="small" stripe>
      <el-table-column prop="title" label="对象" min-width="150" />
      <el-table-column label="来源" min-width="160">
        <template #default="{ row }">
          <el-tag v-for="item in row.source_types || []" :key="item" size="small" class="matrix-tag" effect="plain">
            {{ sourceTypeText(item) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="120">
        <template #default="{ row }">
          <el-tag size="small" :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="template_count" label="模板" width="82" />
      <el-table-column prop="rule_count" label="规则" width="82" />
      <el-table-column prop="dashboard_count" label="看板" width="82" />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="$emit('create-rule', row)">创建规则</el-button>
          <el-button link size="small" @click="$emit('open-query', row)">打开查询</el-button>
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>

<script setup>
import { RefreshRight } from '@element-plus/icons-vue'

defineProps({
  sources: { type: Array, default: () => [] },
})

defineEmits(['refresh', 'create-rule', 'open-query'])

function sourceTypeText(value) {
  return {
    prometheus: 'Prometheus',
    clickhouse: 'ClickHouse',
    sla: 'SLA',
  }[value] || value
}

function statusText(value) {
  return {
    not_connected: '未接入',
    source_available: '来源可用',
    rules_installed: '规则已安装',
    dashboards_installed: '看板已安装',
  }[value] || value || '-'
}

function statusType(value) {
  return {
    not_connected: 'info',
    source_available: 'success',
    rules_installed: 'warning',
    dashboards_installed: 'primary',
  }[value] || 'info'
}
</script>

<style scoped>
.alert-source-matrix {
  display: grid;
  gap: 12px;
}

.section-head p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
}

.matrix-tag {
  margin-right: 6px;
}
</style>
