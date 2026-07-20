<template>
  <div class="tab-content cmdb-items-layout task-resource-cmdb-layout">
    <div class="cmdb-resource-tree-panel">
      <div class="tree-panel-head">
        <span
          class="tree-panel-title"
          title="点击查看全部"
          @click="clearTreeFilter"
        >
          <el-icon style="margin-right:4px;vertical-align:-2px;"><Connection /></el-icon>一级资产业务分组
        </span>
        <el-button v-if="canManage" link type="primary" size="small" class="tree-head-btn" @click="openNodeDialog()">
          <el-icon><Plus /></el-icon>新增
        </el-button>
      </div>

      <el-tree
        ref="treeRef"
        :data="treeData"
        :props="{ label: 'name', children: 'children' }"
        node-key="id"
        highlight-current
        default-expand-all
        :expand-on-click-node="false"
        class="resource-tree"
        @node-click="onNodeClick"
      >
        <template #default="{ node, data }">
          <div class="custom-tree-node tree-node-content">
            <span class="tree-node-label">
              <el-icon style="color:#10b981;margin-right:4px;"><Monitor /></el-icon>
              {{ node.label }}
            </span>
            <span class="tree-actions" @click.stop>
              <el-button
                v-if="canManage"
                link
                type="primary"
                class="tree-action-btn"
                title="编辑"
                @click="openNodeDialog(data)"
              >
                <el-icon><Edit /></el-icon>
              </el-button>
              <el-popconfirm v-if="canManage" title="确定删除?" @confirm="delNode(data)">
                <template #reference>
                  <el-button link type="danger" class="tree-action-btn" title="删除">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </template>
              </el-popconfirm>
            </span>
          </div>
        </template>
      </el-tree>

      <el-empty
        v-if="!loading.tree && !treeData.length"
        description="暂无一级资产业务分组"
        :image-size="72"
        class="tree-empty"
      />
    </div>

    <div class="cmdb-items-main resource-list-card">
      <div class="toolbar section-gap resource-toolbar">
        <div class="toolbar-left resource-toolbar-left">
          <el-select v-model="filters.resource_type" placeholder="资源类型" clearable style="width:120px" size="small" @change="refreshResourceView">
            <el-option label="主机" value="host" />
            <el-option label="K8S 集群" value="k8s" />
          </el-select>
          <div class="bound-asset-environment">当前上下文默认：{{ currentContext?.task_resource_environment_name || '未绑定' }}</div>
          <el-select v-model="filters.status" placeholder="状态" clearable style="width:110px" size="small" @change="refreshResourceView">
            <el-option label="可用" value="active" />
            <el-option label="异常" value="warning" />
            <el-option label="停用" value="inactive" />
          </el-select>
          <el-input
            v-model="filters.search"
            placeholder="搜索名称/IP/集群/负责人"
            clearable
            style="width:200px"
            size="small"
            @clear="refreshResourceView"
            @keyup.enter="refreshResourceView"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </div>
        <div class="toolbar-right resource-toolbar-right">
          <el-button size="small" @click="resetFilters">重置</el-button>
          <el-button size="small" :loading="loading.resources" @click="reloadAll">刷新</el-button>
          <el-button v-if="canManage" size="small" @click="openResourceDialog(null, 'host')">登记服务器</el-button>
          <el-button v-if="canManage" type="primary" size="small" @click="openResourceDialog(null, 'k8s')">登记 K8S 集群</el-button>
        </div>
      </div>

      <div class="cmdb-stats-row section-gap">
        <div
          v-for="card in statCards"
          :key="card.key"
          class="cmdb-stat-card"
          :class="{ active: card.active }"
          @click="applyStatCard(card)"
        >
          <div class="stat-dot" :style="{ background: card.color }"></div>
          <div class="stat-info">
            <div class="stat-val">{{ card.value }}</div>
            <div class="stat-label">{{ card.label }}</div>
          </div>
        </div>
      </div>

      <div class="resource-table-wrap">
        <el-table
          size="small"
          :data="resources"
          v-loading="loading.resources"
          row-key="id"
          class="resource-table responsive-resource-table"
          height="100%"
          :empty-text="emptyText"
        >
          <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
          <el-table-column label="类型" width="80">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="row.resource_type === 'host' ? 'success' : 'info'">
                {{ row.resource_type_display || resourceTypeLabel(row.resource_type) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="一级资产业务分组" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ (row.business_group_names || [row.environment_name]).filter(Boolean).join('、') || '-' }}</template>
          </el-table-column>
          <el-table-column label="执行入口" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">{{ resourceEndpoint(row) }}</template>
          </el-table-column>
          <el-table-column prop="owner" label="运维负责人" width="90" show-overflow-tooltip>
            <template #default="{ row }">{{ row.owner || '-' }}</template>
          </el-table-column>
          <el-table-column prop="project_owner" label="业务负责人" width="90" show-overflow-tooltip>
            <template #default="{ row }">{{ row.project_owner || '-' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="statusType(row.status)">
                {{ row.status_display || statusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="说明" min-width="110" show-overflow-tooltip />
          <el-table-column v-if="canManage" label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button link size="small" @click="openResourceDialog(row)">编辑</el-button>
              <el-button link size="small" type="danger" @click="removeResource(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog
      v-model="nodeDialogVisible"
      :title="nodeDialogTitle"
      class="resource-dialog"
      width="520px"
      top="15vh"
      append-to-body
      destroy-on-close
    >
      <el-form :model="nodeForm" label-width="96px" class="resource-compact-form">
        <el-form-item label="节点类型">
          <el-tag size="small" type="success" effect="plain">一级资产业务分组</el-tag>
        </el-form-item>
        <el-form-item label="业务名称" required>
          <el-input v-model="nodeForm.name" placeholder="例如：智能平台、支付业务、中间件集群" />
        </el-form-item>
        <el-form-item label="编码">
          <el-input v-model="nodeForm.code" placeholder="可选，例如 prod / quality" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="nodeForm.sort_order" :min="1" :max="9999" style="width:100%" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="nodeForm.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="nodeDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="loading.submit" @click="submitNode">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="resourceDialogVisible"
      :title="resourceDialogTitle"
      class="resource-dialog"
      width="620px"
      top="10vh"
      append-to-body
      destroy-on-close
    >
      <el-form :model="resourceForm" label-width="96px" class="resource-compact-form">
        <div class="form-row">
          <el-form-item label="资源类型" required class="form-col">
            <el-radio-group v-model="resourceForm.resource_type" :disabled="editingResourceId !== null">
              <el-radio label="host">主机</el-radio>
              <el-radio label="k8s">K8S 集群</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="状态" required class="form-col">
            <el-select v-model="resourceForm.status" style="width:100%">
              <el-option label="可用" value="active" />
              <el-option label="异常" value="warning" />
              <el-option label="停用" value="inactive" />
            </el-select>
          </el-form-item>
        </div>
        <div class="form-row">
          <el-form-item label="业务分组" required class="form-col wide">
            <div class="resource-group-picker">
              <el-select v-model="resourceForm.business_groups" multiple filterable placeholder="可选择多个一级业务分组" style="width:100%">
                <el-option v-for="item in environments" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
              <el-button v-if="canManage" plain :icon="Plus" @click="openNodeDialog(null, true)">新建</el-button>
            </div>
          </el-form-item>
        </div>
        <div class="form-row">
          <el-form-item label="运维负责人" class="form-col">
            <el-input v-model="resourceForm.owner" placeholder="例如 xinghai / 平台运维组" />
          </el-form-item>
          <el-form-item label="业务负责人" class="form-col">
            <el-input v-model="resourceForm.project_owner" placeholder="例如 研发负责人 / 业务负责人" />
          </el-form-item>
        </div>
        <el-form-item v-if="resourceForm.resource_type === 'host'" label="资产名称" required>
          <el-input v-model="resourceForm.name" placeholder="请输入资产名称" />
        </el-form-item>
        <template v-if="resourceForm.resource_type === 'host'">
          <div class="form-row">
            <el-form-item label="IP 地址" required class="form-col">
              <el-input v-model="resourceForm.ip_address" placeholder="192.168.1.10" />
            </el-form-item>
            <el-form-item label="SSH 端口" class="form-col">
              <el-input-number v-model="resourceForm.ssh_port" :min="1" :max="65535" style="width:100%" />
            </el-form-item>
          </div>
          <div class="form-row">
            <el-form-item label="SSH 用户" class="form-col">
              <el-input v-model="resourceForm.ssh_user" />
            </el-form-item>
            <el-form-item label="SSH 密码" class="form-col">
              <el-input v-model="resourceForm.ssh_password" type="password" show-password placeholder="不修改可留空" />
            </el-form-item>
          </div>
        </template>
        <template v-else>
          <div class="form-row">
            <el-form-item label="K8S 集群" required class="form-col">
              <el-select v-model="resourceForm.cluster" filterable style="width:100%" @change="syncK8sResourceName">
                <el-option v-for="cluster in k8sClusters" :key="cluster.id" :label="cluster.name" :value="cluster.id" />
              </el-select>
              <div class="field-hint">一个 K8S 集群登记为一项资产；Node、Namespace 和工作负载由集群接口自动发现，无需逐个登记。</div>
            </el-form-item>
            <el-form-item label="资产名称" class="form-col">
              <el-input :model-value="selectedK8sClusterName || '选择集群后自动生成'" disabled />
            </el-form-item>
          </div>
        </template>
        <div class="form-row">
          <el-form-item label="说明" class="form-col wide">
            <el-input v-model="resourceForm.description" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="resourceDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="loading.submit" @click="submitResource">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Delete, Edit, Monitor, Plus, Search } from '@element-plus/icons-vue'
import { getK8sClusters } from '@/api/modules/container'
import {
  createTaskResource,
  createTaskResourceGroup,
  deleteTaskResource,
  deleteTaskResourceGroup,
  getTaskResourceStats,
  getTaskResourceTree,
  getTaskResources,
  updateTaskResource,
  updateTaskResourceGroup,
} from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'
import { useBusinessContextStore } from '@/stores/businessContext'

const emit = defineEmits(['tree-updated', 'stats-updated'])
const auth = useAuthStore()
const businessContextStore = useBusinessContextStore()
const { currentContext, currentContextId } = storeToRefs(businessContextStore)
const canManage = computed(() => auth.hasPermission('ops.task.resource.manage'))

const treeRef = ref(null)
const treeData = ref([])
const resources = ref([])
const stats = ref({})
const k8sClusters = ref([])
const loading = reactive({ tree: false, resources: false, submit: false })
const filters = reactive({ search: '', resource_type: '', status: '', environment: '' })

const nodeDialogVisible = ref(false)
const editingNodeId = ref(null)
const selectCreatedGroupForResource = ref(false)
const nodeForm = reactive(defaultNodeForm())

const resourceDialogVisible = ref(false)
const editingResourceId = ref(null)
const resourceForm = reactive(defaultResourceForm())

const environments = computed(() => treeData.value)
const selectedK8sClusterName = computed(() => k8sClusters.value.find(item => item.id === resourceForm.cluster)?.name || '')
const nodeDialogTitle = computed(() => `${editingNodeId.value ? '编辑' : '新增'}一级资产业务分组`)
const resourceDialogTitle = computed(() => `${editingResourceId.value ? '编辑' : '新增'}资产`)
const emptyText = computed(() => (treeData.value.length ? '暂无匹配资产' : '暂无资产，请先创建左侧一级资产业务分组'))
const statCards = computed(() => [
  { key: 'total', label: '资产总数', value: stats.value.total || 0, color: '#8b5cf6' },
  { key: 'host', label: '主机', value: stats.value.host || 0, color: '#10b981', resourceType: 'host', active: filters.resource_type === 'host' },
  { key: 'k8s', label: 'K8S 集群', value: stats.value.k8s || 0, color: '#38bdf8', resourceType: 'k8s', active: filters.resource_type === 'k8s' },
  { key: 'active', label: '可用', value: stats.value.active || 0, color: '#22c55e', status: 'active', active: filters.status === 'active' },
  { key: 'warning', label: '异常', value: stats.value.warning || 0, color: '#f59e0b', status: 'warning', active: filters.status === 'warning' },
  { key: 'inactive', label: '停用', value: stats.value.inactive || 0, color: '#94a3b8', status: 'inactive', active: filters.status === 'inactive' },
])

function defaultNodeForm() {
  return { group_type: 'environment', parent: '', name: '', code: '', sort_order: 100, description: '' }
}

function defaultResourceForm() {
  return {
    resource_type: 'host',
    name: '',
    environment: '',
    business_groups: [],
    system: '',
    asset_environment: '',
    status: 'active',
    ip_address: '',
    ssh_port: 22,
    ssh_user: 'root',
    ssh_password: '',
    cluster: '',
    namespace: '',
    owner: '',
    project_owner: '',
    description: '',
    metadata: {},
  }
}

function normalizeList(res) {
  if (Array.isArray(res)) return res
  if (Array.isArray(res?.results)) return res.results
  return []
}

function normalizeTree(list = []) {
  return list.filter(env => env.group_type === 'environment').map(env => ({
    ...env,
    children: [],
  }))
}

function resourceTypeLabel(type) {
  return type === 'k8s' ? 'K8S 集群' : '主机'
}

function resourceEndpoint(row) {
  if (row.resource_type === 'k8s') return row.cluster_name || row.name || '-'
  return row.endpoint || row.ip_address || '-'
}

function statusLabel(status) {
  if (status === 'active') return '可用'
  if (status === 'warning') return '异常'
  if (status === 'inactive') return '停用'
  return status || '-'
}

function statusType(status) {
  if (status === 'active') return 'success'
  if (status === 'warning') return 'warning'
  return 'info'
}

function clearTreeFilter() {
  treeRef.value?.setCurrentKey(null)
  filters.environment = ''
  refreshResourceView()
}

function onNodeClick(data) {
  filters.environment = data.id
  refreshResourceView()
}

function onEnvironmentFilterChange() {
  treeRef.value?.setCurrentKey(filters.environment || null)
  refreshResourceView()
}

function resetFilters() {
  Object.assign(filters, { search: '', resource_type: '', status: '', environment: '' })
  treeRef.value?.setCurrentKey(null)
  refreshResourceView()
}

function applyStatCard(card) {
  if (card.resourceType) {
    filters.resource_type = filters.resource_type === card.resourceType ? '' : card.resourceType
  }
  if (card.status) {
    filters.status = filters.status === card.status ? '' : card.status
  }
  refreshResourceView()
}

function syncK8sResourceName() {
  if (resourceForm.resource_type === 'k8s') {
    resourceForm.name = selectedK8sClusterName.value
    resourceForm.namespace = ''
  }
}

function openNodeDialog(row = null, selectForResource = false) {
  if (!canManage.value) return
  editingNodeId.value = row?.id || null
  selectCreatedGroupForResource.value = Boolean(selectForResource && !row)
  Object.assign(nodeForm, defaultNodeForm())
  if (row) {
    Object.assign(nodeForm, {
      group_type: row.group_type,
      parent: row.parent || '',
      name: row.name || '',
      code: row.code || '',
      sort_order: row.sort_order || 100,
      description: row.description || '',
    })
  }
  nodeDialogVisible.value = true
}

function openResourceDialog(row = null, preferredType = '') {
  if (!canManage.value) return
  if (!row && !treeData.value.length) {
    Object.assign(resourceForm, defaultResourceForm(), { resource_type: preferredType || 'host' })
    ElMessage.warning('请先新增一级资产业务分组')
    openNodeDialog(null, true)
    return
  }
  editingResourceId.value = row?.id || null
  Object.assign(resourceForm, defaultResourceForm())
  if (row) {
    Object.assign(resourceForm, {
      resource_type: row.resource_type,
      name: row.name || '',
      environment: row.environment || '',
      business_groups: row.business_groups?.length ? [...row.business_groups] : (row.environment ? [row.environment] : []),
      system: row.system || '',
      asset_environment: '',
      status: row.status || 'active',
      ip_address: row.ip_address || '',
      ssh_port: row.ssh_port || 22,
      ssh_user: row.ssh_user || 'root',
      ssh_password: '',
      cluster: row.cluster || '',
      namespace: row.namespace || '',
      owner: row.owner || '',
      project_owner: row.project_owner || '',
      description: row.description || '',
      metadata: row.metadata || {},
    })
  } else {
    Object.assign(resourceForm, {
      resource_type: preferredType || 'host',
      business_groups: [filters.environment || currentContext.value?.task_resource_environment].filter(Boolean),
    })
  }
  resourceDialogVisible.value = true
}

async function fetchTree() {
  loading.tree = true
  try {
    const res = await getTaskResourceTree()
    treeData.value = normalizeTree(normalizeList(res))
    if (filters.environment && !treeData.value.some(item => Number(item.id) === Number(filters.environment))) filters.environment = ''
    emit('tree-updated', treeData.value)
  } finally {
    loading.tree = false
  }
}

async function fetchResources() {
  loading.resources = true
  try {
    const res = await getTaskResources({ ...filters })
    resources.value = normalizeList(res)
  } finally {
    loading.resources = false
  }
}

function statFilterParams() {
  return {
    environment: filters.environment || undefined,
    status: filters.status || undefined,
    search: filters.search || undefined,
  }
}

async function fetchStats() {
  const res = await getTaskResourceStats(statFilterParams())
  stats.value = res || {}
  emit('stats-updated', stats.value)
}

async function refreshResourceView() {
  await Promise.all([fetchResources(), fetchStats()])
}

async function fetchK8sClusters() {
  try {
    k8sClusters.value = normalizeList(await getK8sClusters())
  } catch {
    k8sClusters.value = []
  }
}

async function reloadAll() {
  await Promise.all([fetchTree(), fetchResources(), fetchStats(), fetchK8sClusters()])
}

async function submitNode() {
  if (!nodeForm.name.trim()) return ElMessage.warning('请填写业务名称')
  loading.submit = true
  try {
    const payload = {
      ...nodeForm,
      group_type: 'environment',
      name: nodeForm.name.trim(),
      parent: null,
      event_environment: null,
    }
    let saved
    if (editingNodeId.value) {
      saved = await updateTaskResourceGroup(editingNodeId.value, payload)
    } else {
      saved = await createTaskResourceGroup(payload)
    }
    nodeDialogVisible.value = false
    if (selectCreatedGroupForResource.value && saved?.id) {
      resourceForm.business_groups = Array.from(new Set([...resourceForm.business_groups, saved.id]))
      resourceForm.environment = saved.id
      resourceDialogVisible.value = true
    }
    selectCreatedGroupForResource.value = false
    ElMessage.success('一级资产业务分组已保存')
    await reloadAll()
  } finally {
    loading.submit = false
  }
}

async function submitResource() {
  if (!resourceForm.business_groups.length) return ElMessage.warning('请至少选择一个一级资产业务分组')
  if (resourceForm.resource_type === 'host') {
    if (!resourceForm.name.trim()) return ElMessage.warning('请填写资产名称')
    if (!resourceForm.ip_address) return ElMessage.warning('请填写主机 IP')
  }
  if (resourceForm.resource_type === 'k8s') {
    if (!resourceForm.cluster) return ElMessage.warning('请选择 K8S 集群')
    syncK8sResourceName()
    if (!resourceForm.name.trim()) return ElMessage.warning('所选 K8S 集群缺少名称')
  }
  loading.submit = true
  try {
    const payload = {
      ...resourceForm,
      name: resourceForm.name.trim(),
      environment: resourceForm.business_groups[0],
      asset_environment: '',
      system: resourceForm.system || null,
      cluster: resourceForm.cluster || null,
      namespace: '',
    }
    if (payload.resource_type === 'k8s') {
      payload.ip_address = null
      payload.ssh_password = ''
      payload.ssh_user = ''
    }
    if (editingResourceId.value && !payload.ssh_password) delete payload.ssh_password
    if (editingResourceId.value) {
      await updateTaskResource(editingResourceId.value, payload)
    } else {
      await createTaskResource(payload)
    }
    resourceDialogVisible.value = false
    ElMessage.success('资产已保存')
    await reloadAll()
  } finally {
    loading.submit = false
  }
}

async function delNode(row) {
  await deleteTaskResourceGroup(row.id)
  ElMessage.success('节点已删除')
  await reloadAll()
}

async function removeResource(row) {
  try {
    await ElMessageBox.confirm(`确认删除资产「${row.name}」？`, '删除资产', { type: 'warning' })
  } catch {
    return
  }
  await deleteTaskResource(row.id)
  ElMessage.success('资源已删除')
  await reloadAll()
}

watch(currentContextId, async () => {
  await reloadAll()
})

onMounted(async () => {
  await businessContextStore.loadContexts()
  await reloadAll()
})
</script>

<style scoped>
.bound-asset-environment,
.bound-form-value {
  min-width: 0;
  overflow: hidden;
  border: 1px solid #dbe4ee;
  background: #f8fafc;
  color: #334155;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resource-group-picker {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
}

.bound-asset-environment {
  width: 180px;
  padding: 6px 9px;
}

.bound-form-value {
  width: 100%;
  min-height: 32px;
  padding: 7px 10px;
}

.custom-tree-node {
  transition: background 0.2s;
  border-radius: 6px;
}

.tree-node-content {
  flex: 1;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  min-height: 26px;
  font-size: 12px;
  padding-right: 2px;
}

.custom-tree-node:hover {
  background: rgba(139, 92, 246, 0.05);
}

.tree-actions {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.2s;
  white-space: nowrap;
}

.tree-action-btn {
  min-height: 18px;
  height: 18px;
  min-width: 18px;
  padding: 0;
  margin-left: 0 !important;
  font-size: 11px;
}

.el-tree-node__content:hover .tree-actions {
  opacity: 1;
}

.tree-node-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.tree-env-tag {
  height: 18px;
  padding: 0 5px;
  border-radius: 6px;
  color: #245bdb;
  border-color: rgba(51, 112, 255, 0.18);
  background: rgba(51, 112, 255, 0.08);
}

.tree-panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  padding: 4px 0;
}

.tree-panel-title {
  font-weight: 600;
  color: #0f172a;
  font-size: 13px;
  cursor: pointer;
}

.tree-head-btn {
  min-height: 24px;
  padding: 0 4px;
}

.cmdb-items-layout {
  display: flex;
  gap: 8px;
  min-height: 0;
}

.task-resource-cmdb-layout {
  display: flex;
  gap: 8px;
  align-items: stretch;
  min-height: clamp(560px, calc(100vh - 230px), 980px);
}

.cmdb-resource-tree-panel {
  width: 212px;
  flex: 0 0 212px;
  border-right: 1px solid rgba(148, 163, 184, 0.14);
  padding-right: 12px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.cmdb-items-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.resource-list-card {
  gap: 0;
}

.section-gap {
  margin-bottom: 10px;
}

.resource-tree {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background: transparent;
}

.tree-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px 0;
}

.toolbar,
.resource-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 12px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.92) 0%, rgba(255, 255, 255, 0.96) 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.toolbar-left,
.toolbar-right,
.resource-toolbar-left,
.resource-toolbar-right {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}

