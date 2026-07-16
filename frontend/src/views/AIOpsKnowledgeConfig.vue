<template>
  <div class="knowledge-config-page workbench-page-shell">
    <section v-if="!embedded" class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Setting /></el-icon></span>
          <h2>图谱配置</h2>
          <p class="page-inline-desc">把可观测性、告警和 K8S 基础设施线索绑定成 AIOps 可识别的知识图谱环境</p>
        </div>
      </div>
    </section>

    <section class="workbench-card">
      <div class="section-toolbar">
        <div class="toolbar-head">
          <div class="toolbar-title">环境关联配置</div>
          <div class="toolbar-desc">环境名和别名会作为 AIOps 分析入口，关联来源用于生成图谱节点和辅助定位证据。<strong>信息越多根因分析越准</strong></div>
        </div>
        <div class="toolbar-actions">
          <el-button size="small" :loading="loading" @click="loadData">
            <el-icon><RefreshRight /></el-icon>
            刷新
          </el-button>
          <el-button v-if="canManage" type="primary" size="small" @click="openDialog()">
            <el-icon><Plus /></el-icon>
            新增关联
          </el-button>
        </div>
      </div>
      <el-table v-loading="loading" :data="environments" row-key="id">
        <el-table-column prop="name" label="图谱环境名" min-width="150">
          <template #default="{ row }">
            <div class="env-name">
              <span>{{ row.name }}</span>
              <el-tag v-if="row.is_default" size="small" type="warning">默认</el-tag>
            </div>
            <div v-if="row.description" class="env-desc">{{ row.description }}</div>
          </template>
        </el-table-column>
        <el-table-column label="环境别名" min-width="150">
          <template #default="{ row }"><TagList :items="row.aliases" /></template>
        </el-table-column>
        <el-table-column label="可观测性来源" min-width="220">
          <template #default="{ row }"><TagList :items="observabilityNames(row)" /></template>
        </el-table-column>
        <el-table-column label="基础设施" min-width="190">
          <template #default="{ row }"><TagList :items="infrastructureNames(row)" /></template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button v-if="!row.is_default" size="small" link type="primary" :disabled="!row.is_enabled" @click="setDefaultEnvironment(row)">设为默认</el-button>
              <el-button size="small" link type="primary" @click="openDialog(row)">编辑</el-button>
              <el-button size="small" link type="danger" @click="removeEnvironment(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialog.visible" :title="dialog.editingId ? '编辑图谱环境' : '新增图谱环境'" width="860px" append-to-body destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="128px">
        <el-form-item label="环境名" prop="name">
          <el-input v-model.trim="form.name" placeholder="例如：交易生产 / 核心测试" />
        </el-form-item>
        <el-form-item label="环境别名">
          <el-select
            v-model="form.aliases"
            multiple
            filterable
            allow-create
            default-first-option
            clearable
            placeholder="例如：生产 / 线上 / prod"
          />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model.trim="form.description" maxlength="255" show-word-limit placeholder="可选，说明这个图谱环境绑定的业务范围" />
        </el-form-item>
        <div class="form-group-card">
          <div class="form-group-card__head">
            <strong>可观测性关联配置</strong>
            <span>告警、指标和日志统一作为分析证据。</span>
          </div>
          <el-form-item label="指标数据源">
            <el-select v-model="form.metric_datasource" filterable clearable placeholder="选择当前环境唯一的 Prometheus 指标数据源">
              <el-option v-for="item in catalog.metric_datasources" :key="item.id" :label="datasourceLabel(item)" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="日志数据源">
            <el-select v-model="form.log_datasource" filterable clearable placeholder="选择当前环境唯一的日志数据源">
              <el-option v-for="item in catalog.log_datasources" :key="item.id" :label="datasourceLabel(item)" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="告警中心环境">
            <el-select v-model="form.alert_environments" multiple filterable clearable placeholder="选择一个或多个告警中心环境">
              <el-option v-for="item in catalog.alert_environments" :key="item" :label="item" :value="item" />
            </el-select>
          </el-form-item>
        </div>
        <div class="form-group-card">
          <div class="form-group-card__head">
            <strong>运行与资产登记</strong>
            <span>选择 K8S 集群与资产登记范围，用于识别服务运行位置和可执行资源。</span>
          </div>
          <el-form-item label="K8S 集群">
            <el-select v-model="form.k8s_cluster_ids" multiple filterable clearable placeholder="选择此图谱所在的 K8S 集群">
              <el-option v-for="item in catalog.k8s_clusters" :key="item.id" :label="k8sClusterLabel(item)" :value="item.id" />
            </el-select>
          </el-form-item>
          <div v-if="selectedK8sClusters.length" class="namespace-config">
            <div class="namespace-config-title">图谱展示命名空间</div>
            <div v-for="cluster in selectedK8sClusters" :key="cluster.id" class="namespace-row">
              <div class="namespace-cluster">
                <strong>{{ cluster.name }}</strong>
                <span>展示在图谱拓扑图上的命名空间，不限制智能助手查询</span>
              </div>
              <el-select
                v-model="form.k8s_namespaces[String(cluster.id)]"
                multiple
                filterable
                allow-create
                default-first-option
                clearable
                placeholder="选择展示在图谱拓扑图上的命名空间"
              >
                <el-option v-for="namespace in namespaceOptionsForCluster(cluster)" :key="namespace" :label="namespace" :value="namespace" />
              </el-select>
            </div>
          </div>
          <div class="field-hint">资产登记中的一级业务用于 AIOps 生成巡检、脚本执行等任务时确定可选目标资源范围。</div>
          <el-form-item label="资产登记">
            <el-select v-model="form.task_resource_environment_ids" multiple filterable clearable placeholder="选择资产登记中的一级业务">
              <el-option v-for="item in catalog.task_resource_environments" :key="item.id" :label="taskResourceEnvironmentLabel(item)" :value="item.id" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="启用">
          <el-switch v-model="form.is_enabled" />
        </el-form-item>
        <el-form-item label="默认图谱">
          <el-switch
            v-model="form.is_default"
            active-text="打开图谱视图时优先展示"
            inactive-text="普通图谱"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, ElTag } from 'element-plus'
