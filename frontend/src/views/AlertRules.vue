<template>
  <div class="alert-source-page">
    <header class="page-header">
      <div>
        <span class="eyebrow">可观测性 / 告警配置</span>
        <h1>告警源工作台</h1>
        <p>统一管理 Prometheus、Alertmanager 与 Zabbix 告警源、负责人和分级通知。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openSource()">新增告警源</el-button>
      </div>
    </header>

    <el-tabs v-model="workspaceTab" class="workspace-tabs">
      <el-tab-pane label="告警源" name="sources">
        <div class="source-workbench">
          <aside class="source-list panel">
            <div class="list-toolbar">
              <el-input v-model="sourceSearch" clearable :prefix-icon="Search" placeholder="搜索告警源" />
              <el-select v-model="providerFilter" clearable placeholder="全部类型">
                <el-option label="Prometheus" value="prometheus" />
                <el-option label="Alertmanager" value="alertmanager" />
                <el-option label="Zabbix" value="zabbix" />
              </el-select>
            </div>
            <div v-loading="loading" class="source-items">
              <button
                v-for="source in filteredSources"
                :key="source.id"
                type="button"
                class="source-item"
                :class="{ active: selectedSourceId === source.id }"
                @click="selectedSourceId = source.id"
              >
                <span class="source-icon" :class="source.provider">{{ providerMark(source.provider) }}</span>
                <span class="source-main">
                  <strong>{{ source.name }}</strong>
                  <small>{{ source.provider_display }} · {{ source.code }}</small>
                </span>
                <span class="source-state" :class="source.health_status" />
              </button>
              <el-empty v-if="!loading && !filteredSources.length" :image-size="72" description="暂无告警源" />
            </div>
          </aside>

          <main v-if="selectedSource" class="source-detail panel">
            <div class="detail-head">
              <div>
                <div class="title-line">
                  <h2>{{ selectedSource.name }}</h2>
                  <el-tag :type="selectedSource.is_enabled ? 'success' : 'info'">{{ selectedSource.is_enabled ? '已启用' : '已停用' }}</el-tag>
                  <el-tag effect="plain">{{ selectedSource.provider_display }}</el-tag>
                </div>
                <p>{{ selectedSource.description || selectedSource.code }}</p>
              </div>
              <div class="detail-actions">
                <el-popconfirm
                  v-if="selectedSource.provider !== 'prometheus'"
                  title="轮换后旧 Token 将立即失效，确认继续？"
                  width="280"
                  @confirm="rotateToken"
                >
                  <template #reference><el-button :icon="RefreshRight" :loading="rotatingToken">轮换 Token</el-button></template>
                </el-popconfirm>
                <el-button :icon="Edit" @click="openSource(selectedSource)">编辑</el-button>
                <el-popconfirm title="删除该告警源及其规则和策略？" @confirm="removeSource(selectedSource)">
                  <template #reference><el-button type="danger" plain :icon="Delete">删除</el-button></template>
                </el-popconfirm>
              </div>
            </div>

            <el-tabs v-model="sourceTab" class="detail-tabs">
              <el-tab-pane label="概览" name="overview">
                <div class="metric-strip">
                  <div><span>活跃告警</span><strong>{{ selectedSource.active_alert_count }}</strong></div>
                  <div><span>规则实例</span><strong>{{ selectedSource.rule_count }}</strong></div>
                  <div><span>通知策略</span><strong>{{ selectedSource.policy_count }}</strong></div>
                  <div><span>最近接收</span><strong class="time-value">{{ formatTime(selectedSource.last_received_at) }}</strong></div>
                </div>
                <el-descriptions :column="2" border class="overview-grid">
                  <el-descriptions-item label="主负责人">{{ primaryOwner?.recipient_detail?.name || '未配置' }}</el-descriptions-item>
                  <el-descriptions-item label="协同负责人">{{ collaboratorNames || '-' }}</el-descriptions-item>
                  <el-descriptions-item v-if="selectedSource.provider === 'prometheus'" label="指标数据源">{{ selectedSource.metric_datasource_detail?.name || '-' }}</el-descriptions-item>
                  <el-descriptions-item v-else label="Webhook 地址"><div class="copy-line"><code>{{ selectedSource.endpoint }}</code><el-button link :icon="CopyDocument" @click="copyText(selectedSource.endpoint)" /></div></el-descriptions-item>
                  <el-descriptions-item label="通知">{{ selectedSource.notify_enabled ? '启用' : '停用' }}</el-descriptions-item>
                  <el-descriptions-item label="智能研判">{{ selectedSource.analyze_enabled ? '启用' : '停用' }}</el-descriptions-item>
                  <el-descriptions-item v-if="selectedSource.provider !== 'prometheus'" label="Token">{{ selectedSource.token_configured ? `已配置（${selectedSource.token_hint}）` : '未配置' }}</el-descriptions-item>
                  <el-descriptions-item v-if="selectedSource.provider !== 'prometheus'" label="接入统计">成功 {{ selectedSource.accepted_requests }} / 拒绝 {{ selectedSource.rejected_requests }}</el-descriptions-item>
                </el-descriptions>
              </el-tab-pane>

              <el-tab-pane label="负责人" name="owners">
                <div class="section-head"><h3>告警源负责人</h3><el-button type="primary" :icon="Edit" @click="openSource(selectedSource)">配置负责人</el-button></div>
                <el-table :data="selectedSource.owner_bindings || []" stripe>
                  <el-table-column label="姓名" min-width="160"><template #default="{ row }"><strong>{{ row.recipient_detail?.name }}</strong></template></el-table-column>
                  <el-table-column label="角色" width="120"><template #default="{ row }"><el-tag :type="row.role === 'primary' ? 'danger' : 'info'">{{ row.role === 'primary' ? '主负责人' : '协同负责人' }}</el-tag></template></el-table-column>
                  <el-table-column label="负责级别" min-width="220"><template #default="{ row }"><el-tag v-for="level in row.levels" :key="level" class="level-tag" :type="levelType(level)">{{ levelText(level) }}</el-tag></template></el-table-column>
                  <el-table-column label="个人渠道" min-width="220"><template #default="{ row }">{{ (row.recipient_detail?.preferred_channels || []).map(channelTypeText).join('、') || '按联系方式自动选择' }}</template></el-table-column>
                </el-table>
              </el-tab-pane>

              <el-tab-pane :label="selectedSource.provider === 'prometheus' ? '告警规则' : '字段映射'" name="rules">
                <template v-if="selectedSource.provider === 'prometheus'">
                  <div class="section-head"><h3>规则实例</h3><el-button type="primary" :icon="Plus" @click="openInstantiate">从模板创建</el-button></div>
                  <el-table :data="sourceRules" stripe v-loading="detailLoading">
                    <el-table-column label="规则" min-width="220"><template #default="{ row }"><div class="primary-cell"><strong>{{ row.name }}</strong><small>{{ row.code }}</small></div></template></el-table-column>
                    <el-table-column label="模板" min-width="180"><template #default="{ row }">{{ row.template_detail?.name || '自定义' }}</template></el-table-column>
                    <el-table-column label="级别" width="90"><template #default="{ row }"><el-tag :type="levelType(row.level)">{{ levelText(row.level) }}</el-tag></template></el-table-column>
                    <el-table-column label="运行质量" min-width="130"><template #default="{ row }">{{ qualityText(row.runtime_quality?.health) }}</template></el-table-column>
                    <el-table-column label="启用" width="80"><template #default="{ row }"><el-switch :model-value="row.is_enabled" @change="toggleRule(row, $event)" /></template></el-table-column>
                    <el-table-column label="操作" width="110"><template #default="{ row }"><el-button link type="primary" :loading="testingRuleId === row.id" @click="testRule(row)">试运行</el-button></template></el-table-column>
                  </el-table>
                </template>
                <template v-else>
                  <div class="section-head"><h3>标准化与指纹</h3><el-button type="primary" :loading="savingMapping" @click="saveMapping">保存</el-button></div>
                  <el-form label-position="top" class="mapping-form">
                    <el-form-item label="字段映射 JSON"><el-input v-model="mappingText" type="textarea" :rows="10" placeholder='{"resource":"labels.instance"}' /></el-form-item>
                    <el-form-item label="告警指纹字段"><el-select v-model="fingerprintFields" multiple filterable allow-create default-first-option><el-option v-for="item in fingerprintOptions" :key="item" :label="item" :value="item" /></el-select></el-form-item>
                  </el-form>
                </template>
              </el-tab-pane>

              <el-tab-pane label="通知策略" name="policies">
                <div class="section-head"><h3>分级通知路由</h3><el-button type="primary" :icon="Plus" @click="openPolicy()">新增策略</el-button></div>
                <el-table :data="sourcePolicies" stripe v-loading="detailLoading">
                  <el-table-column label="策略" min-width="180"><template #default="{ row }"><div class="primary-cell"><strong>{{ row.name }}</strong><small>优先级 {{ row.priority }}</small></div></template></el-table-column>
                  <el-table-column label="立即通知" min-width="240"><template #default="{ row }">{{ routeSummary(row, 'immediate') }}</template></el-table-column>
                  <el-table-column label="未认领升级" min-width="240"><template #default="{ row }">{{ routeSummary(row, 'unacknowledged') }}</template></el-table-column>
                  <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag></template></el-table-column>
                  <el-table-column label="操作" width="140"><template #default="{ row }"><el-button link @click="openPolicy(row)">编辑</el-button><el-popconfirm title="删除该策略？" @confirm="removePolicy(row)"><template #reference><el-button link type="danger">删除</el-button></template></el-popconfirm></template></el-table-column>
                </el-table>
              </el-tab-pane>

              <el-tab-pane label="测试" name="test">
                <div v-if="selectedSource.provider === 'prometheus'" class="test-pane">
                  <el-result icon="info" title="Prometheus 规则试运行" sub-title="在告警规则标签中选择一条规则执行只读查询。" />
                </div>
                <div v-else class="test-pane">
                  <el-input v-model="payloadText" type="textarea" :rows="14" placeholder="粘贴 Alertmanager 或 Zabbix JSON" />
                  <el-button type="primary" :loading="previewing" @click="previewPayload">解析预览</el-button>
                  <pre v-if="previewResult">{{ JSON.stringify(previewResult, null, 2) }}</pre>
                </div>
              </el-tab-pane>

              <el-tab-pane v-if="selectedSource.provider !== 'prometheus'" label="接入日志" name="ingress-logs">
                <div class="section-head">
                  <div><h3>Webhook 接入记录</h3><p class="section-note">用于确认请求是否到达平台、鉴权结果和本次接收的告警数量。</p></div>
                  <el-button :icon="Refresh" :loading="ingressLogsLoading" @click="loadIngressLogs">刷新</el-button>
                </div>
                <el-table :data="ingressLogs" stripe v-loading="ingressLogsLoading">
                  <el-table-column label="时间" width="180"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
                  <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="ingressStatusType(row.status)">{{ row.status_display }}</el-tag></template></el-table-column>
                  <el-table-column prop="remote_addr" label="来源地址" min-width="140" />
                  <el-table-column prop="http_status" label="HTTP" width="80" />
                  <el-table-column prop="alert_count" label="告警数" width="90" />
                  <el-table-column label="耗时" width="100"><template #default="{ row }">{{ row.duration_ms }} ms</template></el-table-column>
                  <el-table-column prop="message" label="处理结果" min-width="260" show-overflow-tooltip />
                </el-table>
                <el-empty v-if="!ingressLogsLoading && !ingressLogs.length" :image-size="72" description="暂无接入记录" />
              </el-tab-pane>
            </el-tabs>
          </main>
          <main v-else class="source-detail panel empty-detail"><el-empty description="选择或新增一个告警源" /></main>
        </div>
      </el-tab-pane>

      <el-tab-pane label="全局模板" name="templates">
        <section class="panel standalone-panel">
          <div class="section-head"><h2>全局规则模板</h2><el-button type="primary" :icon="Plus" @click="openTemplate()">新建模板</el-button></div>
          <el-table :data="templates" stripe v-loading="loading">
            <el-table-column label="模板" min-width="240"><template #default="{ row }"><div class="primary-cell"><strong>{{ row.name }}</strong><small>{{ row.code }} · v{{ row.template_version }}</small></div></template></el-table-column>
            <el-table-column prop="category_display" label="分类" width="110" />
            <el-table-column label="级别" width="90"><template #default="{ row }"><el-tag :type="levelType(row.level)">{{ levelText(row.level) }}</el-tag></template></el-table-column>
            <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="templateStatusType(row.template_status)">{{ templateStatusText(row.template_status) }}</el-tag></template></el-table-column>
            <el-table-column label="操作" width="230"><template #default="{ row }"><el-button v-if="row.template_status === 'draft'" link @click="openTemplate(row)">编辑</el-button><el-button v-if="row.template_status === 'draft'" link type="warning" @click="submitTemplate(row)">提交审核</el-button><el-button v-if="['draft','review'].includes(row.template_status)" link type="success" @click="publishTemplate(row)">发布</el-button><el-button v-if="row.template_status === 'published'" link type="danger" @click="archiveTemplate(row)">归档</el-button></template></el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="通知资源" name="resources">
        <section class="resource-grid">
          <div class="panel resource-panel"><div class="section-head"><h2>通知渠道</h2></div><el-table :data="channels" stripe><el-table-column prop="name" label="名称" /><el-table-column label="类型"><template #default="{ row }">{{ channelTypeText(row.channel_type) }}</template></el-table-column><el-table-column label="状态"><template #default="{ row }">{{ row.is_enabled ? '启用' : '停用' }}</template></el-table-column></el-table></div>
          <div class="panel resource-panel"><div class="section-head"><h2>接收人</h2></div><el-table :data="recipients" stripe><el-table-column prop="name" label="姓名" /><el-table-column prop="phone" label="电话" /><el-table-column label="渠道"><template #default="{ row }">{{ (row.contact_channels || []).map(channelTypeText).join('、') || '-' }}</template></el-table-column></el-table></div>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="sourceDialog.visible" :title="sourceDialog.form.id ? '编辑告警源' : '新增告警源'" width="680px" destroy-on-close>
      <el-form label-position="top">
        <div class="form-grid"><el-form-item label="名称"><el-input v-model="sourceDialog.form.name" /></el-form-item><el-form-item label="类型"><el-select v-model="sourceDialog.form.provider" :disabled="Boolean(sourceDialog.form.id)"><el-option label="Prometheus" value="prometheus" /><el-option label="Alertmanager" value="alertmanager" /><el-option label="Zabbix" value="zabbix" /></el-select></el-form-item></div>
        <el-form-item v-if="sourceDialog.form.provider === 'prometheus'" label="Prometheus 指标数据源"><el-select v-model="sourceDialog.form.metric_datasource" filterable><el-option v-for="item in metricSources" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <div class="form-grid"><el-form-item label="主负责人"><el-select v-model="sourceDialog.form.primary_owner" filterable><el-option v-for="item in recipients" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item><el-form-item label="协同负责人"><el-select v-model="sourceDialog.form.collaborators" multiple filterable><el-option v-for="item in recipients" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item></div>
        <el-form-item label="负责人级别"><el-checkbox-group v-model="sourceDialog.form.owner_levels"><el-checkbox value="info">信息</el-checkbox><el-checkbox value="warning">警告</el-checkbox><el-checkbox value="critical">严重</el-checkbox></el-checkbox-group></el-form-item>
        <div class="switch-row"><el-switch v-model="sourceDialog.form.is_enabled" active-text="启用告警源" /><el-switch v-model="sourceDialog.form.notify_enabled" active-text="发送通知" /><el-switch v-model="sourceDialog.form.analyze_enabled" active-text="智能研判" /></div>
        <el-form-item label="说明"><el-input v-model="sourceDialog.form.description" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="sourceDialog.visible=false">取消</el-button><el-button type="primary" :loading="sourceDialog.saving" @click="saveSource">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="tokenDialog.visible" title="Webhook Token" width="620px"><el-alert type="warning" :closable="false" title="Token 仅显示一次" /><div class="token-box"><code>{{ tokenDialog.token }}</code><el-button :icon="CopyDocument" @click="copyText(tokenDialog.token)" /></div><template #footer><el-button type="primary" @click="tokenDialog.visible=false">已保存</el-button></template></el-dialog>

    <el-dialog v-model="instantiateDialog.visible" title="从全局模板创建规则" width="560px"><el-form label-position="top"><el-form-item label="告警源"><el-input :model-value="selectedSource?.name" disabled /></el-form-item><el-form-item label="已发布模板"><el-select v-model="instantiateDialog.templateId" filterable><el-option v-for="item in publishedTemplates" :key="item.id" :label="`${item.name} · ${item.category_display}`" :value="item.id" /></el-select></el-form-item></el-form><template #footer><el-button @click="instantiateDialog.visible=false">取消</el-button><el-button type="primary" :loading="instantiateDialog.saving" @click="instantiateRule">创建</el-button></template></el-dialog>

    <el-dialog v-model="policyDialog.visible" :title="policyDialog.form.id ? '编辑通知策略' : '新增通知策略'" width="900px" destroy-on-close>
      <el-form label-position="top"><div class="form-grid"><el-form-item label="策略名称"><el-input v-model="policyDialog.form.name" /></el-form-item><el-form-item label="优先级"><el-input-number v-model="policyDialog.form.priority" :min="1" :max="9999" /></el-form-item></div><div class="switch-row"><el-switch v-model="policyDialog.form.notify_on_fire" active-text="触发通知" /><el-switch v-model="policyDialog.form.notify_on_resolved" active-text="恢复通知" /><el-switch v-model="policyDialog.form.notify_on_analysis" active-text="研判通知" /><el-switch v-model="policyDialog.form.is_enabled" active-text="启用策略" /></div></el-form>
      <div class="section-head"><h3>通知路由</h3><el-button :icon="Plus" @click="addRoute">添加路由</el-button></div>
      <el-table :data="policyDialog.form.routes" border>
        <el-table-column label="级别" width="120"><template #default="{ row }"><el-select v-model="row.level"><el-option label="信息" value="info" /><el-option label="警告" value="warning" /><el-option label="严重" value="critical" /></el-select></template></el-table-column>
        <el-table-column label="触发" width="140"><template #default="{ row }"><el-select v-model="row.trigger"><el-option label="立即" value="immediate" /><el-option label="未认领" value="unacknowledged" /></el-select></template></el-table-column>
        <el-table-column label="等待(分钟)" width="120"><template #default="{ row }"><el-input-number v-model="row.after_minutes" :min="row.trigger === 'unacknowledged' ? 1 : 0" :disabled="row.trigger === 'immediate'" controls-position="right" /></template></el-table-column>
        <el-table-column label="渠道" min-width="170"><template #default="{ row }"><el-select v-model="row.channel"><el-option v-for="item in channels" :key="item.id" :label="`${item.name} · ${channelTypeText(item.channel_type)}`" :value="item.id" /></el-select></template></el-table-column>
        <el-table-column label="接收对象" min-width="160"><template #default="{ row }"><el-select v-model="row.target_type"><el-option label="固定渠道" value="fixed" /><el-option label="告警源负责人" value="source_owners" /><el-option label="接收组" value="recipient_group" /><el-option label="资源负责人" value="resource_contacts" /></el-select></template></el-table-column>
        <el-table-column label="接收组" min-width="150"><template #default="{ row }"><el-select v-model="row.recipient_group" clearable :disabled="row.target_type !== 'recipient_group'"><el-option v-for="item in recipientGroups" :key="item.id" :label="item.name" :value="item.id" /></el-select></template></el-table-column>
        <el-table-column width="56"><template #default="{ $index }"><el-button link type="danger" :icon="Delete" @click="policyDialog.form.routes.splice($index,1)" /></template></el-table-column>
      </el-table>
      <template #footer><el-button @click="policyDialog.visible=false">取消</el-button><el-button type="primary" :loading="policyDialog.saving" @click="savePolicy">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="templateDialog.visible" :title="templateDialog.form.id ? '编辑模板' : '新建全局模板'" width="720px"><el-form label-position="top"><div class="form-grid"><el-form-item label="模板名称"><el-input v-model="templateDialog.form.name" /></el-form-item><el-form-item label="编码"><el-input v-model="templateDialog.form.code" :disabled="Boolean(templateDialog.form.id)" /></el-form-item><el-form-item label="分类"><el-select v-model="templateDialog.form.category"><el-option label="Kubernetes" value="k8s" /><el-option label="服务器" value="server" /><el-option label="数据库" value="database" /><el-option label="中间件" value="middleware" /></el-select></el-form-item><el-form-item label="默认级别"><el-select v-model="templateDialog.form.level"><el-option label="警告" value="warning" /><el-option label="严重" value="critical" /><el-option label="信息" value="info" /></el-select></el-form-item></div><el-form-item label="PromQL"><el-input v-model="templateDialog.form.promql" type="textarea" :rows="5" /></el-form-item><div class="form-grid"><el-form-item label="操作符"><el-select v-model="templateDialog.form.operator"><el-option v-for="item in ['>','>=','<','<=','==','!=']" :key="item" :label="item" :value="item" /></el-select></el-form-item><el-form-item label="阈值"><el-input-number v-model="templateDialog.form.threshold" /></el-form-item></div><el-form-item label="摘要模板"><el-input v-model="templateDialog.form.summary" /></el-form-item><el-form-item label="详细描述"><el-input v-model="templateDialog.form.message" type="textarea" :rows="3" /></el-form-item></el-form><template #footer><el-button @click="templateDialog.visible=false">取消</el-button><el-button type="primary" :loading="templateDialog.saving" @click="saveTemplate">保存草稿</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { CopyDocument, Delete, Edit, Plus, Refresh, RefreshRight, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  archiveAlertRuleTemplate, createAlertNotificationPolicy, createAlertRuleTemplate,
  createAlertSource, deleteAlertNotificationPolicy, deleteAlertSource, evaluateAlertRule,
  getAlertNotificationChannels, getAlertNotificationPolicies, getAlertRecipientGroups,
  getAlertRecipients, getAlertRules, getAlertRuleTemplates, getAlertSourceLogs, getAlertSources,
  getMetricDataSources, instantiateAlertRule, patchAlertRule, previewAlertSourcePayload,
  publishAlertRuleTemplate, rotateAlertSourceToken, submitAlertRuleTemplate, updateAlertNotificationPolicy,
  updateAlertRuleTemplate, updateAlertSource,
} from '@/api/modules/ops'

