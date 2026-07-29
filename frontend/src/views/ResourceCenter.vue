<template>
  <div class="fade-in resource-center-page">
    <section class="hero panel resource-hero">
      <div>
        <div class="resource-title-row">
          <span class="resource-title-icon"><el-icon><Files /></el-icon></span>
          <div>
            <h2>资源中心</h2>
            <p>统一管理稳定资源、负责人、资源关系与自动发现；Pod 和 Service 保留在 K8S 运行时视图。</p>
          </div>
        </div>
      </div>
      <div class="resource-hero-actions">
        <el-button :loading="loading" @click="refreshAll"><el-icon><RefreshRight /></el-icon>刷新</el-button>
        <el-button v-if="canManage" type="primary" @click="openResourceDialog"><el-icon><Plus /></el-icon>登记资源</el-button>
      </div>
    </section>

    <el-alert v-if="loadError" type="error" :closable="false" show-icon :title="loadError" />

    <section class="resource-summary" v-loading="summaryLoading">
      <div class="resource-stat"><span>资源总数</span><strong>{{ summary.total || 0 }}</strong></div>
      <div class="resource-stat resource-stat--success"><span>使用中</span><strong>{{ summary.active || 0 }}</strong></div>
      <div class="resource-stat resource-stat--warning"><span>异常</span><strong>{{ summary.warning || 0 }}</strong></div>
      <div class="resource-stat resource-stat--danger"><span>失联</span><strong>{{ summary.missing || 0 }}</strong></div>
      <div class="resource-stat"><span>发现源</span><strong>{{ summary.discovery_sources || 0 }}</strong></div>
    </section>

    <div class="neo-tabs theme-blue resource-tabs">
      <button v-for="tab in tabs" :key="tab.key" class="neo-tab-btn" :class="{ active: activeTab === tab.key }" @click="activeTab = tab.key">
        <el-icon><component :is="tab.icon" /></el-icon>{{ tab.label }}
      </button>
    </div>

    <section v-if="activeTab === 'resources'" class="workbench-card resource-section">
      <div class="workbench-toolbar resource-toolbar">
        <div class="workbench-toolbar-left">
          <el-input v-model="filters.search" clearable placeholder="名称、IP、产品或稳定标识" class="resource-search" @keyup.enter="fetchResources" />
          <el-select v-model="filters.type" clearable placeholder="全部类型" class="resource-filter" @change="fetchResources">
            <el-option v-for="item in resourceTypes" :key="item.code" :label="`${item.name} (${item.resource_count || 0})`" :value="item.code" />
          </el-select>
          <el-select v-model="filters.status" clearable placeholder="全部状态" class="resource-filter" @change="fetchResources">
            <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-button @click="fetchResources">查询</el-button>
        </div>
        <span class="resource-count">{{ resources.length }} 项</span>
      </div>
      <el-table :data="resources" stripe v-loading="loading" height="calc(100vh - 345px)">
        <el-table-column label="资源" min-width="220">
          <template #default="{ row }">
            <div class="resource-name-cell">
              <span class="resource-state" :class="`resource-state--${row.status}`"></span>
              <div><strong>{{ row.display_name || row.name }}</strong><small>{{ row.resource_type_name }} · {{ row.uid }}</small></div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="primary_ip" label="主要 IP" width="145"><template #default="{ row }">{{ row.primary_ip || '-' }}</template></el-table-column>
        <el-table-column prop="environment" label="环境" width="90"><template #default="{ row }">{{ environmentText(row.environment) }}</template></el-table-column>
        <el-table-column prop="product" label="所属产品" min-width="130"><template #default="{ row }">{{ row.product || '-' }}</template></el-table-column>
        <el-table-column label="业务上下文" min-width="150"><template #default="{ row }">{{ (row.business_context_names || []).join('、') || '-' }}</template></el-table-column>
        <el-table-column prop="source" label="来源" width="100"><template #default="{ row }">{{ sourceText(row.source) }}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="负责人" min-width="150"><template #default="{ row }">{{ contactSummary(row.contacts) }}</template></el-table-column>
        <el-table-column label="最后发现" width="170"><template #default="{ row }">{{ formatTime(row.last_seen_at) }}</template></el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button v-if="canManage" link type="primary" @click="openResourceDialog(row)">编辑</el-button>
            <el-button v-if="canManage" link type="primary" @click="openContactDialog(row)">负责人</el-button>
            <el-popconfirm v-if="canManage && row.source === 'manual'" title="确定删除该手工资源吗？" @confirm="removeResource(row)">
              <template #reference><el-button link type="danger">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section v-else-if="activeTab === 'discovery'" class="workbench-card resource-section">
      <div class="section-toolbar">
        <div class="toolbar-head"><span class="toolbar-title">自动发现源</span><span class="toolbar-desc">K8S 集群登记后自动创建发现源，节点使用 Kubernetes UID 幂等对账。</span></div>
      </div>
      <el-table :data="discoverySources" stripe v-loading="discoveryLoading">
        <el-table-column prop="name" label="发现源" min-width="210" />
        <el-table-column label="类型" width="130"><template #default="{ row }">{{ row.source_type === 'k8s' ? 'Kubernetes API' : row.source_type }}</template></el-table-column>
        <el-table-column prop="k8s_cluster_name" label="连接对象" min-width="150"><template #default="{ row }">{{ row.k8s_cluster_name || '-' }}</template></el-table-column>
        <el-table-column label="同步周期" width="110"><template #default="{ row }">{{ row.sync_interval_minutes }} 分钟</template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="sourceStatusTag(row.status)">{{ sourceStatusText(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="最近成功" width="175"><template #default="{ row }">{{ formatTime(row.last_success_at) }}</template></el-table-column>
        <el-table-column prop="last_error" label="最近错误" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="previewSource(row)">发现预览</el-button>
            <el-button v-if="canManage" link type="primary" :loading="runningSourceId === row.id" @click="runSource(row)">立即发现</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section v-else-if="activeTab === 'history'" class="workbench-card resource-section">
      <div class="section-toolbar"><div class="toolbar-head"><span class="toolbar-title">发现历史</span><span class="toolbar-desc">查看每次采集、对账、新增、更新和失联结果。</span></div></div>
      <el-table :data="discoveryRuns" stripe v-loading="discoveryLoading">
        <el-table-column prop="source_name" label="发现源" min-width="190" />
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="runStatusTag(row.status)">{{ runStatusText(row.status) }}</el-tag></template></el-table-column>
        <el-table-column prop="discovered_count" label="发现" width="80" />
        <el-table-column prop="created_count" label="新增" width="80" />
        <el-table-column prop="updated_count" label="更新" width="80" />
        <el-table-column prop="unchanged_count" label="未变化" width="90" />
        <el-table-column prop="missing_count" label="未发现" width="90" />
        <el-table-column prop="error" label="错误" min-width="230" show-overflow-tooltip />
        <el-table-column label="开始时间" width="175"><template #default="{ row }">{{ formatTime(row.started_at || row.created_at) }}</template></el-table-column>
      </el-table>
    </section>

    <section v-else class="workbench-card resource-section">
      <div class="section-toolbar"><div class="toolbar-head"><span class="toolbar-title">资源关系</span><span class="toolbar-desc">展示长期资源之间的包含、运行于、部署于和依赖关系。</span></div></div>
      <el-table :data="topology.edges || []" stripe v-loading="topologyLoading">
        <el-table-column prop="source_name" label="源资源" min-width="220" />
        <el-table-column label="关系" width="130"><template #default="{ row }">{{ relationText(row.relation_type) }}</template></el-table-column>
        <el-table-column prop="target_name" label="目标资源" min-width="220" />
        <el-table-column prop="origin" label="来源" width="120" />
        <el-table-column label="最后发现" width="180"><template #default="{ row }">{{ formatTime(row.last_seen_at) }}</template></el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="resourceDialogVisible" :title="editingResourceId ? '编辑资源' : '登记资源'" width="620px" destroy-on-close>
      <el-form label-width="100px">
        <el-form-item label="资源类型" required><el-select v-model="resourceForm.resource_type" :disabled="Boolean(editingResourceId)" style="width:100%"><el-option v-for="item in (editingResourceId ? resourceTypes : manualResourceTypes)" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="资源名称" required><el-input v-model="resourceForm.name" /></el-form-item>
        <el-form-item label="显示名称"><el-input v-model="resourceForm.display_name" /></el-form-item>
        <el-form-item label="环境"><el-select v-model="resourceForm.environment" style="width:100%"><el-option label="生产" value="prod" /><el-option label="测试" value="test" /><el-option label="开发" value="dev" /><el-option label="未指定" value="unknown" /></el-select></el-form-item>
        <el-form-item label="主要 IP"><el-input v-model="resourceForm.primary_ip" placeholder="可留空" /></el-form-item>
        <template v-if="selectedManualTypeCategory === 'compute'">
          <el-form-item label="序列号/实例ID"><el-input v-model="resourceForm.serial_number" placeholder="物理机序列号或云实例 ID" /></el-form-item>
          <el-form-item label="操作系统"><el-input v-model="resourceForm.os_image" placeholder="例如 Rocky Linux 9" /></el-form-item>
        </template>
        <template v-if="selectedManualTypeCategory === 'platform'">
          <el-form-item label="访问地址" required><el-input v-model="resourceForm.endpoint" placeholder="主机名或 IP" /></el-form-item>
          <el-form-item label="端口"><el-input-number v-model="resourceForm.port" :min="1" :max="65535" /></el-form-item>
          <el-form-item label="版本"><el-input v-model="resourceForm.version" placeholder="可留空" /></el-form-item>
        </template>
        <el-form-item label="所属产品"><el-input v-model="resourceForm.product" /></el-form-item>
        <el-form-item label="业务系统"><el-input v-model="resourceForm.business_system" /></el-form-item>
        <el-form-item label="业务上下文"><el-select v-model="resourceForm.business_contexts" multiple clearable filterable style="width:100%" placeholder="仅在智能助手或研判需要时绑定"><el-option v-for="item in businessContexts" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="重要级别"><el-select v-model="resourceForm.criticality" style="width:100%"><el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" /><el-option label="核心" value="critical" /></el-select></el-form-item>
        <el-form-item label="说明"><el-input v-model="resourceForm.description" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="resourceDialogVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="saveResource">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="previewVisible" title="自动发现预览" width="860px" destroy-on-close>
      <el-descriptions v-if="preview.cluster" :column="2" border><el-descriptions-item label="集群">{{ preview.cluster.name }}</el-descriptions-item><el-descriptions-item label="节点数">{{ preview.nodes?.length || 0 }}</el-descriptions-item></el-descriptions>
      <el-table :data="preview.nodes || []" stripe max-height="430" style="margin-top:12px"><el-table-column prop="name" label="节点" min-width="180" /><el-table-column prop="primary_ip" label="IP" width="145" /><el-table-column label="状态" width="100"><template #default="{ row }">{{ statusText(row.status) }}</template></el-table-column><el-table-column label="角色" min-width="150"><template #default="{ row }">{{ (row.attributes?.roles || []).join(', ') }}</template></el-table-column></el-table>
      <div class="runtime-counts"><span v-for="(count, kind) in preview.runtime_counts" :key="kind">{{ kind }} {{ count }}</span></div>
    </el-dialog>

    <el-drawer v-model="detailVisible" title="资源详情" size="620px">
      <el-descriptions v-if="detailResource" :column="1" border><el-descriptions-item label="名称">{{ detailResource.display_name || detailResource.name }}</el-descriptions-item><el-descriptions-item label="类型">{{ detailResource.resource_type_name }}</el-descriptions-item><el-descriptions-item label="资源 ID">{{ detailResource.uid }}</el-descriptions-item><el-descriptions-item label="稳定标识"><div v-for="item in detailResource.identifiers" :key="item.id">{{ item.kind }}: {{ item.value }}</div><span v-if="!detailResource.identifiers?.length">-</span></el-descriptions-item><el-descriptions-item label="扩展属性"><pre class="resource-json">{{ JSON.stringify(detailResource.attributes || {}, null, 2) }}</pre></el-descriptions-item></el-descriptions>
      <template v-if="detailResource?.resource_type_code === 'k8s_cluster'"><h4>当前运行时对象</h4><div class="runtime-counts"><span v-for="(count, kind) in detailRuntimeCounts" :key="kind">{{ kind }} {{ count }}</span></div><p class="resource-hint">Pod 和 Service 仅作为带 TTL 的运行时索引，实际操作请进入 K8S 集群管理。</p></template>
      <h4 v-if="detailResource">最近变更</h4>
      <el-table v-if="detailResource" :data="detailChanges" stripe size="small" max-height="280" v-loading="detailLoading">
        <el-table-column prop="created_at" label="时间" width="165"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
        <el-table-column prop="action" label="动作" width="105"><template #default="{ row }">{{ changeActionText(row.action) }}</template></el-table-column>
        <el-table-column prop="field" label="字段" min-width="100"><template #default="{ row }">{{ row.field || '-' }}</template></el-table-column>
        <el-table-column prop="actor" label="执行人" min-width="120" />
      </el-table>
    </el-drawer>

    <el-dialog v-model="contactVisible" title="配置资源负责人" width="650px">
      <el-table :data="contactResource?.contacts || []" stripe><el-table-column label="职责"><template #default="{ row }">{{ roleText(row.role) }}</template></el-table-column><el-table-column label="联系人"><template #default="{ row }">{{ row.recipient_name || row.user_name || row.contact_name }}</template></el-table-column><el-table-column label="向下继承" width="100"><template #default="{ row }">{{ row.inherit_to_children ? '是' : '否' }}</template></el-table-column><el-table-column width="80"><template #default="{ row }"><el-button link type="danger" @click="removeContact(row)">删除</el-button></template></el-table-column></el-table>
      <el-form inline class="contact-form"><el-form-item label="职责"><el-select v-model="contactForm.role" style="width:150px"><el-option label="运维负责人" value="ops_owner" /><el-option label="项目负责人" value="project_owner" /><el-option label="产品负责人" value="product_owner" /><el-option label="值班人员" value="oncall" /></el-select></el-form-item><el-form-item label="告警接收人"><el-select v-model="contactForm.recipient" filterable style="width:190px"><el-option v-for="item in recipients" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item><el-form-item label="向下继承"><el-switch v-model="contactForm.inherit_to_children" /></el-form-item><el-button type="primary" :disabled="!contactForm.recipient" @click="addContact">添加</el-button></el-form>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Files, RefreshRight, Plus, List, Connection, Clock, Share } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { getAlertRecipients } from '@/api/modules/ops'