.toolbar :deep(.el-input__wrapper),
.toolbar :deep(.el-select__wrapper),
.resource-toolbar :deep(.el-input__wrapper),
.resource-toolbar :deep(.el-select__wrapper) {
  min-height: 28px;
  border-radius: 8px;
  box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.12) inset;
  background: rgba(255, 255, 255, 0.94);
}

.toolbar :deep(.el-input__wrapper:hover),
.toolbar :deep(.el-select__wrapper:hover),
.resource-toolbar :deep(.el-input__wrapper:hover),
.resource-toolbar :deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.16) inset;
}

.toolbar-right :deep(.el-button),
.resource-toolbar-right :deep(.el-button) {
  min-height: 26px;
  padding: 0 9px;
  border-radius: 8px;
  font-weight: 500;
}

.toolbar-right :deep(.el-button:not(.el-button--primary)),
.resource-toolbar-right :deep(.el-button:not(.el-button--primary)) {
  border-color: rgba(148, 163, 184, 0.12);
  background: rgba(255, 255, 255, 0.9);
  color: #475569;
  box-shadow: none;
}

.toolbar-right :deep(.el-button:not(.is-link):hover),
.resource-toolbar-right :deep(.el-button:not(.is-link):hover) {
  border-color: rgba(59, 130, 246, 0.18);
  color: #1d4ed8;
  background: #f8fbff;
}

