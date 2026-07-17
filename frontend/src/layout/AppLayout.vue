<template>
  <div class="app-layout">
    <aside class="sidebar" :class="{ collapsed: appStore.sidebarCollapsed }">
      <div class="sidebar-logo">
        <div class="logo-icon">
          <img src="@/assets/brand-mark.svg" alt="Xing-Cloud" class="brand-mark" />
        </div>
        <div class="logo-copy">
          <span class="logo-text">Xing-Cloud</span>
          <span class="logo-subtext">一屏观测，全程闭环</span>
        </div>
      </div>

      <el-menu
        :default-active="activeMenuPath"
        class="sidebar-nav el-menu-vertical"
        :collapse="appStore.sidebarCollapsed"
        router
        :collapse-transition="false"
        :default-openeds="defaultOpenMenuKeys"
      >
        <template v-for="item in visibleMenuItems" :key="item.title">
          <el-sub-menu v-if="item.children?.length" :index="item.menuKey || item.moduleKey || item.title">
            <template #title>
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.title }}</span>
            </template>
            <el-menu-item
              v-for="child in item.children"
              :key="child.menuKey || child.path"
              :index="child.menuKey || child.path"
              :route="child.route || child.path"
            >
              <template #title>
                <el-icon v-if="child.icon"><component :is="child.icon" /></el-icon>
                <span>{{ child.title }}</span>
              </template>
            </el-menu-item>
          </el-sub-menu>

          <el-menu-item
            v-else
            class="sidebar-direct-item"
            :index="item.menuKey || item.moduleKey || item.path"
            :route="item.route || item.path"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>
              <span>{{ item.title }}</span>
            </template>
          </el-menu-item>
        </template>
      </el-menu>
    </aside>

    <div class="main-area">
      <header class="header">
        <div class="header-left">
          <button class="collapse-btn" @click="appStore.toggleSidebar">
            <el-icon><Fold v-if="!appStore.sidebarCollapsed" /><Expand v-else /></el-icon>
          </button>
          <span class="breadcrumb">{{ currentTitle }}</span>
          <div class="business-context-switch">
            <span class="business-context-switch__label">业务上下文</span>
            <el-select
              v-model="businessContextStore.currentContextId"
              class="business-context-switch__select"
              size="small"
              filterable
              :disabled="!businessContextStore.contexts.length"
              :loading="businessContextStore.loading"
              placeholder="未配置业务上下文"
              @change="businessContextStore.selectContext"
            >
              <el-option
                v-for="item in businessContextStore.contexts"
                :key="item.id"
                :label="item.name"
                :value="String(item.id)"
              >
                <span>{{ item.name }}</span>
                <span class="business-context-switch__code">{{ item.code }}</span>
              </el-option>
            </el-select>
            <el-button
              v-if="businessContextStore.loaded && !businessContextStore.contexts.length && authStore.hasPermission('aiops.knowledge.view')"
              class="business-context-switch__configure"
              link
              type="primary"
              size="small"
              @click="router.push('/aiops/knowledge/config')"
            >
              去配置
            </el-button>
          </div>
        </div>
        <div class="header-right">
          <el-tooltip content="查看 AI Agent 产品介绍" placement="bottom">
            <button class="promo-trigger" type="button" @click="openAIAgentPromo">
              <el-icon :size="17"><Promotion /></el-icon>
              <span>产品介绍</span>
            </button>
          </el-tooltip>

          <el-tooltip v-if="canOpenAIOpsAssistant" content="打开智能助手" placement="bottom">
            <button class="assistant-trigger" type="button" @click="openAIOpsAssistant">
              <el-icon :size="18"><Service /></el-icon>
            </button>
          </el-tooltip>

          <el-popover placement="bottom-end" :width="360" trigger="click" popper-class="header-notice-popover">
            <template #reference>
              <button class="notice-trigger" type="button" @click="handleNoticeOpen">
                <el-badge :value="notificationCount" :max="99" :hidden="!notificationCount">
                  <el-icon :size="18"><Bell /></el-icon>
                </el-badge>
              </button>
            </template>

            <div class="notice-panel">
              <div class="notice-panel__header">
                <div>
                  <div class="notice-panel__title">待关注事项</div>
                  <div class="notice-panel__subtitle">
                    {{ notificationCount ? `当前有 ${notificationCount} 条待关注动态` : '当前暂无待关注动态' }}
                  </div>
                </div>
                <el-button link type="primary" :loading="notificationsLoading" @click="loadNotifications">刷新</el-button>
              </div>

              <div v-if="notificationSections.length" class="notice-groups">
                <section
                  v-for="section in notificationSections"
                  :key="section.key"
                  class="notice-group"
                >
                  <div class="notice-group__header">
                    <div class="notice-group__meta">
                      <span class="notice-group__title">{{ section.title }}</span>
                      <span class="notice-group__count">{{ section.items.length }}</span>
                    </div>
                    <el-button
                      v-if="section.route"
                      link
                      type="primary"
                      class="notice-group__more"
                      @click="goSection(section)"
                    >
                      查看更多
                    </el-button>
                  </div>
                  <div class="notice-list">
                    <button
                      v-for="item in section.items"
                      :key="item.key"
                      type="button"
                      class="notice-item"
                      @click="goNotification(item)"
                    >
                      <div class="notice-item__dot" :class="`is-${item.dotTone}`"></div>
                      <div class="notice-item__body">
                        <div class="notice-item__top">
                          <div class="notice-item__title-wrap">
                            <span class="notice-item__title">{{ item.title }}</span>
                            <el-tag size="small" effect="light" :type="item.tagType">{{ item.tag }}</el-tag>
                          </div>
                          <span class="notice-item__time">{{ formatDateTime(item.time) }}</span>
                        </div>
                        <div class="notice-item__desc">{{ item.description }}</div>
                      </div>
                    </button>
                  </div>
                </section>
              </div>
              <div v-else class="notice-empty">
                <el-icon><Bell /></el-icon>
                <span>告警、事件与高风险动态会在这里实时汇总</span>
              </div>
            </div>
          </el-popover>

          <el-dropdown @command="handleUserCommand">
            <div class="user-trigger">
              <el-avatar :size="36" class="user-avatar">
                <span>{{ userInitials }}</span>
              </el-avatar>
              <div class="user-meta">
                <span class="user-name">{{ authStore.displayName || '未登录' }}</span>
                <span class="user-role">{{ primaryRoleLabel }}</span>
              </div>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="refresh">刷新权限</el-dropdown-item>
                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
      <AIOpsChatWidget v-if="!isAIOpsChatRoute" />
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useBusinessContextStore } from '@/stores/businessContext'
import AIOpsChatWidget from '@/components/aiops/AIOpsChatWidget.vue'
import { getModuleSettings } from '@/api/modules/rbac'
import { getDashboardStats, getDeployments, getTransactionTickets } from '@/api/modules/ops'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()
const businessContextStore = useBusinessContextStore()
const notificationsLoading = ref(false)
const notificationItems = ref([])
const notificationCount = ref(0)
const moduleVisibility = ref({})
const MODULE_SETTINGS_EVENT = 'xing-cloud-module-settings-updated'
const TASK_SCHEDULES_VISIBLE = false
const observabilityBoardPermissions = ['ops.monitor.dashboard.view']
const observabilityOverviewPermissions = [
  'ops.dashboard.view',
  'ops.monitor.dashboard.view',
  'ops.metric.query',
  'ops.metric.datasource.view',
  'ops.log.query',
  'ops.log.datasource.view',
  'ops.alert.view',
  'ops.alert.config.view',
]
const defaultOpenMenuKeys = ['aiops', 'observability']
let notificationTimer = null

