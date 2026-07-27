<template>
  <section class="panel external-source-panel">
    <div class="section-head">
      <div>
        <h3>外部告警接入</h3>
        <p>集中管理 Alertmanager 与 Zabbix 的接入地址、业务归属、通知和研判。</p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadSources">刷新</el-button>
        <el-button v-if="canManage" type="primary" :icon="Plus" @click="openSource()">新增接入源</el-button>
      </div>
    </div>

    <div class="source-stats">
      <div class="stat-item"><span>接入源</span><strong>{{ sources.length }}</strong></div>
      <div class="stat-item"><span>运行正常</span><strong>{{ sourceStats.healthy }}</strong></div>
      <div class="stat-item"><span>待绑定告警</span><strong>{{ sourceStats.unbound }}</strong></div>
      <div class="stat-item"><span>已接收告警</span><strong>{{ sourceStats.received }}</strong></div>
    </div>

    <el-table :data="sources" stripe size="small" v-loading="loading" empty-text="尚未登记外部告警接入源">
      <el-table-column prop="name" label="接入源" min-width="180">
        <template #default="{ row }">
          <div class="source-name">{{ row.name }}</div>
          <div class="source-code">{{ row.code }}</div>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="120">
        <template #default="{ row }">{{ row.provider_display || providerText(row.provider) }}</template>
      </el-table-column>
      <el-table-column label="默认业务上下文" min-width="160">
        <template #default="{ row }">{{ row.default_knowledge_environment_detail?.name || '未设置' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="healthTone(row.health_status)">{{ healthText(row.health_status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="通知 / 研判" width="130">
        <template #default="{ row }">
          <span>{{ row.notify_enabled ? '通知开' : '通知关' }} / {{ row.analyze_enabled ? '研判开' : '研判关' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="活跃 / 待绑定" width="120">
        <template #default="{ row }">{{ row.active_alert_count || 0 }} / {{ row.unbound_alert_count || 0 }}</template>
      </el-table-column>
      <el-table-column prop="received_alerts" label="接收数" width="90" />
      <el-table-column label="最近接收" width="170">
        <template #default="{ row }">{{ formatTime(row.last_received_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="showLogs(row)">记录</el-button>
          <el-button v-if="canManage" link type="success" @click="openPreview(row)">测试</el-button>
          <el-button v-if="canManage" link @click="openSource(row)">配置</el-button>
          <el-button v-if="canManage" link type="warning" @click="rotateToken(row)">轮换 Token</el-button>
          <el-button v-if="canManage" link type="danger" @click="removeSource(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-alert
      v-if="sources.some((item) => item.last_error)"
      class="source-error"
      type="warning"
      :closable="false"
      title="部分接入源最近一次请求失败，可在接入记录中查看原因。"
    />
  </section>

  <el-dialog v-model="sourceDialog.visible" :title="sourceDialog.form.id ? '配置外部告警接入源' : '新增外部告警接入源'" width="min(820px, calc(100vw - 32px))" destroy-on-close>
    <el-form :model="sourceDialog.form" label-width="130px" class="source-form">
      <div class="form-grid">
        <el-form-item label="名称"><el-input v-model="sourceDialog.form.name" placeholder="例如：生产 Alertmanager" /></el-form-item>
        <el-form-item label="编码"><el-input v-model="sourceDialog.form.code" :disabled="Boolean(sourceDialog.form.id)" placeholder="production-alertmanager" /></el-form-item>
        <el-form-item label="类型">
          <el-segmented v-model="sourceDialog.form.provider" :disabled="Boolean(sourceDialog.form.id)" :options="providerOptions" />
        </el-form-item>
        <el-form-item label="默认业务上下文">
          <el-select v-model="sourceDialog.form.default_knowledge_environment" clearable filterable placeholder="未匹配规则时的归属">
            <el-option v-for="item in contextOptions" :key="item.id" :label="contextLabel(item)" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="每分钟请求上限"><el-input-number v-model="sourceDialog.form.rate_limit_per_minute" :min="1" :max="10000" /></el-form-item>
        <el-form-item label="运行开关" class="switch-row">
          <el-checkbox v-model="sourceDialog.form.is_enabled">允许接入</el-checkbox>
          <el-checkbox v-model="sourceDialog.form.notify_enabled">发送通知</el-checkbox>
          <el-checkbox v-model="sourceDialog.form.analyze_enabled">智能研判</el-checkbox>
        </el-form-item>
      </div>
      <el-form-item label="业务上下文映射">
        <div class="mapping-editor">
          <div v-for="(rule, ruleIndex) in sourceDialog.form.mapping_rules" :key="rule.local_id" class="mapping-rule">
            <div class="mapping-head">
              <span>规则 {{ ruleIndex + 1 }}</span>
              <el-input-number v-model="rule.priority" :min="1" :max="9999" controls-position="right" />
              <el-select v-model="rule.knowledge_environment_id" filterable placeholder="目标业务上下文">
                <el-option v-for="item in contextOptions" :key="item.id" :label="contextLabel(item)" :value="item.id" />
              </el-select>
              <el-button text type="danger" :icon="Delete" title="删除映射规则" @click="removeMappingRule(ruleIndex)" />
            </div>
            <div v-for="(matcher, matcherIndex) in rule.matchers" :key="matcher.local_id" class="matcher-row">
              <el-input v-model="matcher.key" placeholder="标签或字段，如 namespace" />
              <el-select v-model="matcher.operator">
                <el-option label="等于" value="==" />
                <el-option label="不等于" value="!=" />
                <el-option label="正则匹配" value="=~" />
                <el-option label="正则不匹配" value="!~" />
                <el-option label="包含" value="contains" />
              </el-select>
              <el-input v-model="matcher.value" placeholder="匹配值" />
              <el-button text type="danger" :icon="Delete" title="删除条件" @click="removeMatcher(rule, matcherIndex)" />
            </div>
            <el-button text type="primary" :icon="Plus" @click="addMatcher(rule)">增加条件</el-button>
          </div>
          <el-button :icon="Plus" @click="addMappingRule">增加映射规则</el-button>
          <span class="mapping-help">规则按优先级匹配；均未命中时使用默认业务上下文，否则进入待绑定告警。</span>
        </div>
      </el-form-item>
      <el-form-item label="说明"><el-input v-model="sourceDialog.form.description" type="textarea" :rows="2" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="sourceDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="sourceDialog.saving" @click="saveSource">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="tokenDialog.visible" title="接入凭据" width="min(680px, calc(100vw - 32px))" destroy-on-close>
    <el-alert type="warning" :closable="false" title="Token 仅显示一次，请立即配置到外部告警系统。" />
    <div class="credential-row"><span>接入地址</span><code>{{ tokenDialog.endpoint }}</code><el-button :icon="CopyDocument" @click="copyText(tokenDialog.endpoint)">复制</el-button></div>
    <div class="credential-row"><span>Bearer Token</span><code>{{ tokenDialog.token }}</code><el-button :icon="CopyDocument" @click="copyText(tokenDialog.token)">复制</el-button></div>
    <pre class="config-sample">{{ tokenDialog.sample }}</pre>
  </el-dialog>

  <el-dialog v-model="logDialog.visible" :title="`${logDialog.source?.name || ''} · 接入记录`" width="min(900px, calc(100vw - 32px))" destroy-on-close>
    <el-table :data="logDialog.logs" size="small" stripe v-loading="logDialog.loading" empty-text="暂无接入记录">
      <el-table-column label="时间" width="175"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
      <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag size="small" :type="logTone(row.status)">{{ row.status_display || row.status }}</el-tag></template></el-table-column>
      <el-table-column prop="http_status" label="HTTP" width="70" />
      <el-table-column prop="alert_count" label="告警数" width="80" />
      <el-table-column prop="duration_ms" label="耗时(ms)" width="90" />
      <el-table-column prop="remote_addr" label="来源地址" width="140" />
      <el-table-column prop="message" label="结果" min-width="220" show-overflow-tooltip />
    </el-table>
  </el-dialog>

  <el-dialog v-model="previewDialog.visible" :title="`${previewDialog.source?.name || ''} · 载荷与归属预览`" width="min(900px, calc(100vw - 32px))" destroy-on-close>
    <el-input v-model="previewDialog.text" type="textarea" :rows="14" spellcheck="false" />
    <div class="preview-actions"><el-button type="primary" :loading="previewDialog.loading" @click="previewPayload">验证载荷</el-button></div>
    <el-table v-if="previewDialog.results.length" :data="previewDialog.results" size="small" stripe>
      <el-table-column prop="title" label="告警" min-width="200" />
      <el-table-column prop="level" label="级别" width="90" />
      <el-table-column prop="resource" label="资源" min-width="150" />
      <el-table-column prop="binding_status" label="归属" width="90" />
      <el-table-column label="业务上下文" min-width="160"><template #default="{ row }">{{ row.knowledge_environment?.name || '待绑定' }}</template></el-table-column>
    </el-table>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Delete, Plus, Refresh } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { getAIOpsKnowledgeEnvironments } from '@/api/modules/aiops'
import {
  createExternalAlertSource,
  deleteExternalAlertSource,
  getExternalAlertSourceLogs,
  getExternalAlertSources,
  previewExternalAlertSourcePayload,
  rotateExternalAlertSourceToken,
  updateExternalAlertSource,
} from '@/api/modules/ops'

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('ops.alert.config.manage'))
const loading = ref(false)
const sources = ref([])
const contextOptions = ref([])
const providerOptions = [
  { label: 'Alertmanager', value: 'alertmanager' },
  { label: 'Zabbix', value: 'zabbix' },
]