.cmdb-stats-row {
  display: flex;
  gap: 8px;
  flex-wrap: nowrap;
  overflow-x: auto;
  padding-bottom: 2px;
}

.resource-table-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
}

.resource-table {
  width: 100%;
}

.resource-list-card :deep(.el-table) {
  --el-table-border-color: rgba(148, 163, 184, 0.16);
  --el-table-header-bg-color: #f8fafc;
  --el-table-row-hover-bg-color: #f8fbff;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 16px;
  overflow: hidden;
}

.resource-list-card :deep(.el-table th.el-table__cell) {
  color: #475569;
  font-weight: 600;
  background: #f8fafc;
}

.cmdb-stat-card {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #ffffff;
  border-radius: 10px;
  padding: 7px 10px;
  min-width: 88px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  flex: 0 0 auto;
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
}

.cmdb-stat-card:hover {
  transform: translateY(-1px);
  border-color: rgba(59, 130, 246, 0.24);
}

.cmdb-stat-card.active {
  background: #e8f0ff;
  border-color: rgba(51, 112, 255, 0.2);
  box-shadow: inset 0 0 0 1px rgba(51, 112, 255, 0.06);
}

.stat-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.stat-info {
  min-width: 0;
}

.stat-val {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1;
}

.stat-label {
  margin-top: 2px;
  font-size: 11px;
  color: #64748b;
  white-space: nowrap;
}