import { Plus, RefreshRight, Setting } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  createAIOpsKnowledgeEnvironment,
  deleteAIOpsKnowledgeEnvironment,
  getAIOpsKnowledgeEnvironmentCatalog,
  getAIOpsKnowledgeEnvironments,
  updateAIOpsKnowledgeEnvironment,
} from '@/api/modules/aiops'

const TagList = defineComponent({
  name: 'TagList',
  props: {
    items: { type: Array, default: () => [] },
  },
  setup(props) {
    return () => {
      const values = (props.items || []).filter(Boolean)
      if (!values.length) return h('span', { class: 'muted' }, '未关联')
      return h('div', { class: 'tag-list' }, values.slice(0, 4).map(item => h(ElTag, { key: String(item), size: 'small', type: 'info' }, () => String(item))).concat(
        values.length > 4 ? [h(ElTag, { key: '__more', size: 'small' }, () => `+${values.length - 4}`)] : [],
      ))
    }
  },
})

defineProps({
  embedded: { type: Boolean, default: false },
})

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('aiops.knowledge.manage'))
const loading = ref(false)
const saving = ref(false)
const formRef = ref(null)
const environments = ref([])
const catalog = reactive({
  metric_datasources: [],
  log_datasources: [],
  alert_environments: [],
  k8s_clusters: [],
  task_resource_environments: [],
})
const dialog = reactive({ visible: false, editingId: null })
const form = reactive({
  name: '',
  aliases: [],
  description: '',
  metric_datasource: null,
  log_datasource: null,
  alert_environments: [],
  k8s_cluster_ids: [],
  k8s_namespaces: {},
  task_resource_environment_ids: [],
  is_default: false,
  is_enabled: true,
})

const rules = {
  name: [{ required: true, message: '请填写知识图谱环境名', trigger: 'blur' }],
}

const selectedK8sClusters = computed(() => {
  const selected = new Set((form.k8s_cluster_ids || []).map(id => Number(id)))
  return catalog.k8s_clusters.filter(item => selected.has(Number(item.id)))
})

