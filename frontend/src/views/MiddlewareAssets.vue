<template>
  <div class="middleware-page fade-in">
    <section class="middleware-hero">
      <div class="hero-copy">
        <span class="hero-icon"><el-icon><Coin /></el-icon></span>
        <div>
          <h2>中间件与数据库资产</h2>
          <p>只展示已登记的真实资产。运行指标与健康状态由后续监控接入产生，平台不会自动填充任何资产记录。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button v-if="canManage" type="primary" :icon="Plus" @click="openRegistration()">登记资产</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="loadOverview">刷新</el-button>
      </div>
    </section>

    <section class="asset-summary-grid">
      <button
        v-for="item in typeCards"
        :key="item.key"
        type="button"
        class="asset-summary-card"
        :class="[{ active: activeType === item.key }, `is-${item.key}`]"
        @click="toggleType(item.key)"
      >
        <span class="summary-icon"><el-icon><component :is="item.icon" /></el-icon></span>
        <span class="summary-body">
          <strong>{{ typeCount(item.key) }}</strong>
          <span>{{ item.label }}</span>
          <small>{{ item.description }}</small>
        </span>
      </button>
    </section>

    <section class="asset-workspace">
      <div class="workspace-toolbar">
        <div>
          <strong>{{ activeType ? `${typeLabel(activeType)} 资产` : '全部中间件资产' }}</strong>
          <span>共 {{ filteredAssets.length }} 条登记记录</span>
        </div>
        <div class="toolbar-actions">
          <el-button v-if="activeType" link type="primary" @click="activeType = ''">查看全部</el-button>
          <el-tag effect="plain" type="info">仅登记信息</el-tag>
        </div>
      </div>

      <el-table v-if="filteredAssets.length" :data="filteredAssets" stripe border v-loading="loading">
        <el-table-column prop="name" label="资产名称" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="asset-name-cell">
              <span class="asset-dot" :class="`is-${row.asset_type}`"></span>
              <strong>{{ row.name }}</strong>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="asset_type_label" label="类型" width="130">
          <template #default="{ row }"><el-tag effect="plain">{{ row.asset_type_label || typeLabel(row.asset_type) }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="environment" label="环境" width="120" show-overflow-tooltip />
        <el-table-column prop="endpoint" label="访问地址" min-width="230" show-overflow-tooltip>
          <template #default="{ row }"><code>{{ row.endpoint }}</code></template>
        </el-table-column>
        <el-table-column label="认证" width="150">
          <template #default="{ row }">{{ row.username || '-' }}<span v-if="row.password_configured"> / 已配置密码</span></template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="110">
          <template #default="{ row }">{{ row.version || '-' }}</template>
        </el-table-column>
        <el-table-column prop="status_label" label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="statusType(row.status)">{{ row.status_label || statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :disabled="!canManage" @click="openRegistration(row)">编辑</el-button>
            <el-popconfirm title="确定删除这条资产登记吗？" @confirm="deleteAsset(row)">
              <template #reference><el-button link type="danger" :disabled="!canManage">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-else
        :description="activeType ? `暂无已登记的 ${typeLabel(activeType)} 资产` : '暂无已登记的中间件资产'"
        class="asset-empty"
      >
        <el-button v-if="canManage" type="primary" :icon="Plus" @click="openRegistration(null, activeType)">登记第一条资产</el-button>
      </el-empty>
    </section>

    <el-dialog v-model="registrationVisible" :title="editingId ? '编辑中间件资产' : '登记中间件资产'" width="560px" destroy-on-close>
      <el-form :model="registrationForm" label-width="92px">
        <el-form-item label="资产类型" required>
          <el-select v-model="registrationForm.asset_type" style="width:100%">
            <el-option v-for="item in typeCards" :key="item.key" :label="item.label" :value="item.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="资产名称" required>
          <el-input v-model="registrationForm.name" placeholder="请输入实际资产或集群名称" maxlength="128" />
        </el-form-item>
        <el-form-item label="所属环境" required>
          <el-input v-model="registrationForm.environment" placeholder="例如 prod、test 或业务环境名称" maxlength="32" />
        </el-form-item>
        <el-form-item label="访问地址" required>
          <el-input v-model="registrationForm.endpoint" placeholder="请输入实际连接地址或管理地址" maxlength="255" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="registrationForm.username" placeholder="部分资产需要认证时填写" maxlength="128" autocomplete="off" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="registrationForm.password" type="password" show-password :placeholder="editingId ? '留空则保留现有密码' : '可选'" maxlength="255" autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="版本">
          <el-input v-model="registrationForm.version" placeholder="可选" maxlength="64" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="registrationForm.description" type="textarea" :rows="3" placeholder="可选" maxlength="255" show-word-limit />
        </el-form-item>
        <el-alert title="登记不会自动生成节点、QPS、容量或健康数据；接入对应监控源后再展示真实指标。" type="info" :closable="false" show-icon />
      </el-form>
      <template #footer>
        <el-button @click="registrationVisible = false">取消</el-button>
        <el-button type="primary" :loading="registrationSubmitting" @click="submitRegistration">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Coin, Connection, Grid, Plus, Refresh } from '@element-plus/icons-vue'

import { getMiddlewareOverview, runMiddlewareAction } from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const loading = ref(false)
const overview = ref({ assets: [], summary: { total: 0, by_type: {}, by_status: {} } })
const activeType = ref('')
const registrationVisible = ref(false)
const registrationSubmitting = ref(false)
const editingId = ref(null)
const registrationForm = reactive(emptyForm())

const typeCards = [
  { key: 'redis', label: 'Redis', description: '缓存与会话存储', icon: Grid },
  { key: 'kafka', label: 'Kafka', description: '消息流与消费队列', icon: Connection },
  { key: 'rocketmq', label: 'RocketMQ', description: '消息队列与 Broker', icon: Connection },
  { key: 'database', label: '数据库', description: 'MySQL、PostgreSQL 等', icon: Coin },
]

const canManage = computed(() => authStore.hasPermission('ops.middleware.manage'))
const assets = computed(() => Array.isArray(overview.value.assets) ? overview.value.assets : [])
const filteredAssets = computed(() => activeType.value
  ? assets.value.filter((item) => item.asset_type === activeType.value)
  : assets.value)

function emptyForm(assetType = 'redis') {
  return { asset_type: assetType, name: '', environment: 'prod', endpoint: '', username: '', password: '', version: '', description: '' }
}

function typeCount(type) {
  return Number(overview.value.summary?.by_type?.[type]) || 0
}

function typeLabel(type) {
  return typeCards.find((item) => item.key === type)?.label || type || '中间件'
}

function statusType(status) {
  if (status === 'healthy') return 'success'
  if (status === 'warning') return 'warning'
  if (status === 'offline') return 'danger'
  return 'info'
}

function statusLabel(status) {
  return { unknown: '未检测', healthy: '正常', warning: '异常', offline: '离线' }[status] || '未检测'
}

function toggleType(type) {
  activeType.value = activeType.value === type ? '' : type
}

async function loadOverview() {
  loading.value = true
  try {
    overview.value = await getMiddlewareOverview()
  } finally {
    loading.value = false
  }
}

function openRegistration(row = null, preferredType = '') {
  editingId.value = row?.id || null
  Object.assign(registrationForm, row ? {
    asset_type: row.asset_type,
    name: row.name,
    environment: row.environment,
    endpoint: row.endpoint,
    username: row.username || '',
    password: '',
    version: row.version || '',
    description: row.description || '',
  } : emptyForm(preferredType || activeType.value || 'redis'))
  registrationVisible.value = true
}

async function submitRegistration() {
  const payload = Object.fromEntries(
    Object.entries(registrationForm).map(([key, value]) => [key, String(value || '').trim()]),
  )
  if (!payload.asset_type || !payload.name || !payload.environment || !payload.endpoint) {
    return ElMessage.warning('请完整填写资产类型、名称、环境和访问地址')
  }
  registrationSubmitting.value = true
  try {
    const response = await runMiddlewareAction({
      action: editingId.value ? 'update_asset' : 'create_asset',
      target_id: editingId.value || undefined,
      payload,
    })
    overview.value = response.data || overview.value
    activeType.value = payload.asset_type
    registrationVisible.value = false
    ElMessage.success(response.message || '中间件资产已保存')
  } finally {
    registrationSubmitting.value = false
  }
}

async function deleteAsset(row) {
  const response = await runMiddlewareAction({ action: 'delete_asset', target_id: row.id })
  overview.value = response.data || overview.value
  ElMessage.success(response.message || '中间件资产已删除')
}

onMounted(loadOverview)
</script>

<style scoped>
.middleware-page { display: flex; flex-direction: column; gap: 10px; }
.middleware-hero { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 15px 18px; border: 1px solid rgba(148, 163, 184, .2); border-radius: 16px; background: linear-gradient(135deg, #fff, #f5f9ff); box-shadow: 0 12px 28px rgba(15, 23, 42, .05); }
.hero-copy { display: flex; align-items: center; min-width: 0; gap: 12px; }
.hero-icon { display: inline-flex; align-items: center; justify-content: center; width: 42px; height: 42px; flex: 0 0 auto; border-radius: 13px; color: #fff; font-size: 21px; background: linear-gradient(135deg, #2563eb, #0f766e); }
.hero-copy h2 { margin: 0; color: #0f172a; font-size: 23px; }
.hero-copy p { margin: 4px 0 0; color: #64748b; font-size: 13px; line-height: 1.5; }
.hero-actions { display: flex; flex: 0 0 auto; gap: 8px; }
.asset-summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.asset-summary-card { display: flex; align-items: center; gap: 12px; min-height: 92px; padding: 14px; color: inherit; text-align: left; cursor: pointer; border: 1px solid rgba(148, 163, 184, .2); border-radius: 12px; background: #fff; box-shadow: 0 8px 20px rgba(15, 23, 42, .04); transition: .18s ease; }
.asset-summary-card:hover, .asset-summary-card.active { transform: translateY(-1px); border-color: rgba(37, 99, 235, .34); box-shadow: 0 12px 26px rgba(37, 99, 235, .1); }
.summary-icon { display: inline-flex; align-items: center; justify-content: center; width: 42px; height: 42px; flex: 0 0 auto; border-radius: 12px; color: #2563eb; background: #eff6ff; font-size: 20px; }
.is-redis .summary-icon { color: #dc2626; background: #fef2f2; }
.is-kafka .summary-icon { color: #7c3aed; background: #f5f3ff; }
.is-rocketmq .summary-icon { color: #d97706; background: #fffbeb; }
.is-database .summary-icon { color: #0f766e; background: #f0fdfa; }
.summary-body { display: flex; flex-direction: column; min-width: 0; }
.summary-body strong { color: #0f172a; font-size: 24px; line-height: 1; }
.summary-body span { margin-top: 5px; color: #334155; font-size: 13px; font-weight: 700; }
.summary-body small { margin-top: 2px; color: #94a3b8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-workspace { min-width: 0; padding: 14px; border: 1px solid rgba(148, 163, 184, .2); border-radius: 14px; background: #fff; box-shadow: 0 10px 24px rgba(15, 23, 42, .04); }
.workspace-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0 2px 12px; }
.workspace-toolbar > div:first-child { display: flex; flex-direction: column; gap: 3px; }
.workspace-toolbar strong { color: #0f172a; font-size: 15px; }
.workspace-toolbar span { color: #64748b; font-size: 12px; }
.toolbar-actions { display: flex; align-items: center; gap: 8px; }
.asset-name-cell { display: flex; align-items: center; gap: 8px; min-width: 0; }
.asset-dot { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%; background: #94a3b8; }
.asset-dot.is-redis { background: #ef4444; }
.asset-dot.is-kafka { background: #8b5cf6; }
.asset-dot.is-rocketmq { background: #f59e0b; }
.asset-dot.is-database { background: #14b8a6; }
code { color: #334155; font-family: "Cascadia Code", Consolas, monospace; font-size: 12px; }
.asset-empty { min-height: 280px; }
@media (max-width: 1100px) { .asset-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .middleware-hero, .workspace-toolbar { align-items: flex-start; flex-direction: column; } .hero-actions { width: 100%; flex-wrap: wrap; } .asset-summary-grid { grid-template-columns: 1fr; } }
</style>