const listOf = (value) => value?.results || value?.data?.results || value?.data || value || []
const loading = ref(false)
const detailLoading = ref(false)
const workspaceTab = ref('sources')
const sourceTab = ref('overview')
const sourceSearch = ref('')
const providerFilter = ref('')
const sources = ref([])
const templates = ref([])
const rules = ref([])
const policies = ref([])
const channels = ref([])
const recipients = ref([])
const recipientGroups = ref([])
const metricSources = ref([])
const selectedSourceId = ref(null)
const mappingText = ref('{}')
const fingerprintFields = ref([])
const savingMapping = ref(false)
const payloadText = ref('')
const previewResult = ref(null)
const previewing = ref(false)
const testingRuleId = ref(null)
const rotatingToken = ref(false)
const ingressLogsLoading = ref(false)
const ingressLogs = ref([])

const selectedSource = computed(() => sources.value.find((item) => item.id === selectedSourceId.value) || null)
const filteredSources = computed(() => sources.value.filter((item) => (!providerFilter.value || item.provider === providerFilter.value) && `${item.name} ${item.code}`.toLowerCase().includes(sourceSearch.value.toLowerCase())))
const sourceRules = computed(() => rules.value.filter((item) => item.alert_source === selectedSourceId.value))
const sourcePolicies = computed(() => policies.value.filter((item) => item.alert_source === selectedSourceId.value))
const publishedTemplates = computed(() => templates.value.filter((item) => item.template_status === 'published'))
const primaryOwner = computed(() => selectedSource.value?.owner_bindings?.find((item) => item.role === 'primary' && item.is_enabled))
const collaboratorNames = computed(() => (selectedSource.value?.owner_bindings || []).filter((item) => item.role === 'collaborator' && item.is_enabled).map((item) => item.recipient_detail?.name).filter(Boolean).join('、'))
const fingerprintOptions = ['alertname', 'cluster', 'namespace', 'pod', 'container', 'uid', 'instance', 'trigger_id', 'zabbix_host', 'service']