function resetForm(row = null) {
  dialog.editingId = row?.id || null
  form.name = row?.name || ''
  form.aliases = [...(row?.aliases || [])]
  form.description = row?.description || ''
  form.metric_datasource = relationId(row?.metric_datasource ?? row?.metric_datasource_id ?? row?.metric_datasource_ids?.[0])
  form.log_datasource = relationId(row?.log_datasource ?? row?.log_datasource_id ?? row?.log_datasource_ids?.[0])
  form.alert_environments = [...(row?.alert_environments || [])]
  form.k8s_cluster_ids = [...(row?.k8s_cluster_ids || [])]
  form.k8s_namespaces = { ...(row?.k8s_namespaces || {}) }
  form.task_resource_environment_ids = [...(row?.task_resource_environment_ids || [])]
  form.is_default = row?.is_default ?? false
  form.is_enabled = row?.is_enabled ?? true
}

function hasAnyBinding() {
  return Boolean(form.metric_datasource || form.log_datasource || [
    form.alert_environments,
    form.k8s_cluster_ids,
    form.task_resource_environment_ids,
  ].some(items => items.length))
}

function relationId(value) {
  if (value && typeof value === 'object') return value.id ?? null
  return value ?? null
}

function datasourceLabel(item) {
  return `${item.name} / ${item.provider_display || item.provider}`
}

function datasourceNames(ids = [], type = 'log') {
  const source = type === 'metric'
      ? catalog.metric_datasources
      : catalog.log_datasources
  const nameMap = new Map(source.map(item => [Number(item.id), item.name]))
  return ids.map(id => nameMap.get(Number(id)) || `ID ${id}`)
}

function k8sClusterLabel(item) {
  return item.api_server ? `${item.name} / ${item.api_server}` : item.name
}

function namespaceOptionsForCluster(cluster) {
  return cluster.namespaces || []
}

function taskResourceEnvironmentLabel(item) {
  const suffix = Number(item.resource_count || 0) ? ` / ${item.resource_count} 个资源` : ''
  return `${item.name}${suffix}`
}

function observabilityNames(row) {
  const metricId = relationId(row.metric_datasource ?? row.metric_datasource_id ?? row.metric_datasource_ids?.[0])
  const logId = relationId(row.log_datasource ?? row.log_datasource_id ?? row.log_datasource_ids?.[0])
  return [
    ...(row.alert_environments || []).map(name => `告警: ${name}`),
    ...(metricId ? [`指标: ${datasourceNames([metricId], 'metric')[0]}`] : []),
    ...(logId ? [`日志: ${datasourceNames([logId], 'log')[0]}`] : []),
  ]
}

function infrastructureNames(row) {
  const k8sMap = new Map(catalog.k8s_clusters.map(item => [Number(item.id), `K8S: ${item.name}`]))
  const resourceEnvMap = new Map(catalog.task_resource_environments.map(item => [Number(item.id), `资产登记: ${item.name}`]))
  return [
    ...(row.k8s_cluster_ids || []).map((id) => {
      const namespaces = row.k8s_namespaces?.[String(id)] || []
      const suffix = namespaces.length ? ` / 图谱展示: ${namespaces.join(', ')}` : ''
      return `${k8sMap.get(Number(id)) || `K8S ID ${id}`}${suffix}`
    }),
    ...(row.task_resource_environment_ids || []).map(id => resourceEnvMap.get(Number(id)) || `资产登记 ID ${id}`),
  ]
}

async function loadData() {
  loading.value = true
  try {
    const [list, options] = await Promise.all([
      getAIOpsKnowledgeEnvironments(),
      getAIOpsKnowledgeEnvironmentCatalog(),
    ])
    environments.value = Array.isArray(list) ? list : (list.results || [])
    Object.assign(catalog, {
      metric_datasources: options.metric_datasources || [],
      log_datasources: options.log_datasources || [],
      alert_environments: options.alert_environments || [],
      k8s_clusters: options.k8s_clusters || [],
      task_resource_environments: options.task_resource_environments || [],
    })
  } finally {
    loading.value = false
  }
}

function openDialog(row = null) {
  resetForm(row)
  dialog.visible = true
}

async function submitForm() {
  await formRef.value?.validate()
  if (!hasAnyBinding()) {
    ElMessage.warning('请至少选择一个指标、日志、告警、K8S 集群或资产登记来源')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name,
      aliases: form.aliases,
      description: form.description,
      metric_datasource: form.metric_datasource || null,
      log_datasource: form.log_datasource || null,
      alert_environments: form.alert_environments,
      k8s_cluster_ids: form.k8s_cluster_ids,
      k8s_namespaces: form.k8s_namespaces,
      task_resource_environment_ids: form.task_resource_environment_ids,
      is_default: form.is_default,
      is_enabled: form.is_enabled,
    }
    if (dialog.editingId) {
      await updateAIOpsKnowledgeEnvironment(dialog.editingId, payload)
    } else {
      await createAIOpsKnowledgeEnvironment(payload)
    }
    ElMessage.success('知识图谱环境已保存')
    dialog.visible = false
    await loadData()
  } finally {
    saving.value = false
  }
}