const menuItems = [
  { moduleKey: 'dashboard', path: '/dashboard', title: '运行概览', icon: 'Odometer', permission: 'ops.dashboard.view' },
  {
    moduleKey: 'aiops',
    title: 'AIOps',
    icon: 'ChatDotSquare',
    children: [
      { path: '/aiops/chat', title: '智能助手', icon: 'Service', permission: 'aiops.chat.view' },
      { path: '/aiops/knowledge', title: '知识图谱', icon: 'Share', permission: 'aiops.knowledge.view' },
      { path: '/aiops/config', title: '智能体配置', icon: 'Tools', permission: 'aiops.config.view' },
      { path: '/aiops/audit', title: '智能体审计', icon: 'Tickets', permission: 'aiops.audit.view' },
    ],
  },
  {
    moduleKey: 'observability',
    title: '可观测性',
    icon: 'DataLine',
    children: [
      { path: '/observability/overview', title: '平台总览', icon: 'DataLine', anyPermissions: observabilityOverviewPermissions },
      { path: '/observability/alerts', title: '告警中心', icon: 'Bell', anyPermissions: ['ops.alert.view', 'ops.alert.config.view'] },
      { path: '/observability/rules', title: '告警规则', icon: 'Operation', permission: 'ops.alert.config.view' },
      { path: '/observability/dashboards', title: '监控看板', icon: 'Histogram', anyPermissions: observabilityBoardPermissions },
      { path: '/observability/metrics', title: '指标查询', icon: 'DataAnalysis', anyPermissions: ['ops.metric.query', 'ops.metric.datasource.view'] },
      { path: '/observability/logs', title: '日志查询', icon: 'Search', anyPermissions: ['ops.log.query', 'ops.log.datasource.view'] },
      { path: '/observability/data-sources', title: '数据源', icon: 'DataBoard', anyPermissions: ['ops.metric.datasource.view', 'ops.log.datasource.view'] },
    ],
  },
  {
    moduleKey: 'tasks',
    title: '任务中心',
    icon: 'Operation',
    children: [
      { path: '/tasks/workbench', title: '任务工作台', icon: 'Operation', anyPermissions: ['ops.task.execute', 'ops.host.execute'] },
      { path: '/tasks/schedules', title: '计划任务', icon: 'Timer', hidden: !TASK_SCHEDULES_VISIBLE, anyPermissions: ['ops.host.schedule.view', 'ops.host.schedule.manage', 'ops.host.schedule.execute'] },
    ],
  },
  {
    moduleKey: 'assets',
    title: '资产管理',
    icon: 'Files',
    children: [
      { path: '/assets/registration', title: '资产登记', icon: 'Monitor', anyPermissions: ['ops.task.resource.view', 'ops.task.resource.manage'] },
      { path: '/assets/middleware', title: '中间件资产', icon: 'Coin', anyPermissions: ['ops.middleware.view', 'ops.middleware.manage'] },
    ],
  },
  {
    moduleKey: 'workworkorders',
    title: '工单系统',
    icon: 'Tickets',
    children: [
      { path: '/workworkorders/releases', title: '应用发布', icon: 'Promotion', anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'] },
      { path: '/workworkorders/transactions', title: '事务工单', icon: 'Tickets', anyPermissions: ['ops.ticket.view', 'ops.ticket.manage', 'ops.ticket.approve'] },
      { path: '/workworkorders/approval-flows', title: '审批流', icon: 'Checked', anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'] },
    ],
  },
  {
    moduleKey: 'platform',
    title: '平台管理',
    icon: 'Box',
    children: [
      { path: '/platform/k8s', title: 'K8S 集群', icon: 'Connection', permission: 'ops.k8s.view' },
    ],
  },
  {
    moduleKey: 'system',
    title: '系统管理',
    icon: 'User',
    children: [
      { path: '/users', title: '用户管理', icon: 'User', anyPermissions: ['rbac.user.view', 'rbac.role.view', 'rbac.group.view', 'rbac.permission.view'] },
      { path: '/users/audit', title: '操作审计', icon: 'DocumentChecked', permission: 'rbac.audit.view' },
      { path: '/users/modules', title: '模块管理', icon: 'Menu', permission: 'rbac.module.manage' },
    ],
  },
]

function canAccess(item) {
  if (item.permission) return authStore.hasPermission(item.permission)
  if (item.anyPermissions) return authStore.hasAnyPermission(item.anyPermissions)
  return true
}

function isModuleVisible(item) {
  const visibilityKey = item.visibilityKey || item.moduleKey
  if (!visibilityKey) return true
  return moduleVisibility.value[visibilityKey] !== false
}

function visibleChildren(items = []) {
  return items
    .filter(child => !child.hidden)
    .map((child) => {
      if (!child.children) return child
      const children = visibleChildren(child.children)
      return { ...child, children }
    })
    .filter((child) => child.children ? child.children.length > 0 : canAccess(child))
}

const visibleMenuItems = computed(() => menuItems
  .filter(isModuleVisible)
  .map((item) => {
    if (!item.children) return item
    const children = visibleChildren(item.children)
    return { ...item, children }
  })
  .filter((item) => item.children ? item.children.length > 0 : !item.hidden && canAccess(item))
)

const normalizedMenuPath = computed(() => {
  if (route.path.startsWith('/sql')) {
    return '/sql'
  }
  return route.path
})

const activeMenuPath = computed(() => {
  return normalizedMenuPath.value
})

const currentTitle = computed(() => {
  const currentPath = normalizedMenuPath.value
  for (const item of visibleMenuItems.value) {
    if ((item.menuKey || item.path) === currentPath) return item.title
    if (item.children) {
      const child = item.children.find((entry) => (entry.menuKey || entry.path) === currentPath)
      if (child) return item.title === child.title ? child.title : `${item.title} / ${child.title}`
    }
  }
  return route.meta.title || ''
})

const currentRoleLabel = computed(() => {
  const roles = authStore.currentUser?.roles || []
  if (!roles.length) return '无角色'
  return roles.map(role => role.name).join(' / ')
})

const primaryRoleLabel = computed(() => {
  const roles = authStore.currentUser?.roles || []
  if (!roles.length) return '访客'
  if (roles.length === 1) return roles[0].name
  return `${roles[0].name} +${roles.length - 1}`
})

const userInitials = computed(() => {
  const source = authStore.displayName || authStore.currentUser?.username || 'S'
  return source.slice(0, 1).toUpperCase()
})

const isAIOpsChatRoute = computed(() => route.name === 'AIOpsChat' || route.path === '/aiops/chat')
const canOpenAIOpsAssistant = computed(() => authStore.hasPermission('aiops.chat.view') && !isAIOpsChatRoute.value)

const notificationSections = computed(() => {
  const sectionOrder = ['approval', 'alert']
  const sectionTitleMap = {
    approval: '待审批清单',
    alert: '告警提醒',
  }
  const sectionRouteMap = {
    approval: '/workworkorders/releases',
    alert: '/observability/alerts',
  }
  return sectionOrder
    .map((key) => ({
      key,
      title: sectionTitleMap[key],
      route: sectionRouteMap[key],
      items: notificationItems.value.filter(item => item.section === key),
    }))
    .filter(section => section.items.length)
})

function formatDateTime(value) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function buildAlertNotificationItem(item) {
  const levelMap = {
    critical: { tag: '严重告警', tagType: 'danger' },
    warning: { tag: '告警提醒', tagType: 'warning' },
    info: { tag: '信息提醒', tagType: 'info' },
  }
  const meta = levelMap[item.level] || { tag: '系统通知', tagType: 'info' }
  return {
    key: `alert-${item.id}`,
    section: 'alert',
    title: item.title || '告警中心通知',
    description: item.message || item.source || '请进入告警中心查看详情',
    time: item.created_at,
    route: '/observability/alerts',
    tag: meta.tag,
    tagType: meta.tagType,
    dotTone: item.level === 'critical' ? 'danger' : item.level === 'warning' ? 'warning' : 'info',
    priority: item.level === 'critical' ? 3 : item.level === 'warning' ? 2 : 1,
  }
}

function buildDeploymentApprovalItem(item) {
  const nodeName = item.current_approval_step?.node_name || '默认审批'
  const scopeText = formatScopeText(item)
  return {
    key: `deploy-approval-${item.id}`,
    section: 'approval',
    title: `${item.app_name} / ${item.version}`,
    description: `${scopeText} · 发布审批待处理 · ${nodeName}`,
    time: item.deployed_at,
    route: '/workworkorders/releases',
    tag: '发布审批',
    tagType: 'warning',
    dotTone: 'warning',
    priority: 4,
  }
}

function buildTransactionApprovalItem(item) {
  const scopeText = formatScopeText(item)
  return {
    key: `transaction-approval-${item.id}`,
    section: 'approval',
    title: item.title || '事务工单待审批',
    description: `${scopeText} · 事务工单待处理 · ${item.type_display || '运维事务'}`,
    time: item.updated_at || item.created_at,
    route: '/workworkorders/transactions',
    tag: '事务审批',
    tagType: 'warning',
    dotTone: 'warning',
    priority: 4,
  }
}

function buildEventNotificationItem(item) {
  const resultToneMap = {
    failed: { tag: '高风险事件', tagType: 'danger', priority: 3 },
    partial: { tag: '待关注事件', tagType: 'warning', priority: 2 },
    pending: { tag: '待处理事件', tagType: 'warning', priority: 2 },
  }
  const meta = resultToneMap[item.result] || { tag: '平台动态', tagType: 'info', priority: 1 }
  return {
    key: `event-${item.id}`,
    tagType: meta.tagType,
    dotTone: item.result === 'failed' ? 'danger' : item.result === 'partial' || item.result === 'pending' ? 'warning' : 'info',
    priority: meta.priority,
  }
}

function formatScopeText(item) {
  const parts = []
  if (item?.system_name || item?.business_line) parts.push(item.system_name || item.business_line)
  if (item?.environment_display) {
    parts.push(item.environment_display)
  } else if (item?.environment) {
    parts.push(item.environment)
  }
  return parts.join(' / ') || '未指定系统 / 环境'
}

async function loadNotifications() {
  notificationsLoading.value = true
  try {
    const tasks = []
    if (authStore.hasPermission('ops.deployment.approve')) {
      tasks.push(getDeployments({ approval_status: 'pending' }))
    } else {
      tasks.push(Promise.resolve(null))
    }

    if (authStore.hasPermission('ops.ticket.approve')) {
      tasks.push(getTransactionTickets({ status: 'pending' }))
    } else {
      tasks.push(Promise.resolve(null))
    }

    if (authStore.hasPermission('ops.dashboard.view')) {
      tasks.push(getDashboardStats())
    } else {
      tasks.push(Promise.resolve(null))
    }



    const [deploymentsResult, transactionTicketsResult, dashboardStatsResult, eventOverviewResult] = await Promise.allSettled(tasks)
    const deploymentsResponse = deploymentsResult.status === 'fulfilled' ? deploymentsResult.value : null
    const transactionTicketsResponse = transactionTicketsResult.status === 'fulfilled' ? transactionTicketsResult.value : null
    const dashboardStats = dashboardStatsResult.status === 'fulfilled' ? dashboardStatsResult.value : null
    const eventOverview = eventOverviewResult.status === 'fulfilled' ? eventOverviewResult.value : null

    const items = []
    let total = 0

    if (deploymentsResponse) {
      const deploymentItems = Array.isArray(deploymentsResponse.results) ? deploymentsResponse.results : (deploymentsResponse || [])
      const pendingDeploymentApprovals = deploymentItems.filter(canHandleDeploymentApproval)
      items.push(...pendingDeploymentApprovals.slice(0, 3).map(buildDeploymentApprovalItem))
      total += pendingDeploymentApprovals.length
    }

    if (transactionTicketsResponse) {
      const ticketItems = Array.isArray(transactionTicketsResponse.results) ? transactionTicketsResponse.results : (transactionTicketsResponse || [])
      items.push(...ticketItems.slice(0, 3).map(buildTransactionApprovalItem))
      total += ticketItems.length
    }

    if (dashboardStats) {
      const recentAlerts = Array.isArray(dashboardStats.recent_alerts) ? dashboardStats.recent_alerts : []
      items.push(...recentAlerts.slice(0, 4).map(buildAlertNotificationItem))
      total += Number(dashboardStats.alerts?.unacknowledged || 0)
    }

    if (eventOverview) {
      const priorityEvents = Array.isArray(eventOverview.suspects) ? eventOverview.suspects : []
      items.push(...priorityEvents.slice(0, 4).map(buildEventNotificationItem))
      total += priorityEvents.length
    }

    notificationItems.value = items
      .sort((left, right) => {
        if (right.priority !== left.priority) return right.priority - left.priority
        return new Date(right.time || 0).getTime() - new Date(left.time || 0).getTime()
      })
      .slice(0, 6)
    notificationCount.value = total
  } catch {
    notificationItems.value = []
    notificationCount.value = 0
  } finally {
    notificationsLoading.value = false
  }
}

function handleNoticeOpen() {
  if (!notificationItems.value.length && !notificationsLoading.value) {
    void loadNotifications()
  }
}

async function loadModuleSettings() {
  if (!authStore.isAuthenticated) return
  try {
    const settings = await getModuleSettings({ skipErrorMessage: true })
    moduleVisibility.value = (settings || []).reduce((result, item) => ({
      ...result,
      [item.code]: item.required ? true : item.enabled !== false,
    }), {})
  } catch {
    moduleVisibility.value = {}
  }
}

function openAIOpsAssistant() {
  window.dispatchEvent(new Event('xing-cloud-aiops-open'))
}

function openAIAgentPromo() {
  router.push('/ai-agent-promo')
}

function canHandleDeploymentApproval(item) {
  const step = item?.current_approval_step
  if (!step?.approver_type || !step?.approver_value) return authStore.hasPermission('ops.deployment.approve')
  if (step.approver_type === 'user') return authStore.currentUser?.username === step.approver_value
  if (step.approver_type === 'role') {
    return (authStore.currentUser?.roles || []).some(role => role.code === step.approver_value)
  }
  if (step.approver_type === 'group') {
    return (authStore.currentUser?.user_groups || []).some(group => group.code === step.approver_value)
  }
  return false
}

function goNotification(item) {
  if (!item?.route) return
  router.push(item.route)
}

function goSection(section) {
  if (!section?.route) return
  router.push(section.route)
}

async function handleUserCommand(command) {
  if (command === 'refresh') {
    await authStore.reloadProfile()
    ElMessage.success('权限已刷新')
    return
  }
  if (command === 'logout') {
    await authStore.logout()
    router.replace('/login')
  }
}

onMounted(() => {
  window.addEventListener(MODULE_SETTINGS_EVENT, loadModuleSettings)
  void loadModuleSettings()
  void loadNotifications()
  void businessContextStore.loadContexts()
  notificationTimer = window.setInterval(() => {
    void loadNotifications()
  }, 60000)
})

onBeforeUnmount(() => {
  window.removeEventListener(MODULE_SETTINGS_EVENT, loadModuleSettings)
  if (notificationTimer) {
    window.clearInterval(notificationTimer)
    notificationTimer = null
  }
})
</script>

<style scoped>
.business-context-switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  margin-left: 10px;
  padding-left: 14px;
  border-left: 1px solid #e2e8f0;
}

.business-context-switch__label,
.business-context-switch__code {
  color: #64748b;
  font-size: 12px;
  white-space: nowrap;
}

.business-context-switch__select {
  width: 190px;
}

.business-context-switch__code {
  float: right;
  margin-left: 16px;
}

.business-context-switch__configure {
  flex: 0 0 auto;
  padding: 0;
}

.brand-mark {
  width: 29px;
  height: 29px;
  display: block;
}

@media (max-width: 1100px) {
  .business-context-switch__label {
    display: none;
  }

  .business-context-switch__select {
    width: 150px;
  }
}

@media (max-width: 820px) {
  .business-context-switch {
    margin-left: 4px;
    padding-left: 8px;
  }

  .business-context-switch__select {
    width: 132px;
  }
}

.assistant-trigger,
.promo-trigger,
.notice-trigger {
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.78);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.promo-trigger {
  width: auto;
  min-width: 102px;
  padding: 0 12px;
  gap: 6px;
  color: var(--nebula-blue);
  border-color: rgba(91, 192, 235, 0.24);
  background: linear-gradient(135deg, rgba(91, 192, 235, 0.1) 0%, rgba(46, 134, 222, 0.08) 100%);
  box-shadow: 0 4px 12px rgba(15, 52, 96, 0.08);
  font-size: 13px;
  font-weight: 700;
}

.promo-trigger:hover {
  color: var(--nebula-dark);
  border-color: rgba(91, 192, 235, 0.36);
  background: linear-gradient(135deg, rgba(91, 192, 235, 0.16) 0%, rgba(46, 134, 222, 0.12) 100%);
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(15, 52, 96, 0.12);
}

.assistant-trigger {
  position: relative;
  overflow: hidden;
  color: var(--nebula-blue);
  border-color: rgba(91, 192, 235, 0.24);
  background: linear-gradient(135deg, rgba(91, 192, 235, 0.1) 0%, rgba(248, 250, 252, 0.86) 100%);
  box-shadow: 0 4px 12px rgba(15, 52, 96, 0.08);
}

.assistant-trigger::after {
  content: '';
  position: absolute;
  inset: 6px;
  border-radius: 9px;
  border: 1px solid rgba(91, 192, 235, 0.14);
  pointer-events: none;
}

.assistant-trigger:hover {
  color: var(--nebula-dark);
  border-color: rgba(91, 192, 235, 0.34);
  background: linear-gradient(135deg, rgba(91, 192, 235, 0.16) 0%, rgba(46, 134, 222, 0.1) 100%);
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(15, 52, 96, 0.12);
}

.notice-trigger:hover {
  color: var(--nebula-blue);
  border-color: rgba(91, 192, 235, 0.26);
  background: rgba(91, 192, 235, 0.1);
}

.notice-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.notice-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.notice-panel__title {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.notice-panel__subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}

.notice-groups {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-height: 420px;
  overflow-y: auto;
  padding-right: 4px;
}

.notice-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.notice-group__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.notice-group__meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.notice-group__title {
  font-size: 12px;
  font-weight: 700;
  color: #475569;
}

.notice-group__count {
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.72);
  color: #64748b;
  font-size: 11px;
  line-height: 20px;
  text-align: center;
}