.form-row {
  display: flex;
  gap: 10px;
}

.form-col {
  flex: 1;
}

.field-hint {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 11px;
  line-height: 1.4;
}

.resource-compact-form :deep(.el-form-item) {
  margin-bottom: 12px;
}

.resource-compact-form :deep(.el-input__wrapper),
.resource-compact-form :deep(.el-textarea__inner),
.resource-compact-form :deep(.el-select__wrapper) {
  min-height: 32px;
  border-radius: 10px;
  box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.16) inset;
  background: rgba(255, 255, 255, 0.94);
}

.resource-compact-form :deep(.el-input__wrapper:hover),
.resource-compact-form :deep(.el-textarea__inner:hover),
.resource-compact-form :deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.18) inset;
}

.resource-dialog :deep(.el-dialog__header) {
  margin-right: 0;
  padding: 16px 18px 10px;
}

.resource-dialog :deep(.el-dialog__body) {
  padding: 10px 18px 14px;
}

.resource-dialog :deep(.el-dialog__footer) {
  padding: 10px 18px 16px;
}

.resource-dialog :deep(.el-button) {
  min-height: 30px;
  border-radius: 9px;
}

@media (max-width: 1200px) {
  .cmdb-resource-tree-panel {
    width: 196px;
    flex-basis: 196px;
  }
}