async function setDefaultEnvironment(row) {
  await updateAIOpsKnowledgeEnvironment(row.id, { is_default: true })
  ElMessage.success(`已设为默认图谱：${row.name}`)
  await loadData()
}

async function removeEnvironment(row) {
  await ElMessageBox.confirm(`确认删除知识图谱环境「${row.name}」？`, '删除确认', { type: 'warning' })
  await deleteAIOpsKnowledgeEnvironment(row.id)
  ElMessage.success('已删除')
  await loadData()
}

onMounted(loadData)

watch(() => [...form.k8s_cluster_ids], (ids) => {
  const selected = new Set(ids.map(id => String(id)))
  Object.keys(form.k8s_namespaces || {}).forEach((clusterId) => {
    if (!selected.has(clusterId)) {
      delete form.k8s_namespaces[clusterId]
    }
  })
  ids.forEach((id) => {
    const key = String(id)
    if (!Array.isArray(form.k8s_namespaces[key])) {
      form.k8s_namespaces[key] = []
    }
  })
})
</script>

<style scoped>
.knowledge-config-page {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.panel {
  padding: 14px 16px;
  border: 1px solid rgba(36, 91, 219, 0.09);
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
}

.hero {
  min-height: 70px;
  background: linear-gradient(135deg, #fbfdff 0%, #f7faff 52%, #f9fbfd 100%);
}

.hero,
.hero-copy,
.hero-title-row,
.section-toolbar,
.toolbar-head,
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.hero-title-row h2 {
  margin: 0;
  color: #0f172a;
  font-size: 22px;
  font-weight: 800;
  line-height: 1.2;
}

.page-inline-desc {
  margin: 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.hero-icon {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #245bdb;
  background: rgba(36, 91, 219, 0.09);
}

.env-desc,
.muted {
  color: #64748b;
  font-size: 13px;
}

.workbench-card {
  padding: 12px 14px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.04);
}

.section-toolbar {
  justify-content: space-between;
  margin-bottom: 10px;
}

.toolbar-title {
  color: #0f172a;
  font-size: 15px;
  font-weight: 800;
}

.toolbar-desc {
  color: #64748b;
  font-size: 13px;
}

.toolbar-desc strong {
  margin-left: 4px;
  color: #0f172a;
  font-weight: 800;
}

.toolbar-actions {
  justify-content: flex-end;
}

.env-name {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  color: #0f172a;
  font-weight: 700;
}

.tag-list {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.table-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}

.table-actions :deep(.el-button) {
  margin-left: 0;
}

.form-group-card {
  margin: 0 0 14px;
  padding: 12px 14px 2px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 12px;
  background: #f8fafc;
}

.form-group-card__head {
  margin: 0 0 10px 128px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.form-group-card__head strong {
  color: #0f172a;
  font-size: 13px;
  font-weight: 800;
}

.form-group-card__head span,
.field-hint {
  color: #64748b;
  font-size: 12px;
}

.field-hint {
  margin: -2px 0 10px 128px;
}

.namespace-config {
  margin: -4px 0 16px 128px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.78);
}

.namespace-config-title {
  margin-bottom: 8px;
  color: #0f172a;
  font-size: 12px;
  font-weight: 700;
}

.namespace-row {
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
}

.namespace-row + .namespace-row {
  margin-top: 8px;
}

.namespace-cluster {
  display: flex;
  flex-direction: column;
  gap: 2px;
  color: #64748b;
  font-size: 11px;
}

.namespace-cluster strong {
  color: #0f172a;
  font-size: 12px;
}

:deep(.el-select) {
  width: 100%;
}

.hero.panel {
  border-radius: 20px;
}

@media (max-width: 900px) {
  .hero,
  .section-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .toolbar-actions {
    justify-content: flex-start;
  }

  .namespace-config,
  .form-group-card__head,
  .field-hint {
    margin-left: 0;
  }

  .namespace-row {
    grid-template-columns: 1fr;
  }
}
</style>