const emptySourceForm = () => ({ id: null, name: '', provider: 'prometheus', metric_datasource: null, primary_owner: null, collaborators: [], owner_levels: ['warning', 'critical'], is_enabled: true, notify_enabled: true, analyze_enabled: true, description: '' })
const sourceDialog = reactive({ visible: false, saving: false, form: emptySourceForm() })
const tokenDialog = reactive({ visible: false, token: '' })
const instantiateDialog = reactive({ visible: false, saving: false, templateId: null })
const emptyPolicyForm = () => ({ id: null, name: '', priority: 100, routes: [], notify_on_fire: true, notify_on_resolved: true, notify_on_analysis: true, is_enabled: true })
const policyDialog = reactive({ visible: false, saving: false, form: emptyPolicyForm() })
const emptyTemplateForm = () => ({ id: null, name: '', code: '', category: 'k8s', level: 'warning', promql: '', operator: '>', threshold: 0, summary: '', message: '' })
const templateDialog = reactive({ visible: false, saving: false, form: emptyTemplateForm() })

async function loadAll() {
  loading.value = true
  try {
    const [sourceData, templateData, channelData, recipientData, groupData, metricData] = await Promise.all([
      getAlertSources({ page_size: 500 }), getAlertRuleTemplates({ page_size: 500 }),
      getAlertNotificationChannels({ page_size: 500 }), getAlertRecipients({ page_size: 500 }),
      getAlertRecipientGroups({ page_size: 500 }), getMetricDataSources({ page_size: 500 }),
    ])
    sources.value = listOf(sourceData)
    templates.value = listOf(templateData)
    channels.value = listOf(channelData)
    recipients.value = listOf(recipientData)
    recipientGroups.value = listOf(groupData)
    metricSources.value = listOf(metricData)
    if (!selectedSourceId.value && sources.value.length) selectedSourceId.value = sources.value[0].id
    await loadSourceData()
  } catch (error) { ElMessage.error(error.response?.data?.detail || error.message || '加载告警配置失败') }
  finally { loading.value = false }
}

