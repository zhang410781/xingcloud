<template>
  <div class="knowledge-config-page workbench-page-shell">
    <section v-if="!embedded" class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Setting /></el-icon></span>
          <h2>业务上下文</h2>
          <p class="page-inline-desc">从已登记的 CMDB 资产分组和数据源组装统一业务上下文</p>
        </div>
      </div>
    </section>

    <section class="workbench-card">
      <div class="section-toolbar">
        <div class="toolbar-head">
          <div class="toolbar-title">业务上下文配置</div>
          <div class="toolbar-desc">先登记 CMDB 与数据源，再选择资产分组、Prometheus 和日志源。</div>
        </div>
        <div class="toolbar-actions">
          <el-button size="small" :loading="loading" @click="loadData">
            <el-icon><RefreshRight /></el-icon>
            刷新
          </el-button>
          <el-button v-if="canManage" type="primary" size="small" @click="openDialog()">
            <el-icon><Plus /></el-icon>
            新建上下文
          </el-button>
        </div>
      </div>
      <el-table v-loading="loading" :data="environments" row-key="id">
        <el-table-column prop="name" label="业务上下文" min-width="180">
          <template #default="{ row }">
            <div class="env-name">
              <span>{{ row.name }}</span>
              <el-tag v-if="row.is_default" size="small" type="warning">默认</el-tag>
            </div>
            <div v-if="row.description" class="env-desc">{{ row.description }}</div>
            <div class="env-desc">编码：{{ row.code }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="business_line" label="业务线" min-width="130">
          <template #default="{ row }">{{ row.business_line || '-' }}</template>
        </el-table-column>
        <el-table-column label="可观测性来源" min-width="220">
          <template #default="{ row }"><TagList :items="observabilityNames(row)" /></template>
        </el-table-column>
        <el-table-column label="基础设施" min-width="190">
          <template #default="{ row }"><TagList :items="infrastructureNames(row)" /></template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.binding_status?.ready ? 'success' : 'warning'">{{ row.binding_status?.ready ? '已就绪' : '待完善' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button v-if="!row.is_default" size="small" link type="primary" :disabled="!row.is_enabled" @click="setDefaultEnvironment(row)">设为默认</el-button>
              <el-button size="small" link type="primary" @click="openDialog(row)">编辑</el-button>
              <el-button size="small" link type="primary" @click="runBindingValidation(row)">检查</el-button>
              <el-button size="small" link type="danger" @click="removeEnvironment(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialog.visible" :title="dialog.editingId ? '编辑业务上下文' : '新建业务上下文'" width="860px" append-to-body destroy-on-close>
      <el-steps :active="wizardStep" finish-status="success" align-center class="context-steps">
        <el-step title="基本信息" />
        <el-step title="CMDB 资产" />
        <el-step title="数据源与告警" />
        <el-step title="确认" />
      </el-steps>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="128px">
        <div v-show="wizardStep === 0" class="form-group-card">
          <div class="form-group-card__head">
            <strong>定义业务范围</strong>
            <span>唯一编码同时作为 Prometheus 告警的 environment 值。</span>
          </div>
          <el-form-item label="显示名称" prop="name"><el-input v-model.trim="form.name" placeholder="例如：智能运维平台生产环境" /></el-form-item>
          <el-form-item label="唯一编码" prop="code"><el-input v-model.trim="form.code" :disabled="Boolean(dialog.editingId)" placeholder="例如：xingcloud-prod"><template #append><el-button :loading="discovering" @click="discoverBindings">发现绑定</el-button></template></el-input></el-form-item>
          <el-form-item label="业务线" prop="business_line"><el-input v-model.trim="form.business_line" placeholder="例如：智能运维平台" /></el-form-item>
          <el-form-item label="负责人"><el-input v-model.trim="form.owner" /></el-form-item>
          <el-form-item label="描述"><el-input v-model.trim="form.description" maxlength="255" show-word-limit /></el-form-item>
        </div>
        <div v-show="wizardStep === 1" class="form-group-card">
          <div class="form-group-card__head"><strong>选择 CMDB 一级资产业务分组</strong><span>K8S、服务器和中间件范围从该分组自动读取，不重复配置。</span></div>
          <el-form-item label="资产业务分组">
            <el-select v-model="form.task_resource_environment" filterable clearable placeholder="选择已在资产管理中创建的一级业务分组">
              <el-option v-for="item in catalog.task_resource_environments" :key="item.id" :label="taskResourceEnvironmentLabel(item)" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-descriptions v-if="selectedAssetGroup" :column="2" border size="small">
            <el-descriptions-item label="CMDB 资产">{{ selectedAssetGroup.resource_count || 0 }} 项</el-descriptions-item>
            <el-descriptions-item label="K8S 集群">{{ (selectedAssetGroup.k8s_clusters || []).join('、') || '未登记' }}</el-descriptions-item>
            <el-descriptions-item label="中间件" :span="2">{{ (selectedAssetGroup.middleware_assets || []).join('、') || '未登记' }}</el-descriptions-item>
          </el-descriptions>
        </div>
        <div v-show="wizardStep === 2" class="form-group-card">
          <div class="form-group-card__head"><strong>数据源与告警</strong><span>数据源来自可观测性数据源目录，允许多个业务上下文复用。</span></div>
          <el-form-item label="指标数据源"><el-select v-model="form.metric_datasource" filterable clearable><el-option v-for="item in catalog.metric_datasources" :key="item.id" :label="datasourceLabel(item)" :value="item.id" :disabled="item.is_enabled === false" /></el-select></el-form-item>
          <el-form-item label="日志数据源"><el-select v-model="form.log_datasource" filterable clearable><el-option v-for="item in catalog.log_datasources" :key="item.id" :label="datasourceLabel(item)" :value="item.id" :disabled="item.is_enabled === false" /></el-select></el-form-item>
          <el-form-item label="告警环境"><el-input :model-value="form.code" disabled /><div class="field-hint inline">Prometheus 告警的 environment 必须完全等于此编码。</div></el-form-item>
        </div>
        <div v-show="wizardStep === 3" class="form-group-card">
          <div class="form-group-card__head"><strong>确认业务上下文</strong><span>保存后监控、日志、告警、巡检、知识图谱和智能助手统一继承。</span></div>
          <el-descriptions :column="2" border size="small"><el-descriptions-item label="业务上下文">{{ form.name || '-' }}</el-descriptions-item><el-descriptions-item label="环境编码">{{ form.code || '-' }}</el-descriptions-item><el-descriptions-item label="资产业务分组">{{ selectedAssetName }}</el-descriptions-item><el-descriptions-item label="K8S">{{ (selectedAssetGroup?.k8s_clusters || []).join('、') || '未登记' }}</el-descriptions-item><el-descriptions-item label="Prometheus">{{ selectedMetricName }}</el-descriptions-item><el-descriptions-item label="日志源">{{ selectedLogName }}</el-descriptions-item></el-descriptions>
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
        <el-button v-if="wizardStep > 0" @click="wizardStep--">上一步</el-button>
        <el-button v-if="wizardStep < 3" type="primary" @click="wizardStep++">下一步</el-button>
        <el-button v-else type="primary" :loading="saving" @click="submitForm">保存并检查</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, ElTag } from 'element-plus'