import {
  createResource, createResourceContact, deleteResource, deleteResourceContact, updateResource,
  getDiscoveryRuns, getDiscoverySources, getResourceChanges, getResourceRuntime, getResourceSummary,
  getResourceBusinessContexts, getResourceTopology, getResourceTypes, getResources, previewDiscoverySource, runDiscoverySource,
} from '@/api/modules/resourceCenter'

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('cmdb.ci.manage'))
const tabs = [{ key: 'resources', label: '资源清单', icon: List }, { key: 'discovery', label: '自动发现', icon: Connection }, { key: 'history', label: '发现历史', icon: Clock }, { key: 'topology', label: '资源关系', icon: Share }]
const activeTab = ref('resources')
const loadError = ref('')
const loading = ref(false); const summaryLoading = ref(false); const discoveryLoading = ref(false); const topologyLoading = ref(false)
const summary = ref({}); const resources = ref([]); const resourceTypes = ref([]); const discoverySources = ref([]); const discoveryRuns = ref([]); const topology = ref({ nodes: [], edges: [] })
const filters = ref({ search: '', type: '', status: '' })
const statusOptions = [{ value: 'pending', label: '待确认' }, { value: 'active', label: '使用中' }, { value: 'warning', label: '异常' }, { value: 'missing', label: '疑似失联' }, { value: 'offline', label: '已失联' }, { value: 'retired', label: '已下线' }]
const resourceDialogVisible = ref(false); const saving = ref(false)
const editingResourceId = ref(null)
const businessContexts = ref([])
const emptyResourceForm = () => ({ resource_type: '', name: '', display_name: '', environment: 'prod', status: 'active', primary_ip: '', product: '', business_system: '', business_contexts: [], criticality: 'medium', description: '', serial_number: '', os_image: '', endpoint: '', port: 0, version: '', attributes: {} })
const resourceForm = ref(emptyResourceForm())
const manualResourceTypes = computed(() => resourceTypes.value.filter(item => !['k8s_cluster', 'k8s_node'].includes(item.code)))
const selectedManualType = computed(() => resourceTypes.value.find(item => Number(item.id) === Number(resourceForm.value.resource_type)) || null)
const selectedManualTypeCategory = computed(() => selectedManualType.value?.category || '')
const previewVisible = ref(false); const preview = ref({}); const runningSourceId = ref(null)
const detailVisible = ref(false); const detailResource = ref(null); const detailRuntimeCounts = ref({}); const detailChanges = ref([]); const detailLoading = ref(false)
const contactVisible = ref(false); const contactResource = ref(null); const recipients = ref([]); const contactForm = ref({ role: 'ops_owner', recipient: null, inherit_to_children: true })

