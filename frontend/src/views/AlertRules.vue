<template>
  <div class="alert-rule-page">
    <header class="page-header">
      <div>
        <span class="eyebrow">可观测 / 告警配置</span>
        <h1>K8S 多数据源告警规则</h1>
        <p>每个 Prometheus 源拥有独立规则实例，通知渠道全局复用，策略按数据源和标签路由。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
        <el-button v-if="activeTab === 'rules'" type="primary" :icon="Plus" :disabled="!currentContext?.metric_datasource" @click="openInstantiate">从模板创建</el-button>
        <el-button v-if="activeTab === 'rules'" type="primary" plain :disabled="!currentContext?.metric_datasource" @click="openCustomRule">自定义规则</el-button>
        <el-button v-if="activeTab === 'policies'" type="primary" :icon="Plus" @click="openPolicy">新增通知策略</el-button>
      </div>
    </header>

    <ObservabilityRouteTabs group="observability" />

    <nav class="work-tabs">
      <button :class="{ active: activeTab === 'rules' }" @click="activeTab = 'rules'">告警规则</button>
      <button :class="{ active: activeTab === 'policies' }" @click="activeTab = 'policies'">通知策略</button>
      <button :class="{ active: activeTab === 'resources' }" @click="activeTab = 'resources'">通知资源</button>
    </nav>

    <template v-if="activeTab === 'rules'">
      <section class="toolbar panel">
        <div class="toolbar-field view-switch">
          <span>管理视图</span>
          <el-segmented v-model="viewMode" :options="viewModeOptions" @change="handleViewMode" />
        </div>
        <div class="toolbar-field source-field">
          <span>{{ viewMode === 'source' ? '当前 K8S 源' : '指标数据源' }}</span>
          <el-select v-model="selectedSourceId" disabled placeholder="当前上下文未绑定指标数据源">
            <el-option v-for="item in metricSources" :key="item.id" :label="sourceLabel(item)" :value="item.id" />
          </el-select>
        </div>
        <div class="toolbar-field">
          <span>规则分类</span>
          <el-select v-model="ruleCategory" clearable placeholder="全部分类">
            <el-option label="Kubernetes" value="k8s" />
            <el-option label="服务器" value="server" />
            <el-option label="数据库" value="database" />
            <el-option label="存储" value="storage" />
          </el-select>
        </div>
        <div v-if="!ruleCategory || ruleCategory === 'k8s'" class="toolbar-field">
          <span>K8S 子类</span>
          <el-select v-model="ruleGroup" clearable placeholder="全部子类">
            <el-option v-for="item in templateGroupOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </div>
        <div class="toolbar-field search-field">
          <span>搜索</span>
          <el-input v-model="ruleSearch" clearable :prefix-icon="Search" placeholder="规则名称 / 编码 / 模板" />
        </div>
      </section>

      <section class="summary-grid">
        <div class="summary-card"><span>规则实例</span><strong>{{ filteredRules.length }}</strong></div>
        <div class="summary-card success"><span>已启用</span><strong>{{ enabledRuleCount }}</strong></div>
        <div class="summary-card warning"><span>待绑定</span><strong>{{ bindingRuleCount }}</strong></div>
        <div class="summary-card"><span>内置模板</span><strong>{{ templates.length }}</strong></div>
      </section>

      <section class="panel table-panel">
        <el-table class="rule-instance-table" :data="filteredRules" stripe v-loading="loading" :empty-text="ruleEmptyText">
          <el-table-column label="规则" min-width="180">
            <template #default="{ row }">
              <div class="primary-cell">
                <strong>{{ row.name }}</strong>
                <small>{{ row.code }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="数据源 / 集群" min-width="160">
            <template #default="{ row }">
              <div v-if="row.metric_datasource_detail" class="source-cell">
                <strong>{{ row.metric_datasource_detail.cluster_name || row.metric_datasource_detail.name }}</strong>
                <small>{{ row.metric_datasource_detail.environment || row.metric_datasource_detail.name }}</small>
              </div>
              <el-tag v-else type="warning" effect="plain">待绑定</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="模板" min-width="160">
            <template #default="{ row }">
              <div class="primary-cell">
                <strong>{{ row.template_detail?.name || row.source || '自定义' }}</strong>
                <small>{{ row.template_detail?.rule_group_label || '基础监控' }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="级别" width="90">
            <template #default="{ row }"><el-tag :type="levelType(row.level)">{{ levelText(row.level) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-switch :model-value="row.is_enabled" :disabled="row.needs_binding" @change="toggleRule(row, $event)" />
            </template>
          </el-table-column>
          <el-table-column label="最近评估" width="150">
            <template #default="{ row }">{{ formatTime(row.last_evaluated_at) }}</template>
          </el-table-column>
          <el-table-column label="运行质量" min-width="180">
            <template #default="{ row }">
              <el-tag size="small" :type="qualityType(row.runtime_quality?.health)">{{ qualityText(row.runtime_quality) }}</el-tag>
              <small v-if="row.runtime_quality?.duration_ms" class="quality-detail">{{ row.runtime_quality.duration_ms }}ms · 命中 {{ row.runtime_quality.matched_count || 0 }}</small>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="runRule(row)">试运行</el-button>
              <el-button link @click="openEditRule(row)">编辑</el-button>
              <el-popconfirm title="删除该规则实例？" @confirm="removeRule(row)">
                <template #reference><el-button link type="danger">删除</el-button></template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </template>

    <template v-else-if="activeTab === 'policies'">
      <section class="toolbar panel policy-toolbar">
        <div class="toolbar-field source-field">
          <span>策略作用域</span>
          <el-select v-model="policySourceFilter" clearable placeholder="全部策略">
            <el-option label="全局策略" value="global" />
            <el-option v-for="item in metricSources" :key="item.id" :label="sourceLabel(item)" :value="String(item.id)" />
          </el-select>
        </div>
        <div class="toolbar-field search-field">
          <span>搜索</span>
          <el-input v-model="policySearch" clearable :prefix-icon="Search" placeholder="策略名称" />
        </div>
        <el-button plain @click="openPreview">预览路由结果</el-button>
      </section>

      <section class="panel table-panel">
        <el-table :data="filteredPolicies" stripe v-loading="loading" empty-text="暂无通知策略">
          <el-table-column label="策略" min-width="210">
            <template #default="{ row }"><div class="primary-cell"><strong>{{ row.name }}</strong><small>优先级 {{ row.priority }}</small></div></template>
          </el-table-column>
          <el-table-column label="作用域" min-width="190">
            <template #default="{ row }">
              <el-tag v-if="!row.metric_datasource" effect="plain">全局</el-tag>
              <span v-else>{{ row.metric_datasource_detail?.cluster_name || row.metric_datasource_detail?.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="匹配条件" min-width="240">
            <template #default="{ row }">
              <div class="tag-list">
                <el-tag v-for="(item, index) in row.matchers" :key="index" size="small" effect="plain">{{ item.key }} {{ item.operator || item.op || '=' }} {{ item.value }}</el-tag>
                <span v-if="!row.matchers?.length">全部标签</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="渠道" min-width="180">
            <template #default="{ row }"><span>{{ (row.channels || []).map((item) => item.name).join('、') || '-' }}</span></template>
          </el-table-column>
          <el-table-column label="聚合" min-width="180">
            <template #default="{ row }">{{ (row.group_by || []).join(' / ') || '平台默认维度' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }"><el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag></template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button link @click="openPolicy(row)">编辑</el-button>
              <el-popconfirm title="删除该通知策略？" @confirm="removePolicy(row)">
                <template #reference><el-button link type="danger">删除</el-button></template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </template>

    <template v-else>
      <section class="resource-workspace">
        <nav class="resource-tabs panel">
          <button :class="{ active: resourceTab === 'channels' }" @click="resourceTab = 'channels'">通知渠道</button>
          <button :class="{ active: resourceTab === 'recipients' }" @click="resourceTab = 'recipients'">接收人</button>
          <button :class="{ active: resourceTab === 'groups' }" @click="resourceTab = 'groups'">接收组</button>
          <button :class="{ active: resourceTab === 'reports' }" @click="resourceTab = 'reports'">巡检报告</button>
        </nav>

        <div v-if="resourceTab === 'channels'" class="panel table-panel resource-panel">
          <div class="section-head">
            <div><h2>通知渠道</h2><p>渠道是全局发送资源，由通知策略统一选择；接收组不重复绑定渠道。</p></div>
            <el-button type="primary" :icon="Plus" @click="openChannel()">新增渠道</el-button>
          </div>
          <el-table :data="filteredChannels" stripe empty-text="暂无通知渠道">
            <el-table-column prop="name" label="渠道名称" min-width="180" />
            <el-table-column label="类型" width="110"><template #default="{ row }">{{ row.channel_type_display || channelTypeText(row.channel_type) }}</template></el-table-column>
            <el-table-column label="恢复通知" width="110"><template #default="{ row }">{{ row.send_resolved ? '发送' : '不发送' }}</template></el-table-column>
            <el-table-column prop="updated_at" label="更新时间" width="180"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></el-table-column>
            <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag></template></el-table-column>
            <el-table-column label="操作" width="160" fixed="right"><template #default="{ row }"><el-button link type="success" @click="testChannel(row)">测试</el-button><el-button link @click="openChannel(row)">编辑</el-button></template></el-table-column>
          </el-table>
        </div>

        <div v-else-if="resourceTab === 'recipients'" class="panel table-panel resource-panel">
          <div class="section-head">
            <div><h2>接收人</h2><p>统一维护接收渠道及必要联系方式；飞书、钉钉和企微复用机器人渠道。</p></div>
            <div class="resource-actions"><el-input v-model="resourceSearch" clearable :prefix-icon="Search" placeholder="搜索姓名、联系方式或所属组" /><el-button type="primary" :icon="Plus" @click="openRecipient()">新增接收人</el-button></div>
          </div>
          <el-table :data="filteredRecipients" stripe empty-text="暂无接收人">
            <el-table-column label="接收人" min-width="190"><template #default="{ row }"><div class="primary-cell"><strong>{{ row.name }}</strong><small>{{ row.user_detail?.display_name || row.user_detail?.username || '独立联系人' }}</small></div></template></el-table-column>
            <el-table-column label="联系方式" min-width="300"><template #default="{ row }"><div class="tag-list"><el-tag v-for="item in row.contact_channels" :key="item" size="small" effect="plain">{{ channelTypeText(item) }}</el-tag><span v-if="!row.contact_channels?.length" class="warning-text">未配置有效联系方式</span></div></template></el-table-column>
            <el-table-column label="所属接收组" min-width="220"><template #default="{ row }">{{ (row.group_refs || []).map((item) => item.name).join('、') || '-' }}</template></el-table-column>
            <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag></template></el-table-column>
            <el-table-column label="操作" width="150" fixed="right"><template #default="{ row }"><el-button link @click="openRecipient(row)">编辑</el-button><el-popconfirm title="删除该接收人？" @confirm="removeRecipient(row)"><template #reference><el-button link type="danger">删除</el-button></template></el-popconfirm></template></el-table-column>
          </el-table>
        </div>

        <div v-else-if="resourceTab === 'groups'" class="panel table-panel resource-panel">
          <div class="section-head">
            <div><h2>接收组</h2><p>静态成员组由通知策略引用；列表直接展示成员健康度、联系方式覆盖和策略引用。</p></div>
            <div class="resource-actions"><el-input v-model="resourceSearch" clearable :prefix-icon="Search" placeholder="搜索组名、成员或策略" /><el-button type="primary" :icon="Plus" @click="openRecipientGroup()">新增接收组</el-button></div>
          </div>
          <el-table :data="filteredRecipientGroups" stripe empty-text="暂无接收组">
            <el-table-column label="接收组" min-width="210"><template #default="{ row }"><div class="primary-cell"><strong>{{ row.name }}</strong><small>{{ row.description || '未填写说明' }}</small></div></template></el-table-column>
            <el-table-column label="成员" width="150"><template #default="{ row }"><span>{{ row.active_member_count || 0 }} / {{ row.member_count || 0 }} 可用</span></template></el-table-column>
            <el-table-column label="联系方式覆盖" min-width="300"><template #default="{ row }"><div class="tag-list"><el-tag v-for="item in coverageTags(row)" :key="item.key" size="small" effect="plain">{{ item.label }} {{ item.count }}</el-tag><span v-if="!coverageTags(row).length" class="warning-text">无可用联系方式</span></div></template></el-table-column>
            <el-table-column label="资源引用" min-width="240"><template #default="{ row }">{{ recipientGroupReferences(row) }}</template></el-table-column>
            <el-table-column label="健康度" width="110"><template #default="{ row }"><el-tag :type="groupHealth(row).type">{{ groupHealth(row).label }}</el-tag></template></el-table-column>
            <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag></template></el-table-column>
            <el-table-column label="操作" width="150" fixed="right"><template #default="{ row }"><el-button link @click="openRecipientGroup(row)">编辑</el-button><el-button link type="danger" :disabled="Boolean(row.policy_count || row.report_schedule_count)" @click="removeRecipientGroup(row)">删除</el-button></template></el-table-column>
          </el-table>
        </div>

        <div v-else class="panel table-panel resource-panel">
          <div class="section-head">
            <div><h2>巡检报告</h2><p>按每天或每周自动执行确定性巡检，并发送到选定渠道、接收人或接收组。</p></div>
            <el-button type="primary" :icon="Plus" @click="openInspectionReport()">新增巡检报告</el-button>
          </div>
          <el-table :data="inspectionReports" stripe empty-text="暂无巡检报告计划">
            <el-table-column label="计划" min-width="210"><template #default="{ row }"><div class="primary-cell"><strong>{{ row.name }}</strong><small>{{ row.knowledge_environment_detail?.name || '-' }}</small></div></template></el-table-column>
            <el-table-column label="发送周期" min-width="150"><template #default="{ row }">{{ inspectionReportScheduleText(row) }}</template></el-table-column>
            <el-table-column label="巡检范围" min-width="150"><template #default="{ row }">{{ row.profile_display || inspectionProfileText(row.profile) }}</template></el-table-column>
            <el-table-column label="通知渠道" min-width="180"><template #default="{ row }">{{ (row.channels || []).map((item) => item.name).join('、') || '-' }}</template></el-table-column>
            <el-table-column label="接收对象" min-width="240"><template #default="{ row }">{{ inspectionReportRecipients(row) }}</template></el-table-column>
            <el-table-column label="下次发送" width="180"><template #default="{ row }">{{ formatTime(row.next_run_at) }}</template></el-table-column>
            <el-table-column label="最近状态" width="110"><template #default="{ row }"><el-tag :type="inspectionStatusType(row.last_status)">{{ row.last_status_display || inspectionStatusText(row.last_status) }}</el-tag></template></el-table-column>
            <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag></template></el-table-column>
            <el-table-column label="操作" width="190" fixed="right"><template #default="{ row }"><el-button link type="success" @click="runInspectionReport(row)">立即发送</el-button><el-button link @click="openInspectionReport(row)">编辑</el-button><el-popconfirm title="删除该巡检报告计划？" @confirm="removeInspectionReport(row)"><template #reference><el-button link type="danger">删除</el-button></template></el-popconfirm></template></el-table-column>
          </el-table>
        </div>
      </section>
    </template>

    <el-dialog v-model="instantiateDialog" title="从模板创建规则实例" width="640px">
      <el-form label-width="120px">
        <el-form-item label="K8S 数据源" required><el-select v-model="instanceForm.metric_datasource_id" filterable><el-option v-for="item in metricSources" :key="item.id" :label="sourceLabel(item)" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="模板分类"><el-select v-model="templateGroup" clearable placeholder="全部分类" @change="handleTemplateGroupChange"><el-option v-for="item in templateGroupOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
        <el-form-item label="内置模板" required>
          <el-select v-model="instanceForm.template_code" filterable>
            <el-option-group v-for="group in groupedK8sTemplates" :key="group.value" :label="group.label">
              <el-option v-for="item in group.templates" :key="item.code" :label="item.name" :value="item.code" />
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item label="规则名称"><el-input v-model="instanceForm.name" placeholder="留空使用模板名称和集群名称" /></el-form-item>
        <div class="form-grid">
          <el-form-item label="评估间隔"><el-input-number v-model="instanceForm.interval_seconds" :min="30" :step="30" /><span class="suffix">秒</span></el-form-item>
          <el-form-item label="持续时间"><el-input-number v-model="instanceForm.duration_seconds" :min="0" :step="30" /><span class="suffix">秒</span></el-form-item>
        </div>
        <el-form-item label="智能研判"><el-switch v-model="instanceForm.auto_analyze" /><span class="form-help">告警命中后关联指标、日志和知识图谱进行分析</span></el-form-item>
        <el-alert type="info" :closable="false" title="新实例默认停用，请先试运行确认指标存在后再启用。" />
      </el-form>
      <template #footer><el-button @click="instantiateDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveInstance">创建实例</el-button></template>
    </el-dialog>

    <el-dialog v-model="ruleDialog" :title="ruleForm.id ? '编辑规则实例' : '创建自定义 Prometheus 规则'" width="760px">
      <el-form label-width="120px">
        <el-form-item label="指标数据源" required><el-select v-model="ruleForm.metric_datasource" filterable><el-option v-for="item in metricSources" :key="item.id" :label="sourceLabel(item)" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="规则名称" required><el-input v-model="ruleForm.name" /></el-form-item>
        <el-form-item label="PromQL" required><el-input v-model="ruleForm.promql" type="textarea" :rows="4" spellcheck="false" /></el-form-item>
        <div class="form-grid">
          <el-form-item label="比较符"><el-select v-model="ruleForm.operator"><el-option label="大于" value=">" /><el-option label="大于等于" value=">=" /><el-option label="小于" value="<" /><el-option label="小于等于" value="<=" /><el-option label="等于" value="==" /></el-select></el-form-item>
          <el-form-item label="告警阈值"><el-input-number v-model="ruleForm.threshold" /></el-form-item>
          <el-form-item label="持续时间"><el-input-number v-model="ruleForm.duration_seconds" :min="0" /><span class="suffix">秒</span></el-form-item>
          <el-form-item label="评估间隔"><el-input-number v-model="ruleForm.interval_seconds" :min="30" /><span class="suffix">秒</span></el-form-item>
        </div>
        <el-form-item label="告警级别"><el-radio-group v-model="ruleForm.level"><el-radio-button value="warning">警告</el-radio-button><el-radio-button value="critical">严重</el-radio-button><el-radio-button value="info">信息</el-radio-button></el-radio-group></el-form-item>
        <el-form-item label="智能研判"><el-switch v-model="ruleForm.auto_analyze" /><span class="form-help">告警命中后自动研判，也可在告警详情中手动重新研判</span></el-form-item>
        <el-form-item label="说明"><el-input v-model="ruleForm.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="ruleDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveRule">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="policyDialog" :title="policyForm.id ? '编辑通知策略' : '新增通知策略'" width="820px">
      <el-form label-width="130px">
        <el-form-item label="策略名称" required><el-input v-model="policyForm.name" /></el-form-item>
        <div class="form-grid">
          <el-form-item label="作用数据源"><el-select v-model="policyForm.metric_datasource" clearable placeholder="全局策略"><el-option v-for="item in metricSources" :key="item.id" :label="sourceLabel(item)" :value="item.id" /></el-select></el-form-item>
          <el-form-item label="最低级别"><el-select v-model="policyForm.min_level" clearable placeholder="全部级别"><el-option label="信息" value="info" /><el-option label="警告" value="warning" /><el-option label="严重" value="critical" /></el-select></el-form-item>
          <el-form-item label="优先级"><el-input-number v-model="policyForm.priority" :min="0" /></el-form-item>
          <el-form-item label="继续匹配"><el-switch v-model="policyForm.continue_matching" /></el-form-item>
        </div>
        <el-form-item label="标签匹配">
          <div class="matcher-list">
            <div v-for="(item, index) in policyForm.matchers" :key="index" class="matcher-row">
              <el-input v-model="item.key" placeholder="namespace / service / label.team" />
              <el-select v-model="item.operator"><el-option v-for="op in matcherOperators" :key="op" :label="op" :value="op" /></el-select>
              <el-input v-model="item.value" placeholder="匹配值" />
              <el-button text type="danger" @click="policyForm.matchers.splice(index, 1)">删除</el-button>
            </div>
            <el-button plain size="small" @click="policyForm.matchers.push(emptyMatcher())">添加匹配条件</el-button>
          </div>
        </el-form-item>
        <el-form-item label="通知渠道"><el-select v-model="policyForm.channel_ids" multiple filterable><el-option v-for="item in channels" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="接收组"><el-select v-model="policyForm.recipient_group_ids" multiple filterable><el-option v-for="item in recipientGroups" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="聚合维度"><el-select v-model="policyForm.group_by" multiple allow-create filterable><el-option v-for="item in groupByOptions" :key="item" :label="item" :value="item" /></el-select></el-form-item>
        <div class="form-grid triple">
          <el-form-item label="首次等待"><el-input-number v-model="policyForm.group_wait_seconds" :min="0" /><span class="suffix">秒</span></el-form-item>
          <el-form-item label="同组间隔"><el-input-number v-model="policyForm.group_interval_seconds" :min="0" /><span class="suffix">秒</span></el-form-item>
          <el-form-item label="重复通知"><el-input-number v-model="policyForm.repeat_interval_minutes" :min="1" /><span class="suffix">分钟</span></el-form-item>
          <el-form-item label="风暴阈值"><el-input-number v-model="policyForm.storm_threshold" :min="1" /><span class="suffix">同组告警达到该数量时合并摘要</span></el-form-item>
        </div>
        <el-form-item label="静默时段"><el-switch v-model="policyForm.mute_enabled" /><el-time-picker v-if="policyForm.mute_enabled" v-model="policyForm.mute_range" is-range format="HH:mm" value-format="HH:mm" start-placeholder="开始" end-placeholder="结束" /></el-form-item>
        <el-form-item label="升级等待"><el-input-number v-model="policyForm.escalation_after_minutes" :min="0" /><span class="suffix">分钟，0 表示不升级</span></el-form-item>
        <el-form-item label="通知动作"><el-checkbox v-model="policyForm.notify_on_fire">触发通知</el-checkbox><el-checkbox v-model="policyForm.notify_on_resolved">恢复通知</el-checkbox><el-checkbox v-model="policyForm.notify_on_analysis">研判完成通知</el-checkbox><el-checkbox v-model="policyForm.is_enabled">启用策略</el-checkbox></el-form-item>
      </el-form>
      <template #footer><el-button @click="policyDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="savePolicy">保存策略</el-button></template>
    </el-dialog>

    <el-dialog v-model="previewDialog" title="通知策略路由预览" width="650px">
      <el-form label-width="110px">
        <el-form-item label="指标数据源"><el-select v-model="previewForm.metric_datasource_id"><el-option v-for="item in metricSources" :key="item.id" :label="sourceLabel(item)" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="告警级别"><el-select v-model="previewForm.level"><el-option label="信息" value="info" /><el-option label="警告" value="warning" /><el-option label="严重" value="critical" /></el-select></el-form-item>
        <el-form-item label="标签 JSON"><el-input v-model="previewForm.labelsText" type="textarea" :rows="5" spellcheck="false" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="previewing" @click="runPreview">开始匹配</el-button></el-form-item>
      </el-form>
      <div v-if="previewResult" class="preview-result"><strong>命中 {{ previewResult.matched_count }} 条策略</strong><div v-for="item in previewResult.policies" :key="item.id"><b>{{ item.name }}</b><span>{{ (item.channels || []).map((channel) => channel.name).join('、') || '未配置渠道' }}</span></div></div>
    </el-dialog>

    <el-dialog v-model="channelDialog" :title="channelForm.id ? '编辑通知渠道' : '新增通知渠道'" width="600px">
      <el-form label-width="110px">
        <el-form-item label="渠道名称" required><el-input v-model="channelForm.name" /></el-form-item>
        <el-form-item label="渠道类型"><el-select v-model="channelForm.channel_type"><el-option label="邮件" value="email" /><el-option label="钉钉" value="dingtalk" /><el-option label="飞书" value="feishu" /><el-option label="企微" value="wecom" /><el-option label="短信" value="sms" /><el-option label="语音" value="voice" /></el-select></el-form-item>
        <el-form-item v-if="channelForm.channel_type === 'email'" label="收件地址"><el-input v-model="channelForm.destination" placeholder="多个邮箱使用逗号分隔" /></el-form-item>
        <el-form-item v-else label="Webhook URL"><el-input v-model="channelForm.destination" type="textarea" :rows="3" /></el-form-item>
        <el-form-item v-if="channelForm.channel_type === 'feishu'" label="签名密钥" required><el-input v-model="channelForm.secret" type="password" show-password placeholder="飞书机器人签名校验必填" /></el-form-item>
        <el-form-item label="通知行为"><el-checkbox v-model="channelForm.send_resolved">发送恢复通知</el-checkbox><el-checkbox v-model="channelForm.is_enabled">启用渠道</el-checkbox></el-form-item>
      </el-form>
      <template #footer><el-button @click="channelDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveChannel">保存渠道</el-button></template>
    </el-dialog>

    <el-dialog v-model="recipientDialog" :title="recipientForm.id ? '编辑接收人' : '新增接收人'" width="680px">
      <el-form label-width="110px">
        <el-form-item label="姓名" required><el-input v-model="recipientForm.name" /></el-form-item>
        <el-form-item label="平台用户"><el-select v-model="recipientForm.user" clearable filterable placeholder="可选，关联平台账号"><el-option v-for="item in users" :key="item.id" :label="item.display_name || item.username" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="接收渠道" required>
          <el-select v-model="recipientForm.preferred_channels" multiple filterable collapse-tags collapse-tags-tooltip placeholder="选择该接收人可用的通知方式">
            <el-option v-for="item in recipientChannelOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <div class="form-grid">
          <el-form-item v-if="recipientForm.preferred_channels.includes('sms') || recipientForm.preferred_channels.includes('voice')" label="手机号" required><el-input v-model="recipientForm.phone" placeholder="短信和语音通知使用" /></el-form-item>
          <el-form-item v-if="recipientForm.preferred_channels.includes('email')" label="邮箱" required><el-input v-model="recipientForm.email" placeholder="邮件通知使用" /></el-form-item>
          <el-form-item label="启用"><el-switch v-model="recipientForm.is_enabled" /></el-form-item>
        </div>
        <el-alert type="info" :closable="false" title="飞书、钉钉和企微使用通知渠道中配置的机器人发送，无需填写个人标识。" />
        <el-form-item label="说明"><el-input v-model="recipientForm.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="recipientDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveRecipient">保存接收人</el-button></template>
    </el-dialog>

    <el-dialog v-model="recipientGroupDialog" :title="recipientGroupForm.id ? '编辑接收组' : '新增接收组'" width="860px">
      <el-form label-width="110px">
        <div class="form-grid">
          <el-form-item label="接收组名称" required><el-input v-model="recipientGroupForm.name" /></el-form-item>
          <el-form-item label="启用"><el-switch v-model="recipientGroupForm.is_enabled" /></el-form-item>
        </div>
        <el-form-item label="接收人">
          <div class="member-selector">
            <el-select v-model="recipientGroupForm.recipient_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="选择已登记接收人">
              <el-option v-for="item in recipients" :key="item.id" :label="recipientOptionLabel(item)" :value="item.id" :disabled="!item.is_enabled" />
            </el-select>
            <el-button plain :icon="Plus" @click="openRecipient(null, true)">内联新增</el-button>
          </div>
        </el-form-item>
        <el-form-item label="平台用户"><el-select v-model="recipientGroupForm.user_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="选择平台用户"><el-option v-for="item in users" :key="item.id" :label="item.display_name || item.username" :value="item.id" :disabled="item.is_active === false" /></el-select></el-form-item>
        <el-form-item label="成员诊断">
          <div class="group-diagnostic">
            <strong>{{ recipientGroupDraft.memberCount }} 名成员，{{ recipientGroupDraft.reachableCount }} 名具备联系方式</strong>
            <div class="tag-list"><el-tag v-for="item in recipientGroupDraft.coverage" :key="item.key" size="small" effect="plain">{{ item.label }} {{ item.count }}</el-tag><span v-if="!recipientGroupDraft.coverage.length" class="warning-text">当前成员没有可用于通知的联系方式</span></div>
          </div>
        </el-form-item>
        <el-form-item v-if="recipientGroupForm.policy_refs?.length" label="引用策略"><div class="tag-list"><el-tag v-for="item in recipientGroupForm.policy_refs" :key="item.id" size="small">{{ item.name }}</el-tag></div></el-form-item>
        <el-form-item label="说明"><el-input v-model="recipientGroupForm.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="recipientGroupDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveRecipientGroup">保存接收组</el-button></template>
    </el-dialog>

    <el-dialog v-model="inspectionReportDialog" :title="inspectionReportForm.id ? '编辑巡检报告' : '新增巡检报告'" width="760px">
      <el-form label-width="120px">
        <el-form-item label="计划名称" required><el-input v-model="inspectionReportForm.name" placeholder="例如：生产集群每周巡检报告" /></el-form-item>
        <el-form-item label="业务上下文" required>
          <el-select v-model="inspectionReportForm.knowledge_environment" filterable placeholder="选择业务上下文">
            <el-option v-for="item in contexts" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="发送周期" required><el-radio-group v-model="inspectionReportForm.frequency"><el-radio-button value="daily">每天</el-radio-button><el-radio-button value="weekly">每周</el-radio-button></el-radio-group></el-form-item>
          <el-form-item v-if="inspectionReportForm.frequency === 'weekly'" label="发送星期" required><el-select v-model="inspectionReportForm.weekday"><el-option v-for="item in weekdayOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
          <el-form-item label="发送时间" required><el-time-picker v-model="inspectionReportForm.send_time" format="HH:mm" value-format="HH:mm:ss" placeholder="选择时间" /></el-form-item>
          <el-form-item label="巡检范围" required><el-select v-model="inspectionReportForm.profile"><el-option v-for="item in inspectionProfileOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
          <el-form-item label="证据时间窗"><el-input-number v-model="inspectionReportForm.window_minutes" :min="5" :max="360" :step="5" /><span class="suffix">分钟</span></el-form-item>
        </div>
        <el-form-item label="通知渠道" required><el-select v-model="inspectionReportForm.channel_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="选择通知渠道"><el-option v-for="item in channels.filter((channel) => channel.is_enabled)" :key="item.id" :label="`${item.name} · ${channelTypeText(item.channel_type)}`" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="接收人"><el-select v-model="inspectionReportForm.recipient_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="按姓名选择接收人"><el-option v-for="item in recipients.filter((recipient) => recipient.is_enabled)" :key="item.id" :label="recipientOptionLabel(item)" :value="item.id" /></el-select><span class="form-help">菜单只显示姓名和联系方式，无需填写内部编号。</span></el-form-item>
        <el-form-item label="接收组"><el-select v-model="inspectionReportForm.recipient_group_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="也可以选择接收组"><el-option v-for="item in recipientGroups.filter((group) => group.is_enabled)" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="启用"><el-switch v-model="inspectionReportForm.is_enabled" /></el-form-item>
        <el-alert type="info" :closable="false" title="报告由平台确定性巡检管线生成；模型不可用时仍会发送已获取的指标、K8S、日志和资产证据。" />
      </el-form>
      <template #footer><el-button @click="inspectionReportDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveInspectionReport">保存计划</el-button></template>
    </el-dialog>

    <el-dialog v-model="resultDialog" title="规则试运行结果" width="760px"><pre class="result-json">{{ runResult }}</pre></el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import ObservabilityRouteTabs from '@/components/observability/ObservabilityRouteTabs.vue'
import { useBusinessContextStore } from '@/stores/businessContext'
import {
  createAlertNotificationChannel,
  createAlertNotificationPolicy,
  createAlertRecipient,
  createAlertRecipientGroup,
  createAlertRule,
  createInspectionReportSchedule,
  deleteAlertNotificationPolicy,
  deleteAlertRecipient,
  deleteAlertRecipientGroup,
  deleteAlertRule,
  deleteInspectionReportSchedule,
  evaluateAlertRule,
  getAlertNotificationChannels,
  getAlertNotificationPolicies,
  getAlertRecipients,
  getAlertRecipientGroups,
  getAlertRuleTemplates,
  getAlertRules,
  getInspectionReportSchedules,
  getMetricDataSources,
  getUsers,
  instantiateAlertRule,
  patchAlertRule,
  previewAlertNotificationPolicy,
  runInspectionReportSchedule,
  testAlertNotificationChannel,
  updateAlertNotificationChannel,
  updateAlertNotificationPolicy,
  updateAlertRecipient,
  updateAlertRecipientGroup,
  updateInspectionReportSchedule,
} from '@/api/modules/ops'

const businessContextStore = useBusinessContextStore()
const { contexts, currentContext, currentContextId } = storeToRefs(businessContextStore)
const activeTab = ref('rules')
const loading = ref(false)
const saving = ref(false)
const previewing = ref(false)
const viewMode = ref('all')
const selectedSourceId = ref('')
const ruleCategory = ref('')
const ruleGroup = ref('')
const ruleSearch = ref('')
const policySourceFilter = ref('')
const policySearch = ref('')
const resourceTab = ref('channels')
const resourceSearch = ref('')
const metricSources = ref([])
const templates = ref([])
const rules = ref([])
const policies = ref([])
const channels = ref([])
const recipients = ref([])
const recipientGroups = ref([])
const inspectionReports = ref([])
const users = ref([])
const instantiateDialog = ref(false)
const ruleDialog = ref(false)
const policyDialog = ref(false)
const previewDialog = ref(false)
const channelDialog = ref(false)
const recipientDialog = ref(false)
const recipientGroupDialog = ref(false)
const inspectionReportDialog = ref(false)
const resultDialog = ref(false)
const runResult = ref('')
const templateGroup = ref('')

const viewModeOptions = [{ label: '统一列表', value: 'all' }, { label: '按 K8S 源', value: 'source' }]
const matcherOperators = ['=', '!=', '=~', '!~']
const groupByOptions = ['cluster', 'namespace', 'service', 'resource', 'resource_type', 'alert_rule_code', 'label.team']
const instanceForm = reactive({ metric_datasource_id: '', template_code: '', name: '', interval_seconds: 60, duration_seconds: 0, auto_analyze: true })
const ruleForm = reactive(emptyRuleForm())
const policyForm = reactive(emptyPolicyForm())
const previewForm = reactive({ metric_datasource_id: '', level: 'warning', labelsText: '{\n  "namespace": "xing-cloud",\n  "service": "api"\n}' })
const channelForm = reactive(emptyChannelForm())
const recipientForm = reactive(emptyRecipientForm())
const recipientGroupForm = reactive(emptyRecipientGroupForm())
const inspectionReportForm = reactive(emptyInspectionReportForm())
const addRecipientToOpenGroup = ref(false)
const previewResult = ref(null)
const contextReady = ref(false)
const weekdayOptions = [
  { label: '星期一', value: 1 }, { label: '星期二', value: 2 }, { label: '星期三', value: 3 },
  { label: '星期四', value: 4 }, { label: '星期五', value: 5 }, { label: '星期六', value: 6 },
  { label: '星期日', value: 7 },
]
const inspectionProfileOptions = [
  { label: '集群综合巡检', value: 'cluster' },
  { label: '服务器巡检', value: 'server' },
]
const recipientChannelOptions = [
  { label: '邮件', value: 'email' },
  { label: '短信', value: 'sms' },
  { label: '语音', value: 'voice' },
  { label: '钉钉', value: 'dingtalk' },
  { label: '飞书', value: 'feishu' },
  { label: '企微', value: 'wecom' },
]

const k8sTemplates = computed(() => templates.value.filter((item) => item.category === 'k8s' && item.source_type === 'prometheus'))
const templateGroupOptions = computed(() => {
  const groups = new Map()
  k8sTemplates.value.forEach((item) => {
    const value = item.labels?.rule_group || 'basic'
    const label = item.labels?.rule_group_label || '基础监控'
    if (!groups.has(value)) groups.set(value, label)
  })
  const order = ['basic', 'apiserver', 'workload', 'network', 'storage', 'system']
  return [...groups.entries()]
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => order.indexOf(a.value) - order.indexOf(b.value))
})
const groupedK8sTemplates = computed(() => templateGroupOptions.value
  .filter((group) => !templateGroup.value || group.value === templateGroup.value)
  .map((group) => ({
    ...group,
    templates: k8sTemplates.value.filter((item) => (item.labels?.rule_group || 'basic') === group.value),
  })))
const filteredRules = computed(() => rules.value.filter((item) => {
  if (ruleCategory.value && item.category !== ruleCategory.value) return false
  if (ruleGroup.value && item.template_detail?.rule_group !== ruleGroup.value) return false
  const text = ruleSearch.value.trim().toLowerCase()
  return !text || [item.name, item.code, item.source, item.template_detail?.name].some((value) => String(value || '').toLowerCase().includes(text))
}))
const enabledRuleCount = computed(() => filteredRules.value.filter((item) => item.is_enabled).length)
const bindingRuleCount = computed(() => filteredRules.value.filter((item) => item.needs_binding).length)
const ruleEmptyText = computed(() => {
  if (!currentContext.value) return '请先在顶部选择业务上下文'
  if (!currentContext.value.metric_datasource) return '当前业务上下文未绑定指标数据源'
  return '当前数据源暂无规则实例'
})
const filteredPolicies = computed(() => policies.value.filter((item) => {
  const boundDatasourceId = String(currentContext.value?.metric_datasource || '')
  if (!currentContextId.value || !boundDatasourceId) return false
  if (item.metric_datasource && String(item.metric_datasource) !== boundDatasourceId) return false
  if (policySourceFilter.value === 'global' && item.metric_datasource) return false
  if (policySourceFilter.value && policySourceFilter.value !== 'global' && String(item.metric_datasource) !== policySourceFilter.value) return false
  return !policySearch.value.trim() || item.name.toLowerCase().includes(policySearch.value.trim().toLowerCase())
}))
const normalizedResourceSearch = computed(() => resourceSearch.value.trim().toLowerCase())
const filteredChannels = computed(() => channels.value.filter((item) => {
  const text = normalizedResourceSearch.value
  return !text || [item.name, item.channel_type_display, item.channel_type].some((value) => String(value || '').toLowerCase().includes(text))
}))
const filteredRecipients = computed(() => recipients.value.filter((item) => {
  const text = normalizedResourceSearch.value
  return !text || [
    item.name, item.phone, item.email, item.user_detail?.display_name, item.user_detail?.username,
    ...(item.contact_channels || []).map(channelTypeText),
    ...(item.group_refs || []).map((group) => group.name),
  ].some((value) => String(value || '').toLowerCase().includes(text))
}))
const filteredRecipientGroups = computed(() => recipientGroups.value.filter((item) => {
  const text = normalizedResourceSearch.value
  return !text || [
    item.name, item.description, recipientGroupMembers(item),
    ...(item.policy_refs || []).map((policy) => policy.name),
    ...(item.report_schedule_refs || []).map((report) => report.name),
  ].some((value) => String(value || '').toLowerCase().includes(text))
}))
const recipientGroupDraft = computed(() => {
  const selectedRecipients = recipients.value.filter((item) => recipientGroupForm.recipient_ids.includes(item.id) && item.is_enabled)
  const selectedUsers = users.value.filter((item) => recipientGroupForm.user_ids.includes(item.id) && item.is_active !== false)
  const coverage = contactCoverage(selectedRecipients, selectedUsers)
  const reachableRecipients = selectedRecipients.filter((item) => item.contact_channels?.length).length
  const reachableUsers = selectedUsers.filter((item) => item.email).length
  return {
    memberCount: selectedRecipients.length + selectedUsers.length,
    reachableCount: reachableRecipients + reachableUsers,
    coverage: coverageTags({ contact_coverage: coverage }),
  }
})

function listOf(response) { return Array.isArray(response) ? response : (response?.results || []) }
function sourceLabel(item) { return `${item.cluster_name || item.name}${item.environment ? ` · ${item.environment}` : ''}` }
function levelText(value) { return { critical: '严重', warning: '警告', info: '信息' }[value] || value }
function levelType(value) { return { critical: 'danger', warning: 'warning', info: 'info' }[value] || 'info' }
function formatTime(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-' }
function qualityText(quality) {
  if (!quality) return '未评估'
  if (quality.health === 'error') return `查询失败 ${quality.consecutive_error_count || quality.error_count} 次`
  if (quality.health === 'no_data') return `无数据 ${quality.no_data_count} 次`
  if (quality.health === 'flapping') return `抖动 ${quality.flap_count} 次`
  return '健康'
}
function qualityType(value) { return { error: 'danger', no_data: 'warning', flapping: 'warning', healthy: 'success' }[value] || 'info' }
function emptyMatcher() { return { key: '', operator: '=', value: '' } }
function cloneMatchers(value) { return Array.isArray(value) ? value.map((item) => ({ ...item })) : [] }
function emptyRuleForm() { return { id: null, metric_datasource: '', name: '', promql: '', operator: '>', threshold: 80, level: 'warning', duration_seconds: 300, interval_seconds: 60, auto_analyze: true, description: '' } }
function emptyPolicyForm() { return { id: null, name: '', metric_datasource: '', min_level: '', priority: 100, continue_matching: false, matchers: [], channel_ids: [], recipient_group_ids: [], group_by: ['cluster', 'namespace', 'service'], group_wait_seconds: 30, group_interval_seconds: 300, repeat_interval_minutes: 30, storm_threshold: 3, mute_enabled: false, mute_range: [], escalation_after_minutes: 0, notify_on_fire: true, notify_on_resolved: true, notify_on_analysis: true, is_enabled: true, description: '' } }
function emptyChannelForm() { return { id: null, name: '', channel_type: 'email', destination: '', secret: '', send_resolved: true, is_enabled: true, config: {} } }
function emptyRecipientForm() { return { id: null, name: '', user: null, preferred_channels: [], phone: '', email: '', is_enabled: true, description: '' } }
function emptyRecipientGroupForm() { return { id: null, name: '', recipient_ids: [], user_ids: [], policy_refs: [], is_enabled: true, description: '' } }
function emptyInspectionReportForm() { return { id: null, name: '', knowledge_environment: '', frequency: 'weekly', weekday: 1, send_time: '09:00:00', profile: 'cluster', window_minutes: 60, channel_ids: [], recipient_ids: [], recipient_group_ids: [], is_enabled: true } }

async function loadAll() {
  loading.value = true
  try {
    const [sourceResult, templateResult, channelResult, recipientResult, groupResult, userResult, reportResult] = await Promise.all([
      getMetricDataSources({ is_enabled: true, page_size: 200 }),
      getAlertRuleTemplates({ page_size: 200 }),
      getAlertNotificationChannels({ page_size: 200 }),
      getAlertRecipients({ page_size: 200 }),
      getAlertRecipientGroups({ page_size: 200 }),
      getUsers({ page_size: 500 }),
      currentContextId.value
        ? getInspectionReportSchedules({ knowledge_environment: currentContextId.value, page_size: 200 })
        : Promise.resolve([]),
    ])
    const boundDatasourceId = String(currentContext.value?.metric_datasource || '')
    metricSources.value = listOf(sourceResult).filter((item) => boundDatasourceId && String(item.id) === boundDatasourceId)
    templates.value = listOf(templateResult)
    channels.value = listOf(channelResult)
    recipients.value = listOf(recipientResult)
    recipientGroups.value = listOf(groupResult)
    users.value = listOf(userResult)
    inspectionReports.value = listOf(reportResult)
    selectedSourceId.value = metricSources.value[0]?.id || ''
    await Promise.all([loadRules(), loadPolicies()])
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '告警配置加载失败')
  } finally {
    loading.value = false
  }
}

async function loadRules() {
  if (!currentContextId.value || !selectedSourceId.value) {
    rules.value = []
    return
  }
  rules.value = listOf(await getAlertRules({
    is_template: false,
    knowledge_environment_id: currentContextId.value,
    metric_datasource_id: selectedSourceId.value,
    page_size: 200,
  }))
}
async function loadPolicies() {
  if (!currentContextId.value) {
    policies.value = []
    return
  }
  policies.value = listOf(await getAlertNotificationPolicies({
    knowledge_environment_id: currentContextId.value,
    page_size: 200,
  }))
}
async function handleViewMode() { await loadRules() }

function handleTemplateGroupChange() {
  const availableCodes = groupedK8sTemplates.value.flatMap((group) => group.templates.map((item) => item.code))
  if (!availableCodes.includes(instanceForm.template_code)) instanceForm.template_code = availableCodes[0] || ''
}
function openInstantiate() { templateGroup.value = ''; Object.assign(instanceForm, { metric_datasource_id: selectedSourceId.value || metricSources.value[0]?.id || '', template_code: k8sTemplates.value[0]?.code || '', name: '', interval_seconds: 60, duration_seconds: 0, auto_analyze: true }); instantiateDialog.value = true }
async function saveInstance() {
  if (!instanceForm.metric_datasource_id || !instanceForm.template_code) return ElMessage.warning('请选择 K8S 数据源和模板')
  saving.value = true
  try {
    const overrides = { interval_seconds: instanceForm.interval_seconds, duration_seconds: instanceForm.duration_seconds, auto_analyze: instanceForm.auto_analyze, is_enabled: false }
    if (instanceForm.name.trim()) overrides.name = instanceForm.name.trim()
    await instantiateAlertRule({ template_code: instanceForm.template_code, metric_datasource_id: instanceForm.metric_datasource_id, overrides })
    instantiateDialog.value = false
    selectedSourceId.value = viewMode.value === 'source' ? instanceForm.metric_datasource_id : selectedSourceId.value
    await loadRules()
    ElMessage.success('规则实例已创建，请先试运行后启用')
  } catch (error) { ElMessage.error(error.response?.data?.detail || '规则实例创建失败') } finally { saving.value = false }
}

function openCustomRule() { Object.assign(ruleForm, emptyRuleForm(), { metric_datasource: selectedSourceId.value || metricSources.value[0]?.id || '' }); ruleDialog.value = true }
function openEditRule(row) { Object.assign(ruleForm, emptyRuleForm(), { id: row.id, metric_datasource: row.metric_datasource || '', name: row.name, promql: row.query_config?.promql || row.query_config?.query || '', operator: row.condition?.operator || '>', threshold: row.condition?.threshold ?? row.condition?.levels?.[0]?.threshold ?? 80, level: row.level, duration_seconds: row.duration_seconds || 0, interval_seconds: row.interval_seconds || 60, auto_analyze: row.auto_analyze ?? true, description: row.description || '' }); ruleDialog.value = true }
async function saveRule() {
  if (!ruleForm.metric_datasource || !ruleForm.name.trim() || !ruleForm.promql.trim()) return ElMessage.warning('请完整填写数据源、名称和 PromQL')
  const source = metricSources.value.find((item) => item.id === ruleForm.metric_datasource)
  const payload = { metric_datasource: ruleForm.metric_datasource, name: ruleForm.name.trim(), category: 'k8s', source_type: 'prometheus', source: 'custom', level: ruleForm.level, query_config: { query: ruleForm.promql.trim() }, condition: { operator: ruleForm.operator, threshold: Number(ruleForm.threshold) }, labels: { environment: source?.environment || '', cluster: source?.cluster_name || '', metric_datasource_id: String(ruleForm.metric_datasource) }, annotations: {}, interval_seconds: ruleForm.interval_seconds, duration_seconds: ruleForm.duration_seconds, notify_enabled: true, auto_analyze: ruleForm.auto_analyze, is_enabled: false, is_template: false, description: ruleForm.description }
  saving.value = true
  try { if (ruleForm.id) await patchAlertRule(ruleForm.id, payload); else await createAlertRule(payload); ruleDialog.value = false; await loadRules(); ElMessage.success('规则已保存') } catch (error) { ElMessage.error(error.response?.data?.detail || error.response?.data?.metric_datasource?.[0] || '规则保存失败') } finally { saving.value = false }
}
async function toggleRule(row, value) { try { await patchAlertRule(row.id, { is_enabled: value }); row.is_enabled = value; ElMessage.success(value ? '规则已启用' : '规则已停用') } catch (error) { ElMessage.error(error.response?.data?.detail || '状态更新失败') } }
async function runRule(row) { try { const result = await evaluateAlertRule(row.id, { dry_run: true }); runResult.value = JSON.stringify(result, null, 2); resultDialog.value = true } catch (error) { runResult.value = JSON.stringify(error.response?.data || { detail: error.message }, null, 2); resultDialog.value = true } }
async function removeRule(row) { await deleteAlertRule(row.id); await loadRules(); ElMessage.success('规则已删除') }

function openPolicy(row = null) {
  const base = emptyPolicyForm()
  if (row) Object.assign(base, row, {
    channel_ids: (row.channels || []).map((item) => item.id),
    recipient_group_ids: (row.recipient_groups || []).map((item) => item.id),
    matchers: cloneMatchers(row.matchers),
    mute_enabled: Boolean(row.mute_schedule?.enabled),
    mute_range: row.mute_schedule?.start_time && row.mute_schedule?.end_time
      ? [row.mute_schedule.start_time, row.mute_schedule.end_time]
      : [],
    escalation_after_minutes: row.escalation_steps?.[0]?.after_minutes || 0,
  })
  Object.assign(policyForm, base)
  policyDialog.value = true
}
async function savePolicy() {
  if (!policyForm.name.trim()) return ElMessage.warning('请输入策略名称')
  const payload = { name: policyForm.name.trim(), metric_datasource: policyForm.metric_datasource || null, min_level: policyForm.min_level || '', priority: policyForm.priority, continue_matching: policyForm.continue_matching, matchers: policyForm.matchers.filter((item) => item.key && item.value !== ''), channel_ids: policyForm.channel_ids, recipient_group_ids: policyForm.recipient_group_ids, group_by: policyForm.group_by, group_wait_seconds: policyForm.group_wait_seconds, group_interval_seconds: policyForm.group_interval_seconds, repeat_interval_minutes: policyForm.repeat_interval_minutes, storm_threshold: policyForm.storm_threshold || 3, mute_schedule: policyForm.mute_enabled ? { enabled: true, start_time: policyForm.mute_range?.[0] || '00:00', end_time: policyForm.mute_range?.[1] || '00:00' } : {}, inhibition_matchers: [], escalation_steps: policyForm.escalation_after_minutes > 0 ? [{ name: '一级升级', after_minutes: policyForm.escalation_after_minutes, channel_ids: policyForm.channel_ids }] : [], notify_on_fire: policyForm.notify_on_fire, notify_on_resolved: policyForm.notify_on_resolved, notify_on_analysis: policyForm.notify_on_analysis, is_enabled: policyForm.is_enabled, description: policyForm.description || '' }
  saving.value = true
  try { if (policyForm.id) await updateAlertNotificationPolicy(policyForm.id, payload); else await createAlertNotificationPolicy(payload); policyDialog.value = false; await loadPolicies(); ElMessage.success('通知策略已保存') } catch (error) { ElMessage.error(error.response?.data?.detail || '通知策略保存失败') } finally { saving.value = false }
}
async function removePolicy(row) { await deleteAlertNotificationPolicy(row.id); await loadPolicies(); ElMessage.success('通知策略已删除') }
function openPreview() { previewForm.metric_datasource_id ||= selectedSourceId.value || metricSources.value[0]?.id || ''; previewResult.value = null; previewDialog.value = true }
async function runPreview() { previewing.value = true; try { previewResult.value = await previewAlertNotificationPolicy({ metric_datasource_id: previewForm.metric_datasource_id, level: previewForm.level, labels: JSON.parse(previewForm.labelsText || '{}') }) } catch (error) { ElMessage.error(error.message || '标签 JSON 格式错误') } finally { previewing.value = false } }

function openChannel(row = null) { const base = emptyChannelForm(); if (row) Object.assign(base, row, { destination: row.channel_type === 'email' ? (row.config?.to || []).join(', ') : row.config?.webhook_url || row.config?.url || '', secret: row.config?.secret || row.config?.sign_secret || '' }); Object.assign(channelForm, base); channelDialog.value = true }
async function saveChannel() { if (!channelForm.name.trim()) return ElMessage.warning('请输入渠道名称'); if (channelForm.channel_type === 'feishu' && !channelForm.secret) return ElMessage.warning('飞书渠道必须填写签名密钥'); const config = channelForm.channel_type === 'email' ? { ...(channelForm.config || {}), to: channelForm.destination.split(',').map((item) => item.trim()).filter(Boolean) } : { ...(channelForm.config || {}), webhook_url: channelForm.destination.trim(), ...(channelForm.channel_type === 'feishu' ? { secret: channelForm.secret } : {}) }; const payload = { name: channelForm.name.trim(), channel_type: channelForm.channel_type, config, send_resolved: channelForm.send_resolved, is_enabled: channelForm.is_enabled }; saving.value = true; try { if (channelForm.id) await updateAlertNotificationChannel(channelForm.id, payload); else await createAlertNotificationChannel(payload); channelDialog.value = false; channels.value = listOf(await getAlertNotificationChannels()); ElMessage.success('通知渠道已保存') } catch (error) { ElMessage.error(error.response?.data?.detail || '渠道保存失败') } finally { saving.value = false } }
async function testChannel(row) { try { await testAlertNotificationChannel(row.id); ElMessage.success('渠道测试已执行，请在通知记录中查看结果') } catch (error) { ElMessage.error(error.response?.data?.detail || '渠道测试失败') } }
function recipientGroupMembers(row) { return [...(row.recipients || []).map((item) => item.name), ...(row.users || []).map((item) => item.display_name || item.username)].join('、') || '-' }
function recipientGroupReferences(row) {
  const values = [
    ...(row.policy_refs || []).map((item) => `${item.name}（策略）`),
    ...(row.report_schedule_refs || []).map((item) => `${item.name}（巡检）`),
  ]
  return values.join('、') || '未引用'
}

function channelTypeText(value) {
  return { email: '邮件', sms: '短信', voice: '语音', dingtalk: '钉钉', feishu: '飞书', wecom: '企微' }[value] || value
}
function coverageTags(row) {
  const coverage = row?.contact_coverage || {}
  return [
    { key: 'email', label: '邮件', count: Number(coverage.email || 0) },
    { key: 'phone', label: '手机', count: Number(coverage.phone || 0) },
    { key: 'dingtalk', label: '钉钉', count: Number(coverage.dingtalk || 0) },
    { key: 'feishu', label: '飞书', count: Number(coverage.feishu || 0) },
    { key: 'wecom', label: '企微', count: Number(coverage.wecom || 0) },
  ].filter((item) => item.count > 0)
}
function groupHealth(row) {
  return {
    ready: { label: '可通知', type: 'success' },
    partial: { label: '部分缺失', type: 'warning' },
    unreachable: { label: '不可达', type: 'danger' },
    empty: { label: '无成员', type: 'info' },
  }[row?.health_status] || { label: '待诊断', type: 'info' }
}
function contactCoverage(selectedRecipients, selectedUsers) {
  return {
    email: selectedRecipients.filter((item) => item.contact_channels?.includes('email')).length + selectedUsers.filter((item) => item.email).length,
    phone: selectedRecipients.filter((item) => item.contact_channels?.includes('sms') || item.contact_channels?.includes('voice')).length,
    dingtalk: selectedRecipients.filter((item) => item.contact_channels?.includes('dingtalk')).length,
    feishu: selectedRecipients.filter((item) => item.contact_channels?.includes('feishu')).length,
    wecom: selectedRecipients.filter((item) => item.contact_channels?.includes('wecom')).length,
  }
}
function recipientOptionLabel(item) {
  const channels = (item.contact_channels || []).map(channelTypeText).join('/')
  return `${item.name}${channels ? ` · ${channels}` : ' · 无联系方式'}`
}
async function refreshRecipientResources() {
  const [recipientResult, groupResult, userResult] = await Promise.all([
    getAlertRecipients({ page_size: 200 }),
    getAlertRecipientGroups({ page_size: 200 }),
    getUsers({ page_size: 500 }),
  ])
  recipients.value = listOf(recipientResult)
  recipientGroups.value = listOf(groupResult)
  users.value = listOf(userResult)
}
function openRecipient(row = null, addToGroup = false) {
  Object.assign(recipientForm, emptyRecipientForm(), row ? {
    id: row.id,
    name: row.name,
    user: row.user || null,
    preferred_channels: row.preferred_channels?.length ? [...row.preferred_channels] : [...(row.contact_channels || [])],
    phone: row.phone || '',
    email: row.email || '',
    is_enabled: row.is_enabled,
    description: row.description || '',
  } : {})
  addRecipientToOpenGroup.value = addToGroup
  recipientDialog.value = true
}
async function saveRecipient() {
  if (!recipientForm.name.trim()) return ElMessage.warning('请输入接收人姓名')
  if (!recipientForm.preferred_channels.length) return ElMessage.warning('请选择至少一个接收渠道')
  if (recipientForm.preferred_channels.includes('email') && !recipientForm.email.trim()) return ElMessage.warning('邮件渠道需要填写邮箱')
  if ((recipientForm.preferred_channels.includes('sms') || recipientForm.preferred_channels.includes('voice')) && !recipientForm.phone.trim()) return ElMessage.warning('短信或语音渠道需要填写手机号')
  const payload = {
    name: recipientForm.name.trim(), user: recipientForm.user || null,
    preferred_channels: recipientForm.preferred_channels,
    phone: recipientForm.phone.trim(), email: recipientForm.email.trim(),
    is_enabled: recipientForm.is_enabled,
    description: recipientForm.description.trim(),
  }
  saving.value = true
  try {
    const saved = recipientForm.id
      ? await updateAlertRecipient(recipientForm.id, payload)
      : await createAlertRecipient(payload)
    if (!recipientForm.id && addRecipientToOpenGroup.value && saved?.id) recipientGroupForm.recipient_ids.push(saved.id)
    recipientDialog.value = false
    await refreshRecipientResources()
    ElMessage.success('接收人已保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '接收人保存失败')
  } finally {
    saving.value = false
    addRecipientToOpenGroup.value = false
  }
}
async function removeRecipient(row) {
  try {
    await deleteAlertRecipient(row.id)
    await refreshRecipientResources()
    ElMessage.success('接收人已删除')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '接收人删除失败')
  }
}
function openRecipientGroup(row = null) {
  Object.assign(recipientGroupForm, emptyRecipientGroupForm(), row ? {
    id: row.id,
    name: row.name,
    recipient_ids: (row.recipients || []).map((item) => item.id),
    user_ids: (row.users || []).map((item) => item.id),
    policy_refs: (row.policy_refs || []).map((item) => ({ ...item })),
    is_enabled: row.is_enabled,
    description: row.description || '',
  } : {})
  recipientGroupDialog.value = true
}
async function saveRecipientGroup() {
  if (!recipientGroupForm.name.trim()) return ElMessage.warning('请输入接收组名称')
  if (recipientGroupForm.is_enabled && !recipientGroupForm.recipient_ids.length && !recipientGroupForm.user_ids.length) return ElMessage.warning('启用的接收组至少需要一个成员')
  const payload = {
    name: recipientGroupForm.name.trim(),
    recipient_ids: recipientGroupForm.recipient_ids,
    user_ids: recipientGroupForm.user_ids,
    is_enabled: recipientGroupForm.is_enabled,
    description: recipientGroupForm.description.trim(),
  }
  saving.value = true
  try {
    if (recipientGroupForm.id) await updateAlertRecipientGroup(recipientGroupForm.id, payload)
    else await createAlertRecipientGroup(payload)
    recipientGroupDialog.value = false
    await refreshRecipientResources()
    ElMessage.success('接收组已保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '接收组保存失败')
  } finally {
    saving.value = false
  }
}
async function removeRecipientGroup(row) {
  if (row.policy_count) return ElMessage.warning(`接收组正在被 ${row.policy_count} 条通知策略引用，请先解除引用`)
  if (row.report_schedule_count) return ElMessage.warning(`接收组正在被 ${row.report_schedule_count} 个巡检报告计划引用，请先解除引用`)
  try {
    await deleteAlertRecipientGroup(row.id)
    await refreshRecipientResources()
    ElMessage.success('接收组已删除')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '接收组删除失败')
  }
}

function inspectionProfileText(value) {
  return inspectionProfileOptions.find((item) => item.value === value)?.label || value
}
function inspectionStatusText(value) {
  return { never: '未执行', success: '成功', partial: '部分成功', failed: '失败' }[value] || value
}
function inspectionStatusType(value) {
  return { success: 'success', partial: 'warning', failed: 'danger', never: 'info' }[value] || 'info'
}
function inspectionReportScheduleText(row) {
  const time = String(row.send_time || '09:00').slice(0, 5)
  if (row.frequency === 'daily') return `每天 ${time}`
  const weekday = weekdayOptions.find((item) => item.value === Number(row.weekday))?.label || '星期一'
  return `每周${weekday.replace('星期', '周')} ${time}`
}
function inspectionReportRecipients(row) {
  const names = [
    ...(row.recipients || []).map((item) => item.name),
    ...(row.recipient_groups || []).map((item) => `${item.name}（组）`),
  ]
  return names.join('、') || '-'
}
function openInspectionReport(row = null) {
  Object.assign(inspectionReportForm, emptyInspectionReportForm(), row ? {
    id: row.id,
    name: row.name,
    knowledge_environment: row.knowledge_environment,
    frequency: row.frequency,
    weekday: Number(row.weekday || 1),
    send_time: row.send_time || '09:00:00',
    profile: row.profile || 'cluster',
    window_minutes: Number(row.window_minutes || 60),
    channel_ids: (row.channels || []).map((item) => item.id),
    recipient_ids: (row.recipients || []).map((item) => item.id),
    recipient_group_ids: (row.recipient_groups || []).map((item) => item.id),
    is_enabled: row.is_enabled,
  } : {
    knowledge_environment: Number(currentContextId.value) || '',
  })
  inspectionReportDialog.value = true
}
async function saveInspectionReport() {
  if (!inspectionReportForm.name.trim()) return ElMessage.warning('请输入计划名称')
  if (!inspectionReportForm.knowledge_environment) return ElMessage.warning('请选择业务上下文')
  if (inspectionReportForm.is_enabled && !inspectionReportForm.channel_ids.length) return ElMessage.warning('请选择至少一个通知渠道')
  if (inspectionReportForm.is_enabled && !inspectionReportForm.recipient_ids.length && !inspectionReportForm.recipient_group_ids.length) return ElMessage.warning('请选择至少一个接收人或接收组')
  const payload = {
    name: inspectionReportForm.name.trim(),
    knowledge_environment: inspectionReportForm.knowledge_environment,
    frequency: inspectionReportForm.frequency,
    weekday: inspectionReportForm.frequency === 'weekly' ? inspectionReportForm.weekday : 1,
    send_time: inspectionReportForm.send_time,
    timezone: 'Asia/Shanghai',
    profile: inspectionReportForm.profile,
    depth: 'full',
    window_minutes: inspectionReportForm.window_minutes,
    channel_ids: inspectionReportForm.channel_ids,
    recipient_ids: inspectionReportForm.recipient_ids,
    recipient_group_ids: inspectionReportForm.recipient_group_ids,
    is_enabled: inspectionReportForm.is_enabled,
  }
  saving.value = true
  try {
    if (inspectionReportForm.id) await updateInspectionReportSchedule(inspectionReportForm.id, payload)
    else await createInspectionReportSchedule(payload)
    inspectionReportDialog.value = false
    inspectionReports.value = listOf(await getInspectionReportSchedules({ knowledge_environment: currentContextId.value, page_size: 200 }))
    await refreshRecipientResources()
    ElMessage.success('巡检报告计划已保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.response?.data?.recipient_ids?.[0] || error.response?.data?.channel_ids?.[0] || '巡检报告计划保存失败')
  } finally {
    saving.value = false
  }
}
async function runInspectionReport(row) {
  try {
    const result = await runInspectionReportSchedule(row.id)
    await loadAll()
    if (result.status === 'success') ElMessage.success('巡检报告已生成并发送')
    else ElMessage.warning(result.error_message || '巡检完成，但部分渠道发送失败')
  } catch (error) {
    ElMessage.error(error.response?.data?.error_message || error.response?.data?.detail || '巡检报告发送失败')
  }
}
async function removeInspectionReport(row) {
  try {
    await deleteInspectionReportSchedule(row.id)
    inspectionReports.value = listOf(await getInspectionReportSchedules({ knowledge_environment: currentContextId.value, page_size: 200 }))
    await refreshRecipientResources()
    ElMessage.success('巡检报告计划已删除')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '巡检报告计划删除失败')
  }
}

watch(activeTab, async (value) => { if (value === 'policies') await loadPolicies() })
watch(currentContextId, async () => {
  if (contextReady.value) await loadAll()
})
onMounted(async () => {
  await businessContextStore.loadContexts()
  contextReady.value = true
  await loadAll()
})
</script>

<style scoped>
.alert-rule-page { min-height: 100%; padding: 18px 22px 36px; color: #24364b; background: #f4f7fb; }
.page-header, .work-tabs, .toolbar, .summary-grid, .table-panel, .resource-workspace { max-width: 1760px; margin-left: auto; margin-right: auto; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 12px; }
.eyebrow { color: #7890aa; font-size: 11px; letter-spacing: .08em; } h1 { margin: 5px 0; color: #172b42; font-size: 25px; } .page-header p, .section-head p { margin: 0; color: #73879d; font-size: 12px; }
.header-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.panel { border: 1px solid #dce5ef; background: #fff; box-shadow: 0 5px 16px rgba(38,64,94,.06); }
.work-tabs { display: flex; gap: 4px; margin-top: 12px; margin-bottom: 10px; padding: 4px; border: 1px solid #dce5ef; background: #fff; }
.work-tabs button { min-width: 130px; padding: 9px 18px; border: 0; color: #627991; background: transparent; cursor: pointer; } .work-tabs button.active { color: #fff; background: #3478d4; }
.toolbar { display: flex; align-items: flex-end; flex-wrap: wrap; gap: 10px; margin-bottom: 10px; padding: 11px; }
.toolbar-field { display: grid; gap: 5px; width: 180px; } .toolbar-field span { color: #617891; font-size: 11px; } .source-field { width: 280px; } .search-field { flex: 1; min-width: 250px; } .view-switch { width: auto; }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 10px; margin-bottom: 10px; }
.summary-card { display: grid; gap: 6px; padding: 13px 16px; border: 1px solid #dce5ef; border-top: 2px solid #6fa6e8; background: #fff; box-shadow: 0 4px 12px rgba(38,64,94,.05); } .summary-card span { color: #71869c; font-size: 12px; } .summary-card strong { color: #2778cf; font-size: 26px; } .summary-card.success { border-top-color: #20b486; } .summary-card.warning { border-top-color: #e5a12a; }
.table-panel { padding: 12px; } .primary-cell, .source-cell { display: grid; gap: 3px; } .primary-cell strong, .source-cell strong { color: #263d55; } .primary-cell small, .source-cell small { color: #8496a8; font-size: 11px; font-family: Consolas, monospace; }
.tag-list { display: flex; flex-wrap: wrap; gap: 4px; }.policy-toolbar { justify-content: flex-start; }
.resource-workspace { display: grid; gap: 10px; }.resource-tabs { display: flex; gap: 4px; padding: 4px; }.resource-tabs button { min-width: 120px; padding: 8px 16px; border: 0; color: #627991; background: transparent; cursor: pointer; }.resource-tabs button.active { color: #245bdb; background: #eaf2ff; box-shadow: inset 0 0 0 1px #cfe0f7; }.resource-panel { width: 100%; box-sizing: border-box; }.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 10px; }.section-head h2 { margin: 0 0 4px; font-size: 16px; }.resource-actions { display: flex; align-items: center; gap: 8px; min-width: 420px; }.resource-actions .el-input { min-width: 280px; }.warning-text { color: #d97706; font-size: 12px; }.member-selector { display: flex; align-items: center; gap: 8px; width: 100%; }.member-selector .el-select { flex: 1; }.group-diagnostic { display: grid; gap: 8px; width: 100%; padding: 10px 12px; border: 1px solid #dce5ef; background: #f8fafc; }.group-diagnostic strong { color: #344b63; font-size: 13px; }
.form-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 0 12px; }.form-grid.triple { grid-template-columns: repeat(3,minmax(0,1fr)); }.suffix { margin-left: 7px; color: #71869c; font-size: 12px; }.form-help { margin-left: 9px; color: #73879d; font-size: 12px; }
.matcher-list { display: grid; gap: 7px; width: 100%; }.matcher-row { display: grid; grid-template-columns: 1.3fr 90px 1.3fr 54px; gap: 7px; }.preview-result { display: grid; gap: 8px; padding: 12px; border: 1px solid #dce5ef; background: #f8fafc; }.preview-result > div { display: flex; justify-content: space-between; gap: 10px; }.result-json { max-height: 560px; overflow: auto; padding: 14px; color: #dbeafe; background: #172334; white-space: pre-wrap; }
:deep(.el-select), :deep(.el-input) { width: 100%; }:deep(.el-table) { --el-table-header-bg-color: #f5f8fb; --el-table-row-hover-bg-color: #f5f9ff; }
@media (max-width: 1000px) { .summary-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }.form-grid,.form-grid.triple { grid-template-columns: 1fr; }.section-head { flex-direction: column; }.resource-actions { width: 100%; min-width: 0; }.rule-instance-table :deep(.el-table__header),.rule-instance-table :deep(.el-table__body),.rule-instance-table :deep(.el-scrollbar__view) { width: 100% !important; }.rule-instance-table :deep(col:nth-child(2)),.rule-instance-table :deep(col:nth-child(3)),.rule-instance-table :deep(col:nth-child(6)),.rule-instance-table :deep(th:nth-child(2)),.rule-instance-table :deep(th:nth-child(3)),.rule-instance-table :deep(th:nth-child(6)),.rule-instance-table :deep(td:nth-child(2)),.rule-instance-table :deep(td:nth-child(3)),.rule-instance-table :deep(td:nth-child(6)) { display: none; } }
@media (max-width: 700px) { .alert-rule-page { padding: 12px; }.page-header { flex-direction: column; }.header-actions { justify-content: flex-start; }.summary-grid { grid-template-columns: 1fr; }.toolbar-field,.source-field,.search-field { width: 100%; }.matcher-row { grid-template-columns: 1fr; }.work-tabs,.resource-tabs { overflow-x: auto; }.work-tabs button,.resource-tabs button { min-width: 110px; }.resource-actions,.member-selector { align-items: stretch; flex-direction: column; }.resource-actions .el-input { min-width: 0; width: 100%; } }
</style>