import { Plus, RefreshRight, Setting } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useBusinessContextStore } from '@/stores/businessContext'
import {
  createAIOpsKnowledgeEnvironment,
  deleteAIOpsKnowledgeEnvironment,
  discoverAIOpsKnowledgeEnvironmentBindings,
  getAIOpsKnowledgeEnvironmentCatalog,
  getAIOpsKnowledgeEnvironments,
  updateAIOpsKnowledgeEnvironment,
  validateAIOpsKnowledgeEnvironmentBindings,
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
const businessContextStore = useBusinessContextStore()
const canManage = computed(() => authStore.hasPermission('aiops.knowledge.manage'))
const loading = ref(false)
const saving = ref(false)
const discovering = ref(false)
const wizardStep = ref(0)
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
  code: '',
  business_line: '',
  environment_type: 'prod',
  owner: '',
  description: '',
  metric_datasource: null,
  log_datasource: null,
  k8s_cluster: null,
  k8s_namespaces: { namespaces: [] },
  task_resource_environment: null,
  is_default: false,
  is_enabled: true,
})

const rules = {
  name: [{ required: true, message: '请填写业务上下文名称', trigger: 'blur' }],
  code: [{ required: true, pattern: /^[a-z0-9]+(?:-[a-z0-9]+)*$/, message: '请使用小写字母、数字和连字符', trigger: 'blur' }],
  business_line: [{ required: true, message: '请填写业务线', trigger: 'blur' }],
}

