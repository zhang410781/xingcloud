<template>
  <section class="panel rule-template-catalog" :class="{ 'is-compact': compact }">
    <div v-if="!compact" class="section-head">
      <div>
        <h3>对象模板包</h3>
        <p>按监控对象组织告警规则模板，先从 K8S 和 Linux Server 示例开始创建规则。</p>
      </div>
      <div class="section-actions">
        <el-input v-model="keyword" size="small" clearable placeholder="搜索模板" />
        <el-select v-model="sourceType" size="small" clearable placeholder="数据源">
          <el-option label="Prometheus" value="prometheus" />
          <el-option label="ClickHouse" value="clickhouse" />
          <el-option label="K8S" value="k8s" />
        </el-select>
      </div>
    </div>

    <div class="bundle-grid">
      <article v-for="bundle in visibleBundles" :key="bundle.key" class="bundle-card">
        <div class="bundle-head">
          <div>
            <strong>{{ bundle.title }}</strong>
            <p>{{ bundle.description }}</p>
          </div>
          <el-tag size="small" effect="plain">{{ bundle.templates.length }} 条</el-tag>
        </div>
        <div class="bundle-meta">
          <el-tag v-for="item in bundle.sourceTypes" :key="item" size="small" class="mini-tag">{{ item }}</el-tag>
          <span>{{ bundle.dashboard }}</span>
        </div>
        <div class="template-list">
          <article v-for="item in bundle.templates" :key="item.id || item.code" class="template-row">
            <div class="template-main">
              <div class="template-title">
                <strong>{{ item.name }}</strong>
                <el-tag size="small" :type="levelType(item.level)">{{ levelText(item.level) }}</el-tag>
              </div>
              <p>{{ item.description || expressionSummary(item) }}</p>
              <small>
                {{ sourceTypeText(item.source_type) }}
                / {{ item.interval_seconds || 60 }}s
                / for {{ item.duration_seconds || 0 }}s
                / 通知 {{ item.notify_enabled ? '开启' : '关闭' }}
                / AIOps {{ item.auto_analyze ? '开启' : '关闭' }}
              </small>
            </div>
            <div class="template-actions">
              <el-button size="small" type="primary" @click="$emit('import-rule', item)">创建规则</el-button>
              <el-button size="small" @click="$emit('preview', item)">预览</el-button>
            </div>
          </article>
          <el-empty v-if="!bundle.templates.length" description="暂无匹配模板" :image-size="64" />
        </div>
      </article>
    </div>

    <el-empty v-if="!visibleBundles.length" description="暂无匹配模板包" :image-size="80" />
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  templates: { type: Array, default: () => [] },
  compact: { type: Boolean, default: false },
})

defineEmits(['import-rule', 'preview'])

const keyword = ref('')
const sourceType = ref('')

const BUNDLES = [
  {
    key: 'kubernetes',
    title: 'K8S',
    description: '节点 NotReady、异常 Pod、Pod 重启、K8S Events 异常',
    dashboard: '关联看板：K8S 集群健康 / K8S Events',
    codes: ['k8s-node-not-ready', 'k8s-abnormal-pods', 'k8s-pod-restarts', 'k8s-events-warning'],
  },
  {
    key: 'linux',
    title: 'Linux Server',
    description: '主机 Down、CPU 高、内存高、磁盘高',
    dashboard: '关联看板：Linux Server Resources',
    codes: ['linux-node-down', 'linux-high-cpu', 'linux-high-memory', 'linux-high-disk'],
  },
]

const filteredTemplates = computed(() => props.templates.filter((item) => {
  const text = `${item.name || ''} ${item.code || ''} ${item.description || ''}`.toLowerCase()
  const keywordOk = !keyword.value || text.includes(keyword.value.toLowerCase())
  const sourceOk = !sourceType.value || item.source_type === sourceType.value
  return keywordOk && sourceOk
}))

const visibleBundles = computed(() => BUNDLES.map((bundle) => {
  const templates = filteredTemplates.value.filter((item) => bundle.codes.includes(item.code))
  const sourceTypes = [...new Set(templates.map((item) => sourceTypeText(item.source_type)))]
  return { ...bundle, templates, sourceTypes }
}).filter((bundle) => props.compact || bundle.templates.length || (!keyword.value && !sourceType.value)))

function levelType(level) {
  return { critical: 'danger', warning: 'warning', info: 'info' }[level] || 'info'
}

function levelText(level) {
  return { critical: '严重', warning: '警告', info: '信息' }[level] || level || '-'
}

function sourceTypeText(value) {
  return {
    prometheus: 'Prometheus',
    clickhouse: 'ClickHouse',
    k8s: 'K8S',
    sla: 'SLA',
  }[value] || value || '-'
}

function expressionSummary(item) {
  return item.query_config?.query || item.query_config?.promql || item.query_config?.collection || 'Xing-Cloud 内置规则模板'
}
</script>

<style scoped>
.rule-template-catalog {
  display: grid;
  gap: 12px;
}

.rule-template-catalog.is-compact {
  padding: 0;
  border: 0;
  background: transparent;
  box-shadow: none;
}

.section-head p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
}

.section-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.section-actions .el-input {
  width: 220px;
}

.section-actions .el-select {
  width: 150px;
}

.bundle-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
}

.bundle-card {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  border-radius: 8px;
  background: #fff;
}

.bundle-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.bundle-head strong,
.template-title strong {
  color: #0f172a;
}

.bundle-head p,
.template-main p {
  margin: 4px 0 0;
  color: #475569;
  line-height: 1.55;
}

.bundle-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  color: #64748b;
  font-size: 12px;
}

.template-list {
  display: grid;
  gap: 10px;
}

.template-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 12px;
  border-radius: 8px;
  background: #f8fafc;
}

.template-title,
.template-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.template-title {
  justify-content: space-between;
}

.template-main small {
  display: block;
  margin-top: 6px;
  color: #64748b;
}

@media (max-width: 760px) {
  .section-head,
  .section-actions,
  .template-row {
    align-items: stretch;
    grid-template-columns: 1fr;
    flex-direction: column;
  }

  .section-actions .el-input,
  .section-actions .el-select {
    width: 100%;
  }
}
</style>