async function loadSourceData() {
  if (!selectedSourceId.value) { rules.value = []; policies.value = []; return }
  detailLoading.value = true
  try {
    const [ruleData, policyData] = await Promise.all([
      getAlertRules({ alert_source_id: selectedSourceId.value, page_size: 500 }),
      getAlertNotificationPolicies({ alert_source: selectedSourceId.value, page_size: 500 }),
    ])
    rules.value = listOf(ruleData)
    policies.value = listOf(policyData)
  } finally { detailLoading.value = false }
}

watch(selectedSourceId, async () => {
  sourceTab.value = 'overview'
  ingressLogs.value = []
  const source = selectedSource.value
  mappingText.value = JSON.stringify(source?.field_mapping || {}, null, 2)
  fingerprintFields.value = [...(source?.fingerprint_fields || [])]
  await loadSourceData()
})

watch(sourceTab, async (value) => {
  if (value === 'ingress-logs') await loadIngressLogs()
})

function openSource(row = null) {
  const form = emptySourceForm()
  if (row) {
    Object.assign(form, row, {
      primary_owner: row.owner_bindings?.find((item) => item.role === 'primary')?.recipient || null,
      collaborators: (row.owner_bindings || []).filter((item) => item.role === 'collaborator').map((item) => item.recipient),
      owner_levels: row.owner_bindings?.find((item) => item.role === 'primary')?.levels || ['warning', 'critical'],
    })
  }
  sourceDialog.form = form
  sourceDialog.visible = true
}