const selectedAssetGroup = computed(() => catalog.task_resource_environments.find(item => Number(item.id) === Number(form.task_resource_environment)) || null)
const selectedMetricName = computed(() => catalog.metric_datasources.find(item => Number(item.id) === Number(form.metric_datasource))?.name || '未绑定')
const selectedLogName = computed(() => catalog.log_datasources.find(item => Number(item.id) === Number(form.log_datasource))?.name || '未绑定')
const selectedAssetName = computed(() => catalog.task_resource_environments.find(item => Number(item.id) === Number(form.task_resource_environment))?.name || '未绑定')

function resetForm(row = null) {
  dialog.editingId = row?.id || null
  wizardStep.value = 0
  form.name = row?.name || ''
  form.code = row?.code || ''
  form.business_line = row?.business_line || ''
  form.environment_type = row?.environment_type || 'prod'
  form.owner = row?.owner || ''
  form.description = row?.description || ''
  form.metric_datasource = relationId(row?.metric_datasource ?? row?.metric_datasource_id ?? row?.metric_datasource_ids?.[0])
  form.log_datasource = relationId(row?.log_datasource ?? row?.log_datasource_id ?? row?.log_datasource_ids?.[0])
  form.k8s_cluster = relationId(row?.k8s_cluster)
  form.k8s_namespaces = { namespaces: [...(row?.k8s_namespaces?.namespaces || [])] }
  form.task_resource_environment = relationId(row?.task_resource_environment)
  form.is_default = row?.is_default ?? false
  form.is_enabled = row?.is_enabled ?? true
}

function hasAnyBinding() {
  return Boolean(form.metric_datasource && form.log_datasource && form.task_resource_environment)
}

function relationId(value) {
  if (value && typeof value === 'object') return value.id ?? null
  return value ?? null
}

function datasourceLabel(item) {
  const details = [item.provider_display || item.provider, item.environment, item.cluster_name].filter(Boolean)
  const status = item.is_enabled === false ? ' / 已停用' : ''
  return `${item.name}${details.length ? ` / ${details.join(' / ')}` : ''}${bindingOwnerSuffix(item)}${status}`
}

function datasourceNames(ids = [], type = 'log') {
  const source = type === 'metric'
      ? catalog.metric_datasources
      : catalog.log_datasources
  const nameMap = new Map(source.map(item => [Number(item.id), item.name]))
  return ids.map(id => nameMap.get(Number(id)) || `ID ${id}`)
}

function k8sClusterLabel(item) {
  const endpoint = item.api_server ? ` / ${item.api_server}` : ''
  return `${item.name}${endpoint}${bindingOwnerSuffix(item)}`
}

function namespaceOptionsForCluster(cluster) {
  return cluster.namespaces || []
}

function taskResourceEnvironmentLabel(item) {
  const suffix = Number(item.resource_count || 0) ? ` / ${item.resource_count} 个资源` : ''
  return `${item.name}${suffix}${bindingOwnerSuffix(item)}`
}

function bindingOwnerSuffix(item) {
  const owners = item?.bound_contexts || (item?.bound_context ? [item.bound_context] : [])
  return owners.length ? ` / 使用于：${owners.map(owner => owner.name).join('、')}` : ' / 暂未使用'
}

function bindingTransferConflicts() {
  return []
}