const sourceStats = computed(() => ({
  healthy: sources.value.filter((item) => item.health_status === 'healthy').length,
  unbound: sources.value.reduce((total, item) => total + Number(item.unbound_alert_count || 0), 0),
  received: sources.value.reduce((total, item) => total + Number(item.received_alerts || 0), 0),
}))

const sourceDialog = reactive({ visible: false, saving: false, form: emptySource() })
const tokenDialog = reactive({ visible: false, endpoint: '', token: '', sample: '' })
const logDialog = reactive({ visible: false, loading: false, source: null, logs: [] })
const previewDialog = reactive({ visible: false, loading: false, source: null, text: '', results: [] })

function listOf(response) {
  return Array.isArray(response) ? response : (response?.results || [])
}

function localId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function emptyMatcher(value = {}) {
  return { local_id: localId(), key: '', operator: '==', value: '', ...value }
}

function emptyRule(value = {}, index = 0) {
  return {
    local_id: localId(),
    priority: value.priority || (index + 1) * 10,
    knowledge_environment_id: value.knowledge_environment_id || null,
    matchers: (value.matchers || []).map((item) => emptyMatcher(item)),
  }
}

function emptySource() {
  return {
    id: null,
    name: '',
    code: '',
    provider: 'alertmanager',
    default_knowledge_environment: null,
    mapping_rules: [],
    rate_limit_per_minute: 120,
    is_enabled: true,
    notify_enabled: false,
    analyze_enabled: true,
    description: '',
  }
}