const normalize = value => value?.results || value || []
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
const environmentText = value => ({ prod: '生产', test: '测试', dev: '开发', unknown: '未指定' }[value] || value || '-')
const statusText = value => ({ pending: '待确认', active: '使用中', warning: '异常', missing: '疑似失联', offline: '已失联', retired: '已下线' }[value] || value)
const statusTag = value => ({ active: 'success', warning: 'warning', missing: 'danger', offline: 'danger', retired: 'info', pending: 'info' }[value] || 'info')
const sourceText = value => ({ manual: '手工', k8s: 'K8S发现', zabbix: 'Zabbix', prometheus: 'Prometheus', ssh: 'SSH' }[value] || value)
const contactSummary = items => (items || []).map(item => item.recipient_name || item.user_name || item.contact_name).filter(Boolean).join('、') || '-'
const roleText = value => ({ ops_owner: '运维负责人', project_owner: '项目负责人', product_owner: '产品负责人', oncall: '值班人员' }[value] || value)
const relationText = value => ({ belongs_to: '属于', contains: '包含', runs_on: '运行于', deployed_on: '部署于', depends_on: '依赖', monitored_by: '监控于' }[value] || value)
const sourceStatusText = value => ({ pending: '待发现', healthy: '正常', degraded: '部分成功', failed: '失败' }[value] || value)
const sourceStatusTag = value => ({ healthy: 'success', degraded: 'warning', failed: 'danger', pending: 'info' }[value] || 'info')
const runStatusText = value => ({ pending: '等待中', connecting: '连接中', collecting: '采集中', reconciling: '对账中', completed: '完成', partial: '部分完成', failed: '失败' }[value] || value)
const runStatusTag = value => value === 'completed' ? 'success' : value === 'failed' ? 'danger' : ['partial'].includes(value) ? 'warning' : 'info'
const changeActionText = value => ({ create: '自动发现新增', update: '自动发现更新', manual_create: '手工登记', manual_update: '手工修改' }[value] || value)
const requestErrorText = (error, fallback) => error?.response?.data?.detail || error?.message || fallback