function observabilityNames(row) {
  const metricId = relationId(row.metric_datasource)
  const logId = relationId(row.log_datasource)
  return [
    `告警: ${row.code}`,
    ...(metricId ? [`指标: ${datasourceNames([metricId], 'metric')[0]}`] : []),
    ...(logId ? [`日志: ${datasourceNames([logId], 'log')[0]}`] : []),
  ]
}

function infrastructureNames(row) {
  const resourceEnvMap = new Map(catalog.task_resource_environments.map(item => [Number(item.id), `资产登记: ${item.name}`]))
  return [
    ...(row.task_resource_environment ? [resourceEnvMap.get(Number(row.task_resource_environment)) || `资产登记 ID ${row.task_resource_environment}`] : []),
  ]
}

async function discoverBindings() {
  if (!form.code) return ElMessage.warning('请先填写业务上下文编码')
  discovering.value = true
  try {
    const result = await discoverAIOpsKnowledgeEnvironmentBindings(form.code)
    if (result.metric_datasources?.length === 1) form.metric_datasource = result.metric_datasources[0].id
    if (result.log_datasources?.length === 1) form.log_datasource = result.log_datasources[0].id
    if (result.asset_environments?.length === 1) form.task_resource_environment = result.asset_environments[0].id
    ElMessage.success(result.unambiguous ? '已填入唯一匹配的绑定' : '已发现候选项，请确认后继续')
  } finally { discovering.value = false }
}

async function runBindingValidation(row) {
  const result = await validateAIOpsKnowledgeEnvironmentBindings(row.id, true)
  const failed = (result.checks || []).filter(item => item.status !== 'ready')
  if (!failed.length) ElMessage.success('业务上下文已就绪')
  else ElMessage.warning(failed.map(item => `${item.title}：${item.detail}`).join('；'))
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
    ElMessage.warning('请选择 CMDB 一级资产业务分组、指标数据源和日志数据源')
    return
  }
  const transferConflicts = bindingTransferConflicts()
  if (transferConflicts.length) {
    const details = transferConflicts
      .map(({ label, item, owner }) => `${label}「${item.name}」当前属于「${owner.name}（${owner.code}）」`)
      .join('；')
    await ElMessageBox.confirm(
      `${details}。确认后资源及其关联规则将转移到当前业务上下文，原上下文会标记为缺少配置。`,
      '确认转移资源归属',
      { type: 'warning', confirmButtonText: '确认转移', cancelButtonText: '取消' },
    )
  }
  saving.value = true
  try {
    const payload = {
      name: form.name,
      code: form.code,
      business_line: form.business_line,
      owner: form.owner,
      description: form.description,
      metric_datasource: form.metric_datasource || null,
      log_datasource: form.log_datasource || null,
      task_resource_environment: form.task_resource_environment || null,
      environment_type: 'prod',
      is_default: form.is_default,
      is_enabled: form.is_enabled,
    }
    if (dialog.editingId) {
      await updateAIOpsKnowledgeEnvironment(dialog.editingId, payload)
    } else {
      await createAIOpsKnowledgeEnvironment(payload)
    }
    ElMessage.success('业务上下文已保存')
    dialog.visible = false
    await loadData()
    const saved = environments.value.find(item => item.code === form.code)
    await businessContextStore.loadContexts({ force: true })
    if (saved) {
      businessContextStore.selectContext(saved.id)
      await runBindingValidation(saved)
    }
  } finally {
    saving.value = false
  }
}

async function setDefaultEnvironment(row) {
  await updateAIOpsKnowledgeEnvironment(row.id, { is_default: true })
  ElMessage.success(`已设为默认业务上下文：${row.name}`)
  await loadData()
}

async function removeEnvironment(row) {
  await ElMessageBox.confirm(`确认删除业务上下文「${row.name}」？`, '删除确认', { type: 'warning' })
  await deleteAIOpsKnowledgeEnvironment(row.id)
  ElMessage.success('已删除')
  await loadData()
}

onMounted(loadData)

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