async function loadSources() {
  loading.value = true
  try {
    const [sourceResponse, contextResponse] = await Promise.all([
      getExternalAlertSources({ page_size: 500 }),
      getAIOpsKnowledgeEnvironments({ page_size: 500, is_enabled: true }),
    ])
    sources.value = listOf(sourceResponse)
    contextOptions.value = listOf(contextResponse)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '外部告警接入源加载失败')
  } finally {
    loading.value = false
  }
}

function openSource(row = null) {
  sourceDialog.form = row
    ? {
        ...emptySource(),
        ...row,
        mapping_rules: (row.mapping_rules || []).map((item, index) => emptyRule(item, index)),
      }
    : emptySource()
  sourceDialog.visible = true
}

function addMappingRule() {
  const rule = emptyRule({}, sourceDialog.form.mapping_rules.length)
  rule.matchers.push(emptyMatcher())
  sourceDialog.form.mapping_rules.push(rule)
}

function removeMappingRule(index) {
  sourceDialog.form.mapping_rules.splice(index, 1)
}

function addMatcher(rule) {
  rule.matchers.push(emptyMatcher())
}

function removeMatcher(rule, index) {
  rule.matchers.splice(index, 1)
  if (!rule.matchers.length) rule.matchers.push(emptyMatcher())
}