async function saveSource() {
  const form = sourceDialog.form
  if (!form.name.trim() || !form.primary_owner) return ElMessage.warning('请填写名称并选择主负责人')
  sourceDialog.saving = true
  try {
    const ownerBindings = [
      { recipient: form.primary_owner, role: 'primary', levels: form.owner_levels, is_enabled: true },
      ...form.collaborators.filter((id) => id !== form.primary_owner).map((id) => ({ recipient: id, role: 'collaborator', levels: form.owner_levels, is_enabled: true })),
    ]
    const payload = { name: form.name.trim(), provider: form.provider, metric_datasource: form.provider === 'prometheus' ? form.metric_datasource : null, owner_bindings: ownerBindings, is_enabled: form.is_enabled, notify_enabled: form.notify_enabled, analyze_enabled: form.analyze_enabled, description: form.description || '' }
    const result = form.id ? await updateAlertSource(form.id, payload) : await createAlertSource(payload)
    sourceDialog.visible = false
    if (result.token) { tokenDialog.token = result.token; tokenDialog.visible = true }
    selectedSourceId.value = result.id
    await loadAll()
    ElMessage.success('告警源已保存')
  } catch (error) { ElMessage.error(error.response?.data?.detail || firstError(error.response?.data) || '保存失败') }
  finally { sourceDialog.saving = false }
}

