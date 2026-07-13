<template>
  <article class="integration-card">
    <div class="integration-card__head">
      <div class="integration-card__icon">
        <el-icon><component :is="integration.icon || 'DataLine'" /></el-icon>
      </div>
      <div class="integration-card__title">
        <strong>{{ integration.title }}</strong>
        <span>{{ categoryText(integration.category) }}</span>
      </div>
      <el-tag size="small" :type="statusType(integration.status)">{{ statusText(integration.status) }}</el-tag>
    </div>

    <div class="integration-card__meta">
      <span v-for="type in integration.source_types || []" :key="type">{{ sourceTypeText(type) }}</span>
    </div>

    <div class="integration-card__body">
      <div>
        <span>规则模板</span>
        <strong>{{ integration.template_count || 0 }}</strong>
      </div>
      <div>
        <span>已装规则</span>
        <strong>{{ integration.rule_count || 0 }}</strong>
      </div>
      <div>
        <span>看板</span>
        <strong>{{ integration.dashboard_count || 0 }}</strong>
      </div>
    </div>

    <div class="integration-card__tags">
      <el-tag v-for="tag in integration.tags || []" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
    </div>

    <div class="integration-card__actions">
      <el-button size="small" type="primary" :loading="installingRules" @click="$emit('install-rules', integration)">
        安装规则
      </el-button>
      <el-button size="small" :loading="installingDashboards" @click="$emit('install-dashboards', integration)">
        安装看板
      </el-button>
      <el-button size="small" link type="primary" @click="$emit('open-guide', integration)">文档</el-button>
    </div>
  </article>
</template>

<script setup>
defineProps({
  integration: { type: Object, required: true },
  installingRules: { type: Boolean, default: false },
  installingDashboards: { type: Boolean, default: false },
})

defineEmits(['install-rules', 'install-dashboards', 'open-guide'])

function categoryText(value) {
  return {
    middleware: '中间件',
    platform: '平台',
    infrastructure: '基础设施',
    logs: '日志',
    sla: 'SLA',
  }[value] || value || '可观测'
}

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
  }[value] || value || '未接入'
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
.integration-card {
  min-height: 236px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.04);
}

.integration-card__head {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
}

.integration-card__icon {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: #2563eb;
  background: #eff6ff;
}

.integration-card__title {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.integration-card__title strong {
  color: #0f172a;
  font-size: 15px;
}

.integration-card__title span,
.integration-card__body span {
  color: #64748b;
  font-size: 12px;
}

.integration-card__meta,
.integration-card__tags,
.integration-card__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.integration-card__meta span {
  padding: 4px 8px;
  border-radius: 999px;
  background: #f8fafc;
  color: #475569;
  font-size: 12px;
}

.integration-card__body {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.integration-card__body div {
  display: grid;
  gap: 4px;
  padding: 10px;
  border-radius: 8px;
  background: #f8fafc;
}

.integration-card__body strong {
  color: #0f172a;
  font-size: 18px;
}

.integration-card__actions {
  margin-top: auto;
}
</style>
