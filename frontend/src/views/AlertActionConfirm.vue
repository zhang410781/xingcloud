<template>
  <div class="action-page">
    <section class="action-header">
      <div>
        <span class="eyebrow">告警协同</span>
        <h1>确认{{ actionLabel }}</h1>
        <p>该操作将在 Xing-Cloud 中记录操作者和通知来源。</p>
      </div>
      <el-tag v-if="detail.alert_level" :type="levelType(detail.alert_level)" effect="dark">
        {{ detail.alert_level.toUpperCase() }}
      </el-tag>
    </section>

    <section v-loading="loading" class="action-content">
      <el-result v-if="completed" icon="success" title="操作已完成" :sub-title="detail.message || '告警操作已处理'">
        <template #extra><el-button type="primary" @click="openAlert">查看告警详情</el-button></template>
      </el-result>

      <template v-else>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="告警">{{ detail.alert_title || '-' }}</el-descriptions-item>
          <el-descriptions-item label="操作">{{ actionLabel }}</el-descriptions-item>
          <el-descriptions-item label="通知渠道">{{ detail.provider || '-' }}</el-descriptions-item>
          <el-descriptions-item label="有效期">{{ formatTime(detail.expires_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.action === 'mute'" label="屏蔽范围">当前告警指纹，持续1小时</el-descriptions-item>
        </el-descriptions>
        <el-alert v-if="detail.action === 'mute'" title="屏蔽期间同一告警不会重复通知，其他告警不受影响。" type="warning" :closable="false" show-icon />
        <div class="action-buttons">
          <el-button @click="openAlert">取消并查看详情</el-button>
          <el-button type="primary" :loading="submitting" @click="confirmAction">确认{{ actionLabel }}</el-button>
        </div>
      </template>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { confirmAlertCardAction, getAlertCardAction } from '@/api/modules/ops'

const route = useRoute()
const router = useRouter()
const detail = reactive({})
const loading = ref(false)
const submitting = ref(false)
const completed = ref(false)
const token = computed(() => String(route.params.token || ''))
const actionLabel = computed(() => ({ claim: '认领告警', mute: '屏蔽告警' }[detail.action] || '告警操作'))

function levelType(level) {
  return level === 'critical' ? 'danger' : level === 'warning' ? 'warning' : 'info'
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
}

async function loadDetail() {
  loading.value = true
  try {
    Object.assign(detail, await getAlertCardAction(token.value))
  } catch (error) {
    ElMessage.error(error?.response?.data?.message || '操作链接无效或已过期')
  } finally {
    loading.value = false
  }
}

async function confirmAction() {
  submitting.value = true
  try {
    Object.assign(detail, await confirmAlertCardAction(token.value))
    completed.value = true
  } catch (error) {
    ElMessage.error(error?.response?.data?.message || '告警操作失败')
  } finally {
    submitting.value = false
  }
}

function openAlert() {
  router.push(detail.alert_id ? `/observability/alerts/${detail.alert_id}` : '/observability/alerts')
}

onMounted(loadDetail)
</script>

<style scoped>
.action-page { max-width: 880px; margin: 0 auto; padding: 24px; }
.action-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 8px 0 24px; border-bottom: 1px solid var(--el-border-color-light); }
.action-header h1 { margin: 4px 0 6px; font-size: 26px; letter-spacing: 0; }
.action-header p { margin: 0; color: var(--el-text-color-secondary); }
.eyebrow { color: var(--el-color-primary); font-size: 13px; font-weight: 700; }
.action-content { min-height: 320px; padding: 28px 0; }
.action-content .el-alert { margin-top: 18px; }
.action-buttons { display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px; }
@media (max-width: 640px) {
  .action-page { padding: 16px; }
  .action-header { gap: 12px; }
  .action-header h1 { font-size: 22px; }
  .action-buttons { flex-direction: column-reverse; }
  .action-buttons .el-button { width: 100%; margin-left: 0; }
}
</style>