function sourcePayload() {
  const form = sourceDialog.form
  const mappingRules = form.mapping_rules.map((rule) => ({
    priority: Number(rule.priority || 0),
    knowledge_environment_id: rule.knowledge_environment_id,
    matchers: rule.matchers.map((item) => ({ key: item.key.trim(), operator: item.operator, value: item.value })),
  }))
  return {
    name: form.name.trim(),
    code: form.code.trim(),
    provider: form.provider,
    default_knowledge_environment: form.default_knowledge_environment || null,
    mapping_rules: mappingRules,
    rate_limit_per_minute: Number(form.rate_limit_per_minute || 120),
    is_enabled: Boolean(form.is_enabled),
    notify_enabled: Boolean(form.notify_enabled),
    analyze_enabled: Boolean(form.analyze_enabled),
    description: form.description || '',
  }
}

function apiErrorMessage(error, fallback) {
  const data = error?.response?.data
  if (!data) return fallback
  if (typeof data === 'string') return data
  if (data.detail) return data.detail
  const entry = Object.entries(data)[0]
  if (!entry) return fallback
  const [field, messages] = entry
  const message = Array.isArray(messages) ? messages[0] : messages
  return `${field}: ${message || fallback}`
}

async function saveSource() {
  if (!sourceDialog.form.name.trim()) return ElMessage.warning('请输入接入源名称')
  if (!sourceDialog.form.id && !sourceDialog.form.code.trim()) return ElMessage.warning('请输入接入源编码')
  for (const rule of sourceDialog.form.mapping_rules) {
    if (!rule.knowledge_environment_id || rule.matchers.some((item) => !item.key.trim())) {
      return ElMessage.warning('请完整填写业务上下文映射规则')
    }
  }
  sourceDialog.saving = true
  try {
    const result = sourceDialog.form.id
      ? await updateExternalAlertSource(sourceDialog.form.id, sourcePayload())
      : await createExternalAlertSource(sourcePayload())
    sourceDialog.visible = false
    if (result.token) showToken(result)
    ElMessage.success('外部告警接入源已保存')
    await loadSources()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '接入源保存失败，请检查表单'))
  } finally {
    sourceDialog.saving = false
  }
}

function showToken(result, source = result) {
  tokenDialog.endpoint = source.endpoint || result.endpoint || ''
  tokenDialog.token = result.token || ''
  tokenDialog.sample = source.provider === 'zabbix'
    ? `Authorization: Bearer ${result.token || '<TOKEN>'}\nContent-Type: application/json`
    : `- name: xing-cloud-webhook\n  webhook_configs:\n    - url: ${tokenDialog.endpoint}\n      send_resolved: true\n      http_config:\n        authorization:\n          type: Bearer\n          credentials: ${result.token || '<TOKEN>'}`
  tokenDialog.visible = true
}

async function rotateToken(row) {
  try {
    await ElMessageBox.confirm('轮换后旧 Token 会立即失效，确认继续？', '轮换 Token', { type: 'warning' })
    const result = await rotateExternalAlertSourceToken(row.id)
    showToken(result, row)
    await loadSources()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(apiErrorMessage(error, 'Token 轮换失败'))
  }
}

async function removeSource(row) {
  try {
    await ElMessageBox.confirm('仅没有告警和接入记录的接入源可以删除；已有数据时请改为停用。', '删除接入源', { type: 'warning' })
    await deleteExternalAlertSource(row.id)
    ElMessage.success('接入源已删除')
    await loadSources()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(apiErrorMessage(error, '接入源删除失败'))
  }
}

async function showLogs(row) {
  logDialog.visible = true
  logDialog.source = row
  logDialog.loading = true
  try {
    logDialog.logs = listOf(await getExternalAlertSourceLogs(row.id, { page_size: 100 }))
  } catch (error) {
    logDialog.logs = []
    ElMessage.error(apiErrorMessage(error, '接入记录加载失败'))
  } finally {
    logDialog.loading = false
  }
}