.notice-group__more {
  padding: 0;
  font-size: 12px;
}

.notice-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.notice-item {
  width: 100%;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 10px 10px 8px;
  border: 1px solid rgba(226, 232, 240, 0.72);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.92);
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
}

.notice-item:hover {
  border-color: rgba(148, 163, 184, 0.26);
  background: rgba(248, 250, 252, 0.96);
}

.notice-item__dot {
  width: 8px;
  height: 8px;
  margin-top: 6px;
  flex-shrink: 0;
  border-radius: 999px;
  background: #94a3b8;
}

.notice-item__dot.is-danger {
  background: #ef4444;
  box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.08);
}

.notice-item__dot.is-warning {
  background: #f59e0b;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.08);
}

.notice-item__dot.is-info {
  background: #60a5fa;
  box-shadow: 0 0 0 4px rgba(96, 165, 250, 0.08);
}

.notice-item__body {
  min-width: 0;
  flex: 1;
}

.notice-item__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.notice-item__title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.notice-item__title {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}

.notice-item__time {
  flex-shrink: 0;
  font-size: 11px;
  color: #94a3b8;
}

.notice-item__desc {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.55;
  color: #64748b;
}

.notice-empty {
  min-height: 120px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #94a3b8;
  font-size: 12px;
}

.user-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 2px 4px 2px 2px;
  border-radius: 14px;
  cursor: pointer;
  transition: background 0.2s ease;
}

.user-trigger:hover {
  background: rgba(255, 255, 255, 0.56);
}

.user-avatar {
  background: linear-gradient(135deg, var(--nebula-light) 0%, var(--nebula-blue) 100%);
  color: #ffffff;
  box-shadow: 0 8px 18px rgba(46, 134, 222, 0.18);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.user-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.user-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.user-role {
  font-size: 11px;
  color: var(--text-secondary);
}

</style>