@media (max-width: 900px) {
  .responsive-resource-table :deep(.el-table__header),
  .responsive-resource-table :deep(.el-table__body),
  .responsive-resource-table :deep(.el-scrollbar__view) {
    width: 100% !important;
  }

  .cmdb-stats-row {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    overflow: visible;
  }

  .cmdb-stat-card {
    min-width: 0;
  }

  .responsive-resource-table :deep(col:nth-child(3)),
  .responsive-resource-table :deep(col:nth-child(4)),
  .responsive-resource-table :deep(col:nth-child(6)),
  .responsive-resource-table :deep(col:nth-child(7)),
  .responsive-resource-table :deep(col:nth-child(9)),
  .responsive-resource-table :deep(th:nth-child(3)),
  .responsive-resource-table :deep(th:nth-child(4)),
  .responsive-resource-table :deep(th:nth-child(6)),
  .responsive-resource-table :deep(th:nth-child(7)),
  .responsive-resource-table :deep(th:nth-child(9)),
  .responsive-resource-table :deep(td:nth-child(3)),
  .responsive-resource-table :deep(td:nth-child(4)),
  .responsive-resource-table :deep(td:nth-child(6)),
  .responsive-resource-table :deep(td:nth-child(7)),
  .responsive-resource-table :deep(td:nth-child(9)) {
    display: none;
  }

  .cmdb-items-layout {
    flex-direction: column;
  }

  .task-resource-cmdb-layout {
    min-height: auto;
  }

  .cmdb-resource-tree-panel {
    width: 100%;
    flex-basis: auto;
    border-right: none;
    border-bottom: 1px solid rgba(139, 92, 246, 0.15);
    padding-right: 0;
    padding-bottom: 12px;
  }

  .form-row {
    flex-direction: column;
    gap: 0;
  }
}

@media (max-width: 600px) {
  .cmdb-stats-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