async function removeSource(row) { await deleteAlertSource(row.id); if (selectedSourceId.value === row.id) selectedSourceId.value = null; await loadAll(); ElMessage.success('告警源已删除') }
async function rotateToken() {
  if (!selectedSource.value || selectedSource.value.provider === 'prometheus') return
  rotatingToken.value = true
  try {
    const result = await rotateAlertSourceToken(selectedSource.value.id)
    tokenDialog.token = result.token
    tokenDialog.visible = true
    await loadAll()
    ElMessage.success('Token 已轮换')
  } catch (error) { ElMessage.error(firstError(error.response?.data) || error.message || 'Token 轮换失败') }
  finally { rotatingToken.value = false }
}
async function loadIngressLogs() {
  if (!selectedSource.value || selectedSource.value.provider === 'prometheus') { ingressLogs.value = []; return }
  ingressLogsLoading.value = true
  try {
    const result = await getAlertSourceLogs(selectedSource.value.id, { page_size: 100 })
    ingressLogs.value = listOf(result)
  } catch (error) { ingressLogs.value = []; ElMessage.error(firstError(error.response?.data) || error.message || '接入日志加载失败') }
  finally { ingressLogsLoading.value = false }
}
async function saveMapping() { try { savingMapping.value = true; const field_mapping = JSON.parse(mappingText.value || '{}'); await updateAlertSource(selectedSourceId.value, { field_mapping, fingerprint_fields: fingerprintFields.value }); await loadAll(); ElMessage.success('映射已保存') } catch (error) { ElMessage.error(error instanceof SyntaxError ? '字段映射不是有效 JSON' : (error.response?.data?.detail || '保存失败')) } finally { savingMapping.value = false } }
function openInstantiate() { instantiateDialog.templateId = null; instantiateDialog.visible = true }
async function instantiateRule() { if (!instantiateDialog.templateId) return ElMessage.warning('请选择模板'); instantiateDialog.saving = true; try { await instantiateAlertRule({ template_id: instantiateDialog.templateId, alert_source_id: selectedSourceId.value }); instantiateDialog.visible = false; await loadAll(); ElMessage.success('规则实例已创建') } finally { instantiateDialog.saving = false } }
async function toggleRule(row, value) { await patchAlertRule(row.id, { is_enabled: value }); await loadSourceData() }
async function testRule(row) { testingRuleId.value = row.id; try { const result = await evaluateAlertRule(row.id, { dry_run: true }); ElMessage.success(`查询完成，匹配 ${result.would_fire_count || 0} 项`) } catch (error) { ElMessage.error(error.response?.data?.error || error.message || '试运行失败') } finally { testingRuleId.value = null } }

