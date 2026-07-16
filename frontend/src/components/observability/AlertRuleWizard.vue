<template>
  <el-dialog v-model="visible" title="创建告警规则" width="900px" class="alert-rule-wizard" destroy-on-close>
    <el-steps :active="step" finish-status="success" simple>
      <el-step title="选择内置规则" />
      <el-step title="配置与试运行" />
    </el-steps>

    <div class="rule-wizard-body">
      <template v-if="step === 0">
        <div class="wizard-source-grid">
          <button
            v-for="bundle in templateBundles"
            :key="bundle.key"
            type="button"
            class="wizard-source"
            :class="{ active: form.template_bundle === bundle.key }"
            @click="selectBundle(bundle)"
          >
            <div class="wizard-source__title">
              <strong>{{ bundle.title }}</strong>
              <el-tag size="small" effect="plain">{{ bundle.templates.length }} 条规则</el-tag>
            </div>
            <span>{{ bundle.description }}</span>
            <small>{{ bundle.sourceTypes.join(' / ') }}</small>
          </button>
        </div>
        <RuleTemplateCatalog
          v-if="form.template_bundle"
          :templates="matchingTemplates"
          compact
          @import-rule="applyTemplate"
          @preview="applyTemplate"
        />
        <el-empty v-else description="请选择规则类型" :image-size="72" />
      </template>

      <template v-else>
        <el-form label-width="112px">
          <el-form-item label="规则名称"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="严重级别">
            <el-select v-model="form.level">
              <el-option label="严重" value="critical" />
              <el-option label="警告" value="warning" />
              <el-option label="信息" value="info" />
            </el-select>
          </el-form-item>
          <div class="wizard-two-col">
            <el-form-item label="持续时间"><el-input-number v-model="form.duration_seconds" :min="0" /> <span class="field-suffix">s</span></el-form-item>
            <el-form-item label="评估间隔"><el-input-number v-model="form.interval_seconds" :min="10" /> <span class="field-suffix">s</span></el-form-item>
          </div>
          <el-form-item label="查询配置"><el-input v-model="form.query_config_text" type="textarea" :rows="5" spellcheck="false" /></el-form-item>
          <el-form-item label="触发条件"><el-input v-model="form.condition_text" type="textarea" :rows="4" spellcheck="false" /></el-form-item>
          <el-checkbox v-model="form.notify_enabled">命中后通知</el-checkbox>
          <el-checkbox v-model="form.auto_analyze">命中后 AIOps 研判</el-checkbox>
          <el-checkbox v-model="form.is_enabled">保存后启用</el-checkbox>
          <el-input v-model="form.description" type="textarea" :rows="4" placeholder="规则说明" />
          <div class="wizard-run">
            <el-button type="primary" plain :loading="dryRunning" @click="dryRun">试运行</el-button>
            <pre v-if="dryRunResult">{{ dryRunResult }}</pre>
          </div>
        </el-form>
      </template>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button :disabled="step === 0" @click="step -= 1">上一步</el-button>
      <el-button v-if="step < 1" type="primary" :disabled="!canGoNext" @click="step += 1">下一步</el-button>
      <el-button v-else type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import RuleTemplateCatalog from './RuleTemplateCatalog.vue'
import { dryRunDraftAlertRule } from '@/api/modules/ops'

const visible = defineModel({ type: Boolean, default: false })
const props = defineProps({
  templates: { type: Array, default: () => [] },
})
const emit = defineEmits(['save'])

const BUNDLES = [
  {
    key: 'kubernetes',
    title: 'K8S',
    description: '节点、Pod、重启和 K8S Events 异常规则',
    codes: ['k8s-node-not-ready', 'k8s-abnormal-pods', 'k8s-pod-restarts', 'k8s-events-warning'],
  },
  {
    key: 'linux',
    title: 'Linux Server',
    description: '主机存活、CPU、内存和磁盘资源规则',
    codes: ['linux-node-down', 'linux-high-cpu', 'linux-high-memory', 'linux-high-disk'],
  },
]

const step = ref(0)
const dryRunning = ref(false)
const dryRunResult = ref('')
const form = reactive(emptyForm())