async function fetchResources() { loading.value = true; try { resources.value = normalize(await getResources(filters.value)) } catch (error) { resources.value = []; loadError.value = requestErrorText(error, '资源清单加载失败') } finally { loading.value = false } }
async function fetchSummary() { summaryLoading.value = true; try { summary.value = await getResourceSummary() } catch (error) { summary.value = {}; loadError.value = requestErrorText(error, '资源统计加载失败') } finally { summaryLoading.value = false } }
async function fetchDiscovery() { discoveryLoading.value = true; try { const [sources, runs] = await Promise.all([getDiscoverySources(), getDiscoveryRuns()]); discoverySources.value = normalize(sources); discoveryRuns.value = normalize(runs) } catch (error) { discoverySources.value = []; discoveryRuns.value = []; loadError.value = requestErrorText(error, '自动发现数据加载失败') } finally { discoveryLoading.value = false } }
async function fetchTopology() { topologyLoading.value = true; try { topology.value = await getResourceTopology() } catch (error) { topology.value = { nodes: [], edges: [] }; loadError.value = requestErrorText(error, '资源关系加载失败') } finally { topologyLoading.value = false } }
async function refreshAll() { loadError.value = ''; const [types, contexts] = await Promise.allSettled([getResourceTypes(), getResourceBusinessContexts()]); if (types.status === 'fulfilled') resourceTypes.value = normalize(types.value); else loadError.value = requestErrorText(types.reason, '资源类型加载失败'); if (contexts.status === 'fulfilled') businessContexts.value = normalize(contexts.value); else loadError.value = requestErrorText(contexts.reason, '业务上下文加载失败'); await Promise.all([fetchSummary(), fetchResources(), fetchDiscovery()]); if (activeTab.value === 'topology') await fetchTopology() }
function openResourceDialog(row = null) { editingResourceId.value = row?.id || null; const attributes = row?.attributes || {}; resourceForm.value = row ? { resource_type: row.resource_type, name: row.name, display_name: row.display_name || '', environment: row.environment, status: row.status, primary_ip: row.primary_ip || '', product: row.product || '', business_system: row.business_system || '', business_contexts: row.business_contexts || [], criticality: row.criticality, description: row.description || '', serial_number: attributes.serial_number || attributes.instance_id || '', os_image: attributes.os_image || '', endpoint: attributes.endpoint || '', port: attributes.port || 0, version: attributes.version || '', attributes } : emptyResourceForm(); if (!row) resourceForm.value.resource_type = manualResourceTypes.value[0]?.id || ''; resourceDialogVisible.value = true }
async function saveResource() { if (!resourceForm.value.resource_type || !resourceForm.value.name.trim()) return ElMessage.warning('请选择资源类型并填写资源名称'); if (selectedManualTypeCategory.value === 'platform' && !resourceForm.value.endpoint.trim()) return ElMessage.warning('数据库和中间件需要填写访问地址'); saving.value = true; try { const { serial_number, os_image, endpoint, port, version, ...base } = resourceForm.value; const attributes = { ...(base.attributes || {}) }; if (serial_number) attributes.serial_number = serial_number; else delete attributes.serial_number; if (os_image) attributes.os_image = os_image; else delete attributes.os_image; if (endpoint) attributes.endpoint = endpoint; else delete attributes.endpoint; if (port) attributes.port = port; else delete attributes.port; if (version) attributes.version = version; else delete attributes.version; const payload = { ...base, attributes, primary_ip: base.primary_ip || null }; if (editingResourceId.value) await updateResource(editingResourceId.value, payload); else await createResource(payload); ElMessage.success(editingResourceId.value ? '资源已更新' : '资源已登记'); resourceDialogVisible.value = false; await refreshAll() } finally { saving.value = false } }
async function removeResource(row) { await deleteResource(row.id); ElMessage.success('资源已删除'); await refreshAll() }
async function previewSource(row) { try { preview.value = await previewDiscoverySource(row.id); previewVisible.value = true } catch (error) { ElMessage.error(error?.response?.data?.detail || '发现预览失败') } }
async function runSource(row) { runningSourceId.value = row.id; try { const run = await runDiscoverySource(row.id, true); if (run.status === 'failed') ElMessage.error(run.error || '自动发现失败'); else ElMessage.success(`发现完成：新增 ${run.created_count}，更新 ${run.updated_count}`); await refreshAll() } finally { runningSourceId.value = null } }
async function openDetail(row) { detailResource.value = row; detailRuntimeCounts.value = {}; detailChanges.value = []; detailVisible.value = true; detailLoading.value = true; try { const requests = [getResourceChanges(row.id)]; if (row.resource_type_code === 'k8s_cluster') requests.push(getResourceRuntime(row.id)); const [changes, runtime = []] = await Promise.all(requests); detailChanges.value = normalize(changes); detailRuntimeCounts.value = normalize(runtime).reduce((result, item) => ({ ...result, [item.kind]: (result[item.kind] || 0) + 1 }), {}) } catch (error) { ElMessage.error(error?.response?.data?.detail || '资源详情加载失败') } finally { detailLoading.value = false } }
async function openContactDialog(row) { contactResource.value = row; contactForm.value = { role: 'ops_owner', recipient: null, inherit_to_children: true }; if (!recipients.value.length) recipients.value = normalize(await getAlertRecipients({ page_size: 500 })); contactVisible.value = true }
async function addContact() { await createResourceContact({ resource: contactResource.value.id, role: contactForm.value.role, recipient: contactForm.value.recipient, inherit_to_children: contactForm.value.inherit_to_children }); ElMessage.success('负责人已添加'); await fetchResources(); contactResource.value = resources.value.find(item => item.id === contactResource.value.id); contactForm.value.recipient = null }
async function removeContact(row) { await deleteResourceContact(row.id); ElMessage.success('负责人已删除'); await fetchResources(); contactResource.value = resources.value.find(item => item.id === contactResource.value.id) }

