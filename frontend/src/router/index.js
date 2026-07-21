import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppLayout from '@/layout/AppLayout.vue'
import { pinia } from '@/stores'
import { useAuthStore } from '@/stores/auth'

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

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/403',
    name: 'Forbidden',
    component: () => import('@/views/Forbidden.vue'),
    meta: { public: true, title: '无权访问' },
  },
  {
    path: '/ai-agent-promo',
    name: 'AIAgentPromo',
    component: () => import('@/views/AIAgentPromo.vue'),
    meta: { public: true, title: 'AI Agent 产品介绍' },
  },
  {
    path: '/',
    component: AppLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '运行概览', icon: 'Odometer', permission: 'ops.dashboard.view' },
      },
      {
        path: 'hosts',
        redirect: '/assets/registration',
        meta: { hidden: true },
      },
      {
        path: 'hosts/assets',
        redirect: '/assets/registration',
        meta: { hidden: true, title: '资产登记', icon: 'Monitor', anyPermissions: ['ops.task.resource.view', 'ops.task.resource.manage', 'ops.host.view', 'ops.host.manage', 'ops.host.terminal'] },
      },
      {
        path: 'hosts/schedules',
        redirect: TASK_SCHEDULES_VISIBLE ? '/tasks/schedules' : '/tasks/workbench',
        meta: { hidden: true, title: '定时任务', icon: 'Timer', anyPermissions: ['ops.host.schedule.view', 'ops.host.schedule.manage', 'ops.host.schedule.execute'] },
      },
      {
        path: 'hosts/tasks',
        redirect: '/tasks/workbench',
        meta: { hidden: true, title: '任务中心', icon: 'Operation', permission: 'ops.task.execute' },
      },
      {
        path: 'tasks',
        name: 'TaskCenter',
        component: () => import('@/views/TaskCenter.vue'),
        meta: {
          title: '任务中心',
          icon: 'Operation',
          anyPermissions: [
            'ops.task.execute',
            'ops.task.resource.view',
            'ops.task.resource.manage',
            'ops.host.execute',
            'ops.host.view',
            'ops.host.manage',
            'ops.host.terminal',
          ],
        },
      },
      {
        path: 'tasks/resources',
        redirect: '/assets/registration',
        meta: { hidden: true, anyPermissions: ['ops.task.resource.view', 'ops.task.resource.manage'] },
      },
      {
        path: 'assets',
        redirect: () => {
          const authStore = useAuthStore(pinia)
          if (authStore.hasAnyPermission(['ops.task.resource.view', 'ops.task.resource.manage'])) return '/assets/registration'
          if (authStore.hasAnyPermission(['ops.middleware.view', 'ops.middleware.manage'])) return '/assets/middleware'
          return '/403'
        },
        meta: { hidden: true, anyPermissions: ['ops.task.resource.view', 'ops.task.resource.manage', 'ops.middleware.view', 'ops.middleware.manage'] },
      },
      {
        path: 'assets/registration',
        name: 'AssetRegistration',
        component: () => import('@/views/TaskResources.vue'),
        meta: {
          title: '资产登记',
          icon: 'Monitor',
          anyPermissions: ['ops.task.resource.view', 'ops.task.resource.manage'],
        },
      },
      {
        path: 'assets/middleware',
        name: 'MiddlewareAssets',
        component: () => import('@/views/MiddlewareAssets.vue'),
        meta: {
          title: '中间件资产',
          icon: 'Coin',
          anyPermissions: ['ops.middleware.view', 'ops.middleware.manage'],
        },
      },
      {
        path: 'tasks/workbench',
        name: 'TaskWorkbench',
        component: () => import('@/views/TaskWorkbench.vue'),
        meta: {
          title: '任务工作台',
          icon: 'Operation',
          anyPermissions: ['ops.task.execute', 'ops.host.execute'],
        },
      },
      {
        path: 'tasks/schedules',
        ...(TASK_SCHEDULES_VISIBLE
          ? { name: 'TaskSchedules', component: () => import('@/views/TaskSchedules.vue') }
          : { redirect: '/tasks/workbench' }),
        meta: {
          hidden: !TASK_SCHEDULES_VISIBLE,
          title: '计划任务',
          icon: 'Timer',
          anyPermissions: ['ops.host.schedule.view', 'ops.host.schedule.manage', 'ops.host.schedule.execute'],
        },
      },
      {
        path: 'deployments',
        redirect: '/workworkorders/releases',
        meta: { hidden: true, anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'] },
      },
      {
        path: 'workworkorders',
        redirect: () => {
          const authStore = useAuthStore(pinia)
          if (authStore.hasAnyPermission(['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'])) {
            return '/workworkorders/releases'
          }
          if (authStore.hasAnyPermission(['ops.ticket.view', 'ops.ticket.manage', 'ops.ticket.approve'])) {
            return '/workworkorders/transactions'
          }
          return '/403'
        },
        meta: { hidden: true },
      },
      {
        path: 'workworkorders/releases',
        name: 'WorkOrderReleases',
        component: () => import('@/views/Deployments.vue'),
        meta: {
          title: '应用发布',
          icon: 'Promotion',
          anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'],
        },
      },
      {
        path: 'workworkorders/approval-flows',
        name: 'WorkOrderApprovalFlows',
        component: () => import('@/views/Deployments.vue'),
        meta: {
          title: '审批流',
          icon: 'Checked',
          anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'],
        },
      },
      {
        path: 'workworkorders/transactions',
        name: 'TransactionTickets',
        component: () => import('@/views/TransactionTickets.vue'),
        meta: {
          title: '事务工单',
          icon: 'Tickets',
          anyPermissions: ['ops.ticket.view', 'ops.ticket.manage', 'ops.ticket.approve'],
        },
      },
      {
        path: 'containers/k8s',
        redirect: '/platform/k8s',
        meta: { hidden: true, permission: 'ops.k8s.view' },
      },
      {
        path: 'platform',
        redirect: () => {
          const authStore = useAuthStore(pinia)
          if (authStore.hasPermission('ops.k8s.view')) return '/platform/k8s'
          return '/403'
        },
        meta: { hidden: true },
      },
      {
        path: 'platform/k8s',
        name: 'PlatformK8sClusters',
        component: () => import('@/views/K8sManage.vue'),
        meta: { title: 'K8S 集群', icon: 'Connection', permission: 'ops.k8s.view' },
      },
      {
        path: 'observability/overview',
        name: 'ObservabilityOverview',
        component: () => import('@/views/ObservabilityOverview.vue'),
        meta: {
          title: '平台总览',
          icon: 'DataLine',
          anyPermissions: observabilityOverviewPermissions,
        },
      },
      {
        path: 'observability/alerts',
        name: 'ObservabilityAlerts',
        component: () => import('@/views/Alerts.vue'),
        meta: { title: '告警中心', icon: 'Bell', anyPermissions: ['ops.alert.view', 'ops.alert.config.view'] },
      },
      {
        path: 'observability/alerts/:id',
        name: 'ObservabilityAlertDetail',
        component: () => import('@/views/Alerts.vue'),
        meta: { hidden: true, title: '告警详情', permission: 'ops.alert.view' },
      },
      {
        path: 'alert-actions/:token',
        name: 'AlertActionConfirm',
        component: () => import('@/views/AlertActionConfirm.vue'),
        meta: { hidden: true, title: '确认告警操作', permission: 'ops.alert.view' },
      },
      {
        path: 'observability/rules',
        name: 'ObservabilityAlertRules',
        component: () => import('@/views/AlertRules.vue'),
        meta: { title: '告警规则', icon: 'Operation', permission: 'ops.alert.config.view' },
      },
      {
        path: 'observability/metrics',
        name: 'MetricsQuery',
        component: () => import('@/views/MetricsQuery.vue'),
        meta: { title: '指标查询', icon: 'DataAnalysis', anyPermissions: ['ops.metric.query', 'ops.metric.datasource.view'] },
      },
      {
        path: 'observability/logs',
        name: 'ObservabilityLogsQuery',
        component: () => import('@/views/LogsQuery.vue'),
        meta: { title: '日志查询', icon: 'Search', permission: 'ops.log.query' },
      },
      {
        path: 'observability/data-sources',
        name: 'ObservabilityDataSources',
        component: () => import('@/views/ObservabilityDataSources.vue'),
        meta: { title: '数据源', icon: 'DataBoard', anyPermissions: ['ops.metric.datasource.view', 'ops.log.datasource.view'] },
      },
      {
        path: 'observability/dashboards',
        name: 'NativeMonitoringDashboard',
        component: () => import('@/views/NativeMonitoringDashboard.vue'),
        meta: { title: '监控看板', icon: 'Histogram', permission: 'ops.monitor.dashboard.view' },
      },
      {
        path: 'users',
        name: 'Users',
        component: () => import('@/views/Users.vue'),
        meta: {
          title: '用户管理',
          icon: 'User',
          anyPermissions: ['rbac.user.view', 'rbac.role.view', 'rbac.group.view', 'rbac.permission.view', 'rbac.audit.view'],
        },
      },
      {
        path: 'users/audit',
        name: 'OperationAudit',
        component: () => import('@/views/OperationAudit.vue'),
        meta: { title: '操作审计', icon: 'DocumentChecked', permission: 'rbac.audit.view' },
      },
      {
        path: 'users/modules',
        name: 'ModuleManage',
        component: () => import('@/views/ModuleManage.vue'),
        meta: { title: '模块管理', icon: 'Menu', permission: 'rbac.module.manage' },
      },
      {
        path: 'aiops/chat',
        name: 'AIOpsChat',
        component: () => import('@/views/AIOpsChatEntry.vue'),
        meta: {
          title: '智能助手',
          icon: 'Service',
          permission: 'aiops.chat.view',
        },
      },
      {
        path: 'aiops/knowledge',
        name: 'AIOpsKnowledgeGraph',
        component: () => import('@/views/AIOpsKnowledgeGraph.vue'),
        meta: {
          title: '知识图谱',
          icon: 'Share',
          permission: 'aiops.knowledge.view',
        },
      },
      {
        path: 'aiops/knowledge/config',
        name: 'AIOpsKnowledgeConfig',
        redirect: (to) => ({ path: '/aiops/knowledge', query: { ...to.query, tab: 'config' } }),
        meta: { hidden: true },
      },
      {
        path: 'aiops/config',
        name: 'AIOpsConfig',
        component: () => import('@/views/AIOpsConfig.vue'),
        meta: {
          title: '智能体配置',
          icon: 'ChatDotSquare',
          permission: 'aiops.config.view',
        },
      },
      {
        path: 'aiops/audit',
        name: 'AIOpsAudit',
        component: () => import('@/views/AIOpsAudit.vue'),
        meta: {
          title: '智能体审计',
          icon: 'Tickets',
          permission: 'aiops.audit.view',
        },
      },
    ],
  },
  {
    path: '/webshell/:hostId',
    name: 'WebShell',
    component: () => import('@/views/WebShell.vue'),
    meta: { title: 'WebShell', permission: 'ops.host.terminal' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    }
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const authStore = useAuthStore(pinia)
  if (!authStore.initialized) {
    await authStore.bootstrap()
  }

  if (to.meta.public) {
    if (to.name === 'Login' && authStore.isAuthenticated) {
      return '/dashboard'
    }
    return true
  }

  if (!authStore.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }

  const allowed = to.meta.permission
    ? authStore.hasPermission(to.meta.permission)
    : authStore.hasAnyPermission(to.meta.anyPermissions || [])

  if (!allowed) {
    ElMessage.warning('你没有访问该页面的权限')
    return { name: 'Forbidden' }
  }

  return true
})

export default router