const templateBundles = computed(() => BUNDLES.map((bundle) => {
  const templates = props.templates.filter((item) => bundle.codes.includes(item.code))
  const sourceTypes = [...new Set(templates.map((item) => sourceTypeText(item.source_type)))]
  return { ...bundle, templates, sourceTypes: sourceTypes.length ? sourceTypes : ['未安装模板'] }
}))

const activeBundle = computed(() => templateBundles.value.find((item) => item.key === form.template_bundle))
const matchingTemplates = computed(() => activeBundle.value?.templates || [])
const canGoNext = computed(() => Boolean(form.template))

watch(visible, (value) => {
  if (!value) return
  Object.assign(form, emptyForm())
  dryRunResult.value = ''
  step.value = 0
})

function emptyForm() {
  return {
    template_bundle: '',
    template: null,
    category: 'server',
    name: '',
    source_type: 'prometheus',
    level: 'warning',
    query_config_text: '{}',
    condition_text: '{}',
    labels: {},
    annotations: {},
    interval_seconds: 60,
    duration_seconds: 0,
    notify_enabled: true,
    auto_analyze: true,
    is_enabled: true,
    description: '',
  }
}

function selectBundle(bundle) {
  form.template_bundle = bundle.key
  form.template = null
  form.name = ''
  form.labels = { integration: bundle.key }
}

function applyTemplate(template) {
  form.template = template.id
  form.name = template.name
  form.category = template.category || (form.template_bundle === 'kubernetes' ? 'k8s' : 'server')
  form.source_type = template.source_type
  form.level = template.level
  form.query_config_text = JSON.stringify(template.query_config || {}, null, 2)
  form.condition_text = JSON.stringify(template.condition || {}, null, 2)
  form.labels = { ...(template.labels || {}), integration: form.template_bundle || template.labels?.integration }
  form.annotations = template.annotations || {}
  form.interval_seconds = template.interval_seconds || 60
  form.duration_seconds = template.duration_seconds || 0
  form.notify_enabled = Boolean(template.notify_enabled)
  form.auto_analyze = Boolean(template.auto_analyze)
  form.description = template.description || ''
  step.value = 1
}

function payload() {
  return {
    source: 'custom',
    category: form.category || 'server',
    name: form.name,
    source_type: form.source_type,
    level: form.level,
    query_config: JSON.parse(form.query_config_text || '{}'),
    condition: JSON.parse(form.condition_text || '{}'),
    labels: { ...form.labels, integration: form.labels?.integration || form.template_bundle },
    annotations: form.annotations,
    interval_seconds: form.interval_seconds,
    duration_seconds: form.duration_seconds,
    notify_enabled: form.notify_enabled,
    auto_analyze: form.auto_analyze,
    is_enabled: form.is_enabled,
    description: form.description,
  }
}

async function dryRun() {
  dryRunning.value = true
  try {
    dryRunResult.value = JSON.stringify(await dryRunDraftAlertRule(payload()), null, 2)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '试运行失败')
  } finally {
    dryRunning.value = false
  }
}

function save() {
  try {
    emit('save', payload())
    visible.value = false
  } catch (error) {
    ElMessage.error(error.message || '规则配置格式不正确')
  }
}

function sourceTypeText(value) {
  return {
    prometheus: 'Prometheus',
    clickhouse: 'ClickHouse',
    k8s: 'K8S',
    sla: 'SLA',
  }[value] || value || '-'
}
</script>

<style scoped>
.rule-wizard-body {
  min-height: 420px;
  padding: 18px 0 0;
}

.wizard-source-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.wizard-source {
  min-height: 132px;
  display: grid;
  align-content: start;
  justify-items: stretch;
  gap: 10px;
  padding: 14px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  border-radius: 8px;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.wizard-source.active {
  border-color: #2563eb;
  box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.2);
}

.wizard-source__title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.wizard-source strong {
  color: #0f172a;
}

.wizard-source span,
.wizard-source small {
  color: #64748b;
  line-height: 1.5;
}

.wizard-source small {
  font-size: 12px;
}

.wizard-two-col {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.field-suffix {
  margin-left: 6px;
  color: #64748b;
}

.wizard-response,
.wizard-run {
  display: grid;
  gap: 14px;
}

.wizard-run pre {
  max-height: 320px;
  overflow: auto;
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 12px;
}
</style>