watch(activeTab, tab => { if (tab === 'discovery' || tab === 'history') void fetchDiscovery(); if (tab === 'topology') void fetchTopology() })
onMounted(refreshAll)
</script>

<style scoped>
.resource-center-page{display:flex;flex-direction:column;gap:8px}.resource-hero{display:flex;align-items:center;justify-content:space-between;padding:16px 20px}.resource-title-row{display:flex;align-items:center;gap:12px}.resource-title-row h2{margin:0;font-size:21px}.resource-title-row p{margin:3px 0 0;color:#64748b;font-size:13px}.resource-title-icon{display:grid;place-items:center;width:38px;height:38px;border-radius:8px;background:#e0f2fe;color:#0369a1;font-size:20px}.resource-hero-actions{display:flex;gap:8px}.resource-summary{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.resource-stat{min-height:68px;padding:12px 16px;border:1px solid #e2e8f0;border-left:3px solid #0ea5e9;background:#fff;border-radius:6px;display:flex;align-items:center;justify-content:space-between}.resource-stat span{color:#64748b;font-size:13px}.resource-stat strong{font-size:24px;color:#0f172a}.resource-stat--success{border-left-color:#10b981}.resource-stat--warning{border-left-color:#f59e0b}.resource-stat--danger{border-left-color:#ef4444}.resource-tabs{margin:0}.resource-tabs .neo-tab-btn{display:flex;align-items:center;gap:5px}.resource-section{padding:0;overflow:hidden}.resource-toolbar{padding:10px 12px}.resource-search{width:300px}.resource-filter{width:150px}.resource-count{color:#64748b;font-size:13px}.resource-name-cell{display:flex;align-items:center;gap:10px}.resource-name-cell div{min-width:0;display:flex;flex-direction:column}.resource-name-cell small{color:#94a3b8;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.resource-state{width:8px;height:8px;border-radius:50%;background:#94a3b8;flex:none}.resource-state--active{background:#10b981}.resource-state--warning{background:#f59e0b}.resource-state--missing,.resource-state--offline{background:#ef4444}.runtime-counts{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.runtime-counts span{padding:4px 8px;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:4px;color:#334155;font-size:12px}.resource-json{max-height:300px;overflow:auto;margin:0;white-space:pre-wrap;font-size:12px}.resource-hint{color:#64748b;font-size:13px}.contact-form{margin-top:16px;padding-top:14px;border-top:1px solid #e2e8f0}.K8s-cluster-option{display:flex;justify-content:space-between;gap:20px}.K8s-cluster-option__meta{color:#94a3b8;font-size:12px}@media(max-width:900px){.resource-hero{align-items:flex-start;gap:12px}.resource-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.resource-toolbar,.workbench-toolbar-left{align-items:stretch;flex-direction:column}.resource-search,.resource-filter{width:100%}}
</style>