function openPolicy(row = null) { policyDialog.form = row ? { ...row, routes: (row.routes || []).map((item) => ({ ...item })) } : emptyPolicyForm(); policyDialog.visible = true }
function addRoute() { policyDialog.form.routes.push({ level: 'warning', trigger: 'immediate', after_minutes: 0, escalate_to_level: '', channel: null, target_type: 'fixed', recipient_group: null, sort_order: (policyDialog.form.routes.length + 1) * 10, is_enabled: true }) }
async function savePolicy() { const form = policyDialog.form; if (!form.name.trim() || !form.routes.length) return ElMessage.warning('请填写策略名称并至少添加一条路由'); policyDialog.saving = true; try { const payload = { name: form.name.trim(), alert_source: selectedSourceId.value, priority: form.priority, matchers: form.matchers || [], min_level: form.min_level || '', continue_matching: false, routes: form.routes.map((route, index) => ({ level: route.level, trigger: route.trigger, after_minutes: route.trigger === 'unacknowledged' ? route.after_minutes : 0, escalate_to_level: route.trigger === 'unacknowledged' ? (route.escalate_to_level || 'critical') : '', channel: route.channel, target_type: route.target_type, recipient_group: route.target_type === 'recipient_group' ? route.recipient_group : null, sort_order: index * 10 + 10, is_enabled: true })), group_by: form.group_by || ['alert_source_code','cluster','namespace','resource'], group_wait_seconds: form.group_wait_seconds ?? 10, group_interval_seconds: form.group_interval_seconds ?? 60, repeat_interval_minutes: form.repeat_interval_minutes ?? 720, storm_threshold: form.storm_threshold ?? 3, mute_schedule: form.mute_schedule || {}, inhibition_matchers: form.inhibition_matchers || [], notify_on_fire: form.notify_on_fire, notify_on_resolved: form.notify_on_resolved, notify_on_analysis: form.notify_on_analysis, is_enabled: form.is_enabled, description: form.description || '' }; form.id ? await updateAlertNotificationPolicy(form.id, payload) : await createAlertNotificationPolicy(payload); policyDialog.visible = false; await loadAll(); ElMessage.success('通知策略已保存') } catch (error) { ElMessage.error(firstError(error.response?.data) || error.message || '保存失败') } finally { policyDialog.saving = false } }
async function removePolicy(row) { await deleteAlertNotificationPolicy(row.id); await loadAll(); ElMessage.success('策略已删除') }

function openTemplate(row = null) { const form = emptyTemplateForm(); if (row) Object.assign(form, { id: row.id, name: row.name, code: row.code, category: row.category, level: row.level, promql: row.query_config?.promql || '', operator: row.condition?.operator || '>', threshold: row.condition?.threshold || 0, summary: row.annotations?.summary || '', message: row.annotations?.message || '' }); templateDialog.form = form; templateDialog.visible = true }
async function saveTemplate() { const form = templateDialog.form; if (!form.name || !form.code || !form.promql) return ElMessage.warning('请填写模板名称、编码和 PromQL'); templateDialog.saving = true; try { const payload = { name: form.name, code: form.code, category: form.category, source: form.code, source_type: 'prometheus', level: form.level, query_config: { promql: form.promql }, condition: { operator: form.operator, threshold: form.threshold }, labels: {}, annotations: { summary: form.summary, message: form.message }, interval_seconds: 60, duration_seconds: 120, notify_enabled: true, auto_analyze: true, description: form.message || '' }; form.id ? await updateAlertRuleTemplate(form.id, payload) : await createAlertRuleTemplate(payload); templateDialog.visible = false; await loadAll(); ElMessage.success('模板草稿已保存') } catch (error) { ElMessage.error(firstError(error.response?.data) || '保存失败') } finally { templateDialog.saving = false } }
async function submitTemplate(row) { await submitAlertRuleTemplate(row.id); await loadAll() }
async function publishTemplate(row) { await publishAlertRuleTemplate(row.id); await loadAll(); ElMessage.success('模板已发布') }
async function archiveTemplate(row) { await archiveAlertRuleTemplate(row.id); await loadAll(); ElMessage.success('模板已归档') }
async function previewPayload() { try { previewing.value = true; previewResult.value = await previewAlertSourcePayload(selectedSourceId.value, JSON.parse(payloadText.value)); ElMessage.success('载荷解析成功') } catch (error) { ElMessage.error(error instanceof SyntaxError ? '请输入有效 JSON' : (error.response?.data?.detail || '解析失败')) } finally { previewing.value = false } }
async function copyText(value) { await navigator.clipboard.writeText(value || ''); ElMessage.success('已复制') }