function samplePayload(provider) {
  if (provider === 'zabbix') {
    return { event_id: 'test-1', trigger_id: 'trigger-1', trigger_name: 'CPU 使用率过高', severity: 'warning', host_name: 'server-01', message: 'CPU usage is 90%', event_status: 'PROBLEM' }
  }
  return { status: 'firing', receiver: 'xing-cloud', alerts: [{ status: 'firing', labels: { alertname: 'PodWaiting', severity: 'warning', namespace: 'default', pod: 'pod-a' }, annotations: { summary: 'Pod Waiting' }, startsAt: new Date().toISOString(), fingerprint: 'preview-only' }] }
}

function openPreview(row) {
  previewDialog.source = row
  previewDialog.text = JSON.stringify(samplePayload(row.provider), null, 2)
  previewDialog.results = []
  previewDialog.visible = true
}

async function previewPayload() {
  let payload
  try {
    payload = JSON.parse(previewDialog.text)
  } catch {
    return ElMessage.error('请输入有效的 JSON 载荷')
  }
  previewDialog.loading = true
  try {
    const result = await previewExternalAlertSourcePayload(previewDialog.source.id, payload)
    previewDialog.results = result.results || []
    ElMessage.success('载荷格式和业务归属验证通过，不会创建真实告警')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '载荷验证失败'))
  } finally {
    previewDialog.loading = false
  }
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value || '')
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败，请手动选择文本')
  }
}

function providerText(value) {
  return providerOptions.find((item) => item.value === value)?.label || value || '-'
}

function healthText(value) {
  return { healthy: '正常', pending: '待验证', error: '异常', disabled: '已停用' }[value] || value
}

function healthTone(value) {
  return { healthy: 'success', pending: 'info', error: 'danger', disabled: 'info' }[value] || 'info'
}

function logTone(value) {
  return { accepted: 'success', rejected: 'warning', error: 'danger' }[value] || 'info'
}

function contextLabel(item) {
  return `${item.name}${item.code ? ` (${item.code})` : ''}`
}

function formatTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN', { hour12: false })
}

onMounted(loadSources)
</script>

<style scoped>
.external-source-panel { min-width: 0; }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.section-head h3 { margin: 0; font-size: 17px; }
.section-head p { margin: 5px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
.head-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.source-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.stat-item { border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 12px 14px; display: flex; align-items: center; justify-content: space-between; background: var(--el-fill-color-blank); }
.stat-item span { color: var(--el-text-color-secondary); font-size: 13px; }
.stat-item strong { font-size: 21px; }
.source-name { font-weight: 600; }
.source-code { color: var(--el-text-color-secondary); font-size: 12px; margin-top: 3px; }
.source-error { margin-top: 14px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 18px; }
.switch-row :deep(.el-form-item__content) { flex-wrap: wrap; }
.mapping-editor { width: 100%; display: grid; gap: 10px; }
.mapping-rule { border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 10px; display: grid; gap: 8px; }
.mapping-head { display: grid; grid-template-columns: 80px 120px minmax(180px, 1fr) 36px; gap: 8px; align-items: center; }
.matcher-row { display: grid; grid-template-columns: minmax(150px, 1fr) 130px minmax(180px, 1fr) 36px; gap: 8px; align-items: center; }
.mapping-help { color: var(--el-text-color-secondary); font-size: 12px; }
.credential-row { display: grid; grid-template-columns: 100px minmax(0, 1fr) auto; gap: 10px; align-items: center; margin-top: 16px; }
.credential-row code { display: block; padding: 9px; background: var(--el-fill-color-light); border-radius: 4px; overflow-wrap: anywhere; }
.config-sample { margin: 16px 0 0; padding: 12px; background: #101418; color: #d7e0e8; border-radius: 6px; overflow: auto; }
.preview-actions { display: flex; justify-content: flex-end; margin: 10px 0; }
@media (max-width: 768px) {
  .section-head { flex-direction: column; }
  .source-stats, .form-grid { grid-template-columns: 1fr; }
  .mapping-head, .matcher-row, .credential-row { grid-template-columns: 1fr; }
}
</style>