function firstError(data) { if (!data || typeof data !== 'object') return ''; const value = Object.values(data)[0]; return Array.isArray(value) ? value[0] : String(value || '') }
function providerMark(value) { return ({ prometheus: 'P', alertmanager: 'A', zabbix: 'Z' })[value] || '?' }
function levelText(value) { return ({ info: '信息', warning: '警告', critical: '严重' })[value] || value }
function levelType(value) { return ({ info: 'info', warning: 'warning', critical: 'danger' })[value] || 'info' }
function channelTypeText(value) { return ({ feishu: '飞书', wecom: '企微', dingtalk: '钉钉', email: '邮件', sms: '短信', voice: '语音' })[value] || value }
function qualityText(value) { return ({ healthy: '正常', error: '错误', no_data: '无数据', flapping: '抖动' })[value] || '未运行' }
function templateStatusText(value) { return ({ draft: '草稿', review: '待审核', published: '已发布', archived: '已归档' })[value] || value }
function templateStatusType(value) { return ({ draft: 'info', review: 'warning', published: 'success', archived: 'info' })[value] || 'info' }
function ingressStatusType(value) { return ({ accepted: 'success', rejected: 'warning', error: 'danger' })[value] || 'info' }
function formatTime(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-' }
function routeSummary(row, trigger) { const items = (row.routes || []).filter((item) => item.trigger === trigger); return items.length ? items.map((item) => `${levelText(item.level)} → ${item.channel_detail?.name}${trigger === 'unacknowledged' ? `（${item.after_minutes} 分钟）` : ''}`).join('；') : '-' }

onMounted(loadAll)
</script>

<style scoped>
.alert-source-page { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.eyebrow { color: #64748b; font-size: 12px; }
h1 { margin: 4px 0 6px; font-size: 26px; letter-spacing: 0; }
h2, h3, p { margin: 0; letter-spacing: 0; }
.page-header p, .detail-head p { color: #64748b; font-size: 14px; }
.header-actions, .detail-actions, .switch-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.workspace-tabs :deep(.el-tabs__header) { margin-bottom: 14px; }
.panel { border: 1px solid #dbe3ec; background: #fff; border-radius: 6px; }
.source-workbench { display: grid; grid-template-columns: minmax(260px, 320px) minmax(0, 1fr); gap: 14px; min-height: 650px; }
.source-list { padding: 12px; }
.list-toolbar { display: grid; gap: 8px; margin-bottom: 12px; }
.source-items { display: flex; flex-direction: column; gap: 5px; min-height: 300px; }
.source-item { display: grid; grid-template-columns: 34px minmax(0, 1fr) 8px; gap: 10px; align-items: center; width: 100%; min-height: 58px; padding: 8px 10px; border: 1px solid transparent; border-radius: 5px; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.source-item:hover { background: #f6f8fb; }
.source-item.active { border-color: #93c5fd; background: #eff6ff; }
.source-icon { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 5px; background: #334155; color: #fff; font-weight: 700; }
.source-icon.prometheus { background: #dc2626; }.source-icon.alertmanager { background: #2563eb; }.source-icon.zabbix { background: #15803d; }
.source-main { min-width: 0; display: flex; flex-direction: column; gap: 3px; }.source-main strong, .source-main small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.source-main small { color: #64748b; }
.source-state { width: 8px; height: 8px; border-radius: 50%; background: #94a3b8; }.source-state.healthy { background: #16a34a; }.source-state.error { background: #dc2626; }.source-state.pending { background: #d97706; }
.source-detail { min-width: 0; padding: 16px; }.empty-detail { display: grid; place-items: center; }
.detail-head, .section-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }.detail-head { padding-bottom: 14px; border-bottom: 1px solid #e5e7eb; }.title-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }.title-line h2 { font-size: 20px; }
.detail-tabs { margin-top: 8px; }.metric-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid #e2e8f0; margin: 12px 0 18px; }.metric-strip > div { min-height: 84px; padding: 14px; border-right: 1px solid #e2e8f0; display: flex; flex-direction: column; gap: 8px; }.metric-strip > div:last-child { border-right: 0; }.metric-strip span { color: #64748b; font-size: 13px; }.metric-strip strong { font-size: 24px; }.metric-strip .time-value { font-size: 14px; }
.overview-grid { max-width: 980px; }.copy-line, .token-box { display: flex; align-items: center; gap: 8px; min-width: 0; }.copy-line code { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.section-head { margin: 10px 0 12px; }.section-head h2 { font-size: 18px; }.section-head h3 { font-size: 15px; }.section-note { margin-top: 4px; color: #64748b; font-size: 13px; }.primary-cell { display: flex; flex-direction: column; gap: 3px; }.primary-cell small { color: #64748b; }.level-tag { margin-right: 5px; }
.mapping-form { max-width: 820px; }.test-pane { display: flex; flex-direction: column; gap: 12px; max-width: 900px; }.test-pane pre { max-height: 360px; overflow: auto; padding: 12px; border: 1px solid #e2e8f0; background: #f8fafc; }
.standalone-panel, .resource-panel { padding: 16px; }.resource-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }.switch-row { margin: 4px 0 18px; }.token-box { margin-top: 14px; padding: 12px; background: #f8fafc; border: 1px solid #dbe3ec; }.token-box code { flex: 1; overflow-wrap: anywhere; }
@media (max-width: 900px) { .page-header, .detail-head { flex-direction: column; }.source-workbench { grid-template-columns: 1fr; }.source-list { max-height: 300px; overflow: auto; }.metric-strip, .resource-grid, .form-grid { grid-template-columns: 1fr; }.metric-strip > div { border-right: 0; border-bottom: 1px solid #e2e8f0; }.metric-strip > div:last-child { border-bottom: 0; }.source-detail { overflow-x: auto; } }
</style>
