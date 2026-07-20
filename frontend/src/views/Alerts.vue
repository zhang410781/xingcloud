<template>
  <div class="alerts-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon">
            <el-icon><Bell /></el-icon>
          </span>
          <h2>{{ pageTitle }}</h2>
          <p class="page-inline-desc">{{ pageDescription }}</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :icon="Refresh" :loading="loading || configLoading" @click="refreshAll">&#x5237;&#x65B0;</el-button>
      </div>
    </section>

    <ObservabilityRouteTabs group="observability" />

    <div v-if="isEventWorkspace" class="audit-grid alert-top-stats">
      <button
        v-for="card in statCards"
        :key="card.key"
        type="button"
        class="audit-card audit-card--inline audit-card--action alert-summary-card"
        :class="[card.tone, { 'is-active': activeStatKey === card.key }]"
        @click="applyStatFilter(card)"
      >
        <div class="stat-label">{{ card.label }}</div>
        <div class="stat-value">{{ card.value }}</div>
      </button>
    </div>

    <div v-if="!isEventWorkspace" class="neo-tabs theme-blue alert-center-tabs">
      <button v-if="canViewConfig" class="neo-tab-btn" :class="{ active: activeTab === 'rules' }" @click="switchTab('rules')">
        <el-icon style="margin-right: 4px;"><Operation /></el-icon>&#x544A;&#x8B66;&#x89C4;&#x5219;
      </button>
      <button v-if="canViewConfig" class="neo-tab-btn" :class="{ active: activeTab === 'notify' }" @click="switchTab('notify')">
        <el-icon style="margin-right: 4px;"><Setting /></el-icon>&#x901A;&#x77E5;&#x914D;&#x7F6E;
      </button>
    </div>

    <template v-if="activeTab === 'events' && canViewAlerts">
      <section class="panel">
        <div class="toolbar">
          <el-select v-model="filters.status" size="small" clearable placeholder="&#x72B6;&#x6001;" @change="handleFilterChange">
            <el-option label="&#x6D3B;&#x8DC3;" value="active" />
            <el-option label="&#x5DF2;&#x6062;&#x590D;" value="resolved" />
            <el-option label="&#x5DF2;&#x5C4F;&#x853D;" value="muted" />
            <el-option label="&#x5DF2;&#x5173;&#x95ED;" value="closed" />
          </el-select>
          <el-select v-model="filters.source_type" size="small" clearable placeholder="&#x6765;&#x6E90;" @change="handleFilterChange">
            <el-option v-for="item in providerOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select v-model="filters.environment" size="small" clearable filterable allow-create default-first-option placeholder="&#x73AF;&#x5883;" @change="handleFilterChange">
            <el-option v-for="item in environmentOptions" :key="item" :label="item" :value="item" />
          </el-select>
          <el-select v-model="filters.level" size="small" clearable placeholder="&#x7EA7;&#x522B;" @change="handleFilterChange">
            <el-option label="&#x4E25;&#x91CD;" value="critical" />
            <el-option label="&#x8B66;&#x544A;" value="warning" />
            <el-option label="&#x4FE1;&#x606F;" value="info" />
          </el-select>
          <el-input
            v-model="filters.search"
            size="small"
            clearable
            placeholder="&#x641C;&#x7D22;&#x6807;&#x9898; / &#x6765;&#x6E90; / &#x670D;&#x52A1; / &#x8D44;&#x6E90;"
            :prefix-icon="Search"
            @input="handleFilterChange"
          />
          <el-segmented v-model="eventMode" size="small" :options="eventModeOptions" @change="refreshEvents" />
          <el-button size="small" :icon="Refresh" :loading="loading" @click="refreshEvents">&#x5237;&#x65B0;</el-button>
          <div class="toolbar-spacer" />
          <el-button
            v-if="canManageAlerts && eventMode === 'list'"
            size="small"
            type="danger"
            :disabled="!selectedAlerts.length"
            @click="handleBatchDelete"
          >
            &#x6279;&#x91CF;&#x5220;&#x9664;
          </el-button>
        </div>

        <div v-if="eventMode === 'group'" class="group-toolbar">
          <span class="toolbar-label">&#x5206;&#x7EC4;&#x7EF4;&#x5EA6;</span>
          <el-select v-model="groupBy" size="small" multiple collapse-tags collapse-tags-tooltip @change="fetchGroups">
            <el-option v-for="item in dimensionOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </div>

        <el-table v-if="eventMode === 'list'" :data="alerts" stripe size="small" v-loading="loading" class="data-table list-data-table" @selection-change="handleSelectionChange">
          <el-table-column type="selection" width="42" />
          <el-table-column prop="id" label="告警ID" width="70">
            <template #default="{ row }">
              <span class="alert-id-cell">{{ row.id }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="title" label="&#x544A;&#x8B66;&#x6807;&#x9898;" min-width="240">
            <template #default="{ row }">
              <button class="link-title" type="button" @click="openDetail(row)">{{ row.title }}</button>
              <div class="sub-line">{{ row.service || row.resource || row.source }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="level" label="&#x7EA7;&#x522B;" width="80">
            <template #default="{ row }">
              <el-tag :type="levelType(row.level)" size="small">{{ row.level_display || levelText(row.level) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="&#x72B6;&#x6001;" width="80">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{ row.status_display || statusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="source_type" label="接入" width="120">
            <template #default="{ row }">{{ providerText(row.source_type) }}</template>
          </el-table-column>
          <el-table-column prop="category" label="分类" width="90">
            <template #default="{ row }">{{ categoryText(row.category) }}</template>
          </el-table-column>
          <el-table-column prop="environment" label="&#x73AF;&#x5883;" width="100" />
          <el-table-column prop="claimed_by" label="&#x8BA4;&#x9886;&#x4EBA;" width="120">
            <template #default="{ row }">
              <div class="claimant-cell" v-if="row.claimants?.length">
                <el-tag v-for="item in row.claimants" :key="item.id" size="small" class="mini-tag claimant-tag">{{ item.claimant }}</el-tag>
              </div>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="occurrence_count" label="&#x6B21;&#x6570;" width="60" />
          <el-table-column prop="last_received_at" label="&#x6700;&#x8FD1;&#x63A5;&#x6536;" width="180">
            <template #default="{ row }">{{ formatTime(row.last_received_at || row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="&#x64CD;&#x4F5C;" width="145" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <el-button v-if="canManageAlerts && !row.current_user_claimed" link type="success" size="small" @click="runAlertAction(row, 'claim')">&#x8BA4;&#x9886;</el-button>
                <el-button v-if="canManageAlerts" link type="warning" size="small" @click="openMuteDialog(row)">&#x5C4F;&#x853D;</el-button>
                <el-button link size="small" type="primary" @click="openDetail(row)">&#x8BE6;&#x60C5;</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <el-table v-else :data="groups" stripe size="small" v-loading="loading" class="data-table group-data-table">
          <el-table-column label="&#x5206;&#x7EC4;" min-width="280">
            <template #default="{ row }">
              <div v-if="groupDimensionEntries(row).length" class="group-dimensions">
                <span v-for="item in groupDimensionEntries(row)" :key="item.key">
                  <strong>{{ item.label }}：</strong>{{ item.value }}
                </span>
              </div>
              <div v-else class="group-key">{{ row.key }}</div>
              <div class="sub-line">{{ row.sample_title }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="total" label="&#x603B;&#x6570;" width="80" />
          <el-table-column prop="critical" label="&#x4E25;&#x91CD;" width="80" />
          <el-table-column prop="warning" label="&#x8B66;&#x544A;" width="80" />
          <el-table-column prop="unacknowledged" label="&#x672A;&#x8BA4;&#x9886;" width="90" />
          <el-table-column prop="suppressed" label="&#x6291;&#x5236;" width="100" />
          <el-table-column prop="latest_at" label="&#x6700;&#x65B0;&#x65F6;&#x95F4;" width="170">
            <template #default="{ row }">{{ formatTime(row.latest_at) }}</template>
          </el-table-column>
          <el-table-column label="&#x64CD;&#x4F5C;" width="120">
            <template #default="{ row }">
              <el-button link size="small" type="primary" @click="openGroup(row)">&#x67E5;&#x770B;&#x660E;&#x7EC6;</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pager" v-if="eventMode === 'list'">
          <el-pagination
            small
            v-model:current-page="page"
            :page-size="20"
            :total="total"
            layout="total, prev, pager, next"
            @current-change="refreshEvents"
          />
        </div>
      </section>
    </template>

    <template v-if="activeTab === 'notify' && canViewConfig">
      <section class="panel">
        <div class="neo-sub-tabs theme-blue alert-sub-tabs">
          <button class="neo-sub-tab-btn" :class="{ active: notifyTab === 'rules' }" @click="changeNotifyTab('rules')">&#x901A;&#x77E5;&#x89C4;&#x5219;</button>
          <button class="neo-sub-tab-btn" :class="{ active: notifyTab === 'channels' }" @click="changeNotifyTab('channels')">&#x901A;&#x77E5;&#x6E20;&#x9053;</button>
          <button class="neo-sub-tab-btn" :class="{ active: notifyTab === 'recipients' }" @click="changeNotifyTab('recipients')">&#x63A5;&#x6536;&#x5BF9;&#x8C61;</button>
        </div>

        <div v-show="notifyTab === 'rules'">
          <div class="section-head">
            <h3>&#x901A;&#x77E5;&#x89C4;&#x5219;</h3>
            <el-button v-if="canManageConfig" size="small" type="primary" :icon="Plus" @click="openNotificationRule()">&#x65B0;&#x589E;&#x89C4;&#x5219;</el-button>
          </div>
          <el-table :data="notificationRules" stripe size="small" v-loading="configLoading">
            <el-table-column prop="name" label="&#x89C4;&#x5219;&#x540D;&#x79F0;" min-width="180" />
            <el-table-column prop="min_level" label="&#x6700;&#x4F4E;&#x7EA7;&#x522B;" width="110">
              <template #default="{ row }">{{ levelText(row.min_level) || '&#x5168;&#x90E8;' }}</template>
            </el-table-column>
            <el-table-column label="&#x6E20;&#x9053;" min-width="180">
              <template #default="{ row }">
                <el-tag v-for="item in row.channels" :key="item.id" size="small" class="mini-tag">{{ item.channel_type_display || channelText(item.channel_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="&#x63A5;&#x6536;&#x7EC4;" min-width="180">
              <template #default="{ row }">{{ (row.recipient_groups || []).map((item) => item.name).join(', ') || '-' }}</template>
            </el-table-column>
            <el-table-column label="&#x72B6;&#x6001;" width="90">
              <template #default="{ row }">
                <el-tag :type="row.is_enabled ? 'success' : 'info'" size="small">{{ row.is_enabled ? '&#x542F;&#x7528;' : '&#x505C;&#x7528;' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="&#x64CD;&#x4F5C;" width="150" fixed="right">
              <template #default="{ row }">
                <el-button v-if="canManageConfig" link size="small" @click="openNotificationRule(row)">&#x7F16;&#x8F91;</el-button>
                <el-popconfirm v-if="canManageConfig" title="&#x5220;&#x9664;&#x8BE5;&#x89C4;&#x5219;&#xFF1F;" @confirm="removeNotificationRule(row.id)">
                  <template #reference><el-button link type="danger" size="small">&#x5220;&#x9664;</el-button></template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div v-show="notifyTab === 'channels'">
          <div class="section-head">
            <h3>&#x901A;&#x77E5;&#x6E20;&#x9053;</h3>
            <el-button v-if="canManageConfig" size="small" type="primary" :icon="Plus" @click="openChannel()">&#x65B0;&#x589E;&#x6E20;&#x9053;</el-button>
          </div>
          <el-table :data="channels" stripe size="small" v-loading="configLoading">
            <el-table-column prop="name" label="&#x6E20;&#x9053;&#x540D;&#x79F0;" min-width="180" />
            <el-table-column prop="channel_type" label="&#x7C7B;&#x578B;" width="100">
              <template #default="{ row }">{{ row.channel_type_display || channelText(row.channel_type) }}</template>
            </el-table-column>
            <el-table-column prop="send_resolved" label="&#x6062;&#x590D;&#x901A;&#x77E5;" width="100">
              <template #default="{ row }">{{ row.send_resolved ? '&#x53D1;&#x9001;' : '&#x4E0D;&#x53D1;&#x9001;' }}</template>
            </el-table-column>
            <el-table-column prop="updated_at" label="&#x66F4;&#x65B0;&#x65F6;&#x95F4;" width="170">
              <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
            </el-table-column>
            <el-table-column label="&#x72B6;&#x6001;" width="90">
              <template #default="{ row }">
                <el-tag :type="row.is_enabled ? 'success' : 'info'" size="small">{{ row.is_enabled ? '&#x542F;&#x7528;' : '&#x505C;&#x7528;' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="&#x64CD;&#x4F5C;" width="190" fixed="right">
              <template #default="{ row }">
                <el-button v-if="canNotifyAlerts" link type="success" size="small" @click="testChannel(row)">&#x6D4B;&#x8BD5;</el-button>
                <el-button v-if="canManageConfig" link size="small" @click="openChannel(row)">&#x7F16;&#x8F91;</el-button>
                <el-popconfirm v-if="canManageConfig" title="&#x5220;&#x9664;&#x8BE5;&#x6E20;&#x9053;&#xFF1F;" @confirm="removeChannel(row.id)">
                  <template #reference><el-button link type="danger" size="small">&#x5220;&#x9664;</el-button></template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div v-show="notifyTab === 'recipients'">
          <div class="split-grid">
            <div class="split-panel">
              <div class="section-head">
                <h3>&#x63A5;&#x6536;&#x4EBA;</h3>
                <el-button v-if="canManageConfig" size="small" type="primary" :icon="Plus" @click="openRecipient()">&#x65B0;&#x589E;&#x63A5;&#x6536;&#x4EBA;</el-button>
              </div>
              <el-table :data="recipients" stripe size="small" v-loading="configLoading">
                <el-table-column prop="name" label="&#x59D3;&#x540D;" min-width="120" />
                <el-table-column prop="phone" label="&#x624B;&#x673A;" min-width="130" />
                <el-table-column prop="email" label="&#x90AE;&#x7BB1;" min-width="170" />
                <el-table-column label="&#x64CD;&#x4F5C;" width="120">
                  <template #default="{ row }">
                    <el-button v-if="canManageConfig" link size="small" @click="openRecipient(row)">&#x7F16;&#x8F91;</el-button>
                    <el-popconfirm v-if="canManageConfig" title="&#x5220;&#x9664;&#x8BE5;&#x63A5;&#x6536;&#x4EBA;&#xFF1F;" @confirm="removeRecipient(row.id)">
                      <template #reference><el-button link type="danger" size="small">&#x5220;&#x9664;</el-button></template>
                    </el-popconfirm>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <div class="split-panel">
              <div class="section-head">
                <h3>&#x63A5;&#x6536;&#x7EC4;</h3>
                <el-button v-if="canManageConfig" size="small" type="primary" :icon="Plus" @click="openRecipientGroup()">&#x65B0;&#x589E;&#x63A5;&#x6536;&#x7EC4;</el-button>
              </div>
              <el-table :data="recipientGroups" stripe size="small" v-loading="configLoading">
                <el-table-column prop="name" label="&#x7EC4;&#x540D;" min-width="130" />
                <el-table-column label="&#x6210;&#x5458;" min-width="220">
                  <template #default="{ row }">{{ groupMembers(row) }}</template>
                </el-table-column>
                <el-table-column label="&#x64CD;&#x4F5C;" width="120">
                  <template #default="{ row }">
                    <el-button v-if="canManageConfig" link size="small" @click="openRecipientGroup(row)">&#x7F16;&#x8F91;</el-button>
                    <el-popconfirm v-if="canManageConfig" title="&#x5220;&#x9664;&#x8BE5;&#x63A5;&#x6536;&#x7EC4;&#xFF1F;" @confirm="removeRecipientGroup(row.id)">
                      <template #reference><el-button link type="danger" size="small">&#x5220;&#x9664;</el-button></template>
                    </el-popconfirm>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </div>
      </section>
    </template>

    <template v-if="activeTab === 'policies' && canViewConfig">
      <section class="panel">
        <div class="neo-sub-tabs theme-blue alert-sub-tabs">
          <button class="neo-sub-tab-btn" :class="{ active: policyTab === 'aggregation' }" @click="changePolicyTab('aggregation')">&#x805A;&#x5408;</button>
          <button class="neo-sub-tab-btn" :class="{ active: policyTab === 'inhibition' }" @click="changePolicyTab('inhibition')">&#x6291;&#x5236;</button>
          <button class="neo-sub-tab-btn" :class="{ active: policyTab === 'mute' }" @click="changePolicyTab('mute')">&#x5C4F;&#x853D;</button>
          <button class="neo-sub-tab-btn" :class="{ active: policyTab === 'escalation' }" @click="changePolicyTab('escalation')">&#x5347;&#x7EA7;</button>
        </div>

        <div v-show="policyTab === 'aggregation'">
          <PolicyTable title="&#x805A;&#x5408;&#x89C4;&#x5219;" :data="aggregationRules" :loading="configLoading" :can-manage="canManageConfig" @create="openAggregationRule()" @edit="openAggregationRule" @remove="removeAggregationRule" />
        </div>
        <div v-show="policyTab === 'inhibition'">
          <PolicyTable title="&#x6291;&#x5236;&#x89C4;&#x5219;" :data="inhibitionRules" :loading="configLoading" :can-manage="canManageConfig" @create="openInhibitionRule()" @edit="openInhibitionRule" @remove="removeInhibitionRule" />
        </div>
        <div v-show="policyTab === 'mute'">
          <PolicyTable title="&#x5C4F;&#x853D;&#x89C4;&#x5219;" :data="muteRules" :loading="configLoading" :can-manage="canManageConfig" @create="openMuteRule()" @edit="openMuteRule" @remove="removeMuteRule" />
        </div>
        <div v-show="policyTab === 'escalation'">
          <PolicyTable title="&#x5347;&#x7EA7;&#x7B56;&#x7565;" :data="escalationPolicies" :loading="configLoading" :can-manage="canManageConfig" @create="openEscalationPolicy()" @edit="openEscalationPolicy" @remove="removeEscalationPolicy" />
        </div>
      </section>
    </template>

    <template v-if="activeTab === 'rules' && canViewConfig">
      <section class="panel">
        <div class="section-head">
<div class="category-filter neo-tabs theme-blue" style="margin-bottom:12px">
          <button
            v-for="cat in categoryOptions"
            :key="cat.value"
            class="neo-tab-btn"
            :class="{ active: rulesCategoryFilter === cat.value }"
            @click="rulesCategoryFilter = cat.value; fetchAlertRules()"
          >{{ cat.label }}</button>
        </div>
          <h3>告警规则</h3>
          <el-button v-if="canManageConfig" size="small" type="primary" :icon="Plus" @click="openWizardForSource()">新建规则</el-button>
        </div>
        <el-table :data="alertRules" stripe size="small" v-loading="configLoading">
          <el-table-column prop="name" label="规则名称" min-width="180">
            <template #default="{ row }">
              <div class="rule-name-cell">
                <strong>{{ row.name }}</strong>
                <span>{{ row.code }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="source_type" label="数据源" width="130">
            <template #default="{ row }">{{ ruleSourceText(row.source_type) }}</template>
          </el-table-column>
          <el-table-column prop="category" label="分类" width="90">
            <template #default="{ row }">{{ categoryText(row.category) }}</template>
          </el-table-column>
          <el-table-column prop="level" label="&#x7EA7;&#x522B;" width="90">
            <template #default="{ row }"><el-tag :type="levelType(row.level)" size="small">{{ row.level_display || levelText(row.level) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="&#x80FD;&#x529B;" width="145">
            <template #default="{ row }">
              <el-tag size="small" class="mini-tag" :type="row.notify_enabled ? 'success' : 'info'">&#x901A;&#x77E5;</el-tag>
              <el-tag size="small" class="mini-tag" :type="row.auto_analyze ? 'primary' : 'info'">AI</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="interval_seconds" label="&#x95F4;&#x9694;" width="90">
            <template #default="{ row }">{{ row.interval_seconds }}s</template>
          </el-table-column>
          <el-table-column prop="source" label="&#x6765;&#x6E90;" min-width="150" show-overflow-tooltip>
            <template #default="{ row }">{{ row.source === 'custom' ? '&#x81EA;&#x5B9A;&#x4E49;' : '&#x5185;&#x7F6E;&#x89C4;&#x5219;' }}</template>
          </el-table-column>
          <el-table-column prop="last_triggered_at" label="&#x6700;&#x8FD1;&#x89E6;&#x53D1;" width="160">
            <template #default="{ row }">{{ formatTime(row.last_triggered_at) }}</template>
          </el-table-column>
          <el-table-column label="&#x72B6;&#x6001;" width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_enabled ? 'success' : 'info'" size="small">{{ row.is_enabled ? '&#x542F;&#x7528;' : '&#x505C;&#x7528;' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="&#x64CD;&#x4F5C;" width="220" fixed="right">
            <template #default="{ row }">
              <el-button v-if="canManageConfig" link size="small" type="success" @click="dryRunAlertRule(row)">&#x8BD5;&#x8FD0;&#x884C;</el-button>
              <el-button v-if="canManageConfig" link size="small" type="primary" @click="testAlertRule(row)">&#x89E6;&#x53D1;</el-button>
              <el-button v-if="canManageConfig" link size="small" @click="openAlertRule(row)">&#x7F16;&#x8F91;</el-button>
              <el-popconfirm v-if="canManageConfig" title="&#x5220;&#x9664;&#x8BE5;&#x544A;&#x8B66;&#x89C4;&#x5219;&#xFF1F;" @confirm="removeAlertRule(row.id)">
                <template #reference><el-button link type="danger" size="small">&#x5220;&#x9664;</el-button></template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </template>

    <template v-if="activeTab === 'logs' && canViewAlerts">
      <section class="panel">
        <div class="section-head">
          <h3>&#x901A;&#x77E5;&#x8BB0;&#x5F55;</h3>
          <el-button size="small" :icon="Refresh" @click="fetchNotificationLogs">&#x5237;&#x65B0;</el-button>
        </div>
        <el-table :data="notificationLogs" stripe size="small" v-loading="configLoading">
          <el-table-column prop="created_at" label="&#x65F6;&#x95F4;" width="170">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="action" label="&#x52A8;&#x4F5C;" width="90" />
          <el-table-column prop="channel_name" label="&#x6E20;&#x9053;" width="140" />
          <el-table-column prop="rule_name" label="&#x89C4;&#x5219;" min-width="150" />
          <el-table-column prop="recipient_summary" label="&#x63A5;&#x6536;&#x5BF9;&#x8C61;" min-width="180" />
          <el-table-column prop="status" label="&#x72B6;&#x6001;" width="90">
            <template #default="{ row }">
              <el-tag :type="notifyStatusType(row.status)" size="small">{{ row.status_display || row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="error_message" label="&#x9519;&#x8BEF;&#x4FE1;&#x606F;" min-width="220" show-overflow-tooltip />
        </el-table>
      </section>
    </template>

    <el-drawer v-model="detailVisible" class="alert-detail-drawer" size="640px" title="&#x544A;&#x8B66;&#x8BE6;&#x60C5;">
      <template v-if="selectedAlert">
        <div class="alert-detail-body">
          <div class="detail-head">
            <div class="detail-badges">
              <el-tag :type="levelType(selectedAlert.level)">{{ selectedAlert.level_display || levelText(selectedAlert.level) }}</el-tag>
              <el-tag :type="statusType(selectedAlert.status)">{{ selectedAlert.status_display || statusText(selectedAlert.status) }}</el-tag>
              <span class="detail-alert-id">告警ID：{{ selectedAlert.id }}</span>
            </div>
            <span class="detail-title">{{ selectedAlert.title }}</span>
            <span class="detail-fingerprint">告警指纹：{{ selectedAlert.fingerprint || '-' }}</span>
          </div>
          <section class="alert-detail-card">
            <el-descriptions class="alert-detail-summary" :column="1" size="small" border>
              <el-descriptions-item label="&#x6765;&#x6E90;">{{ providerText(selectedAlert.source_type) }} / {{ selectedAlert.source }}</el-descriptions-item>
              <el-descriptions-item label="&#x8D44;&#x6E90;">{{ selectedAlert.resource || selectedAlert.host_name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="&#x670D;&#x52A1;">{{ selectedAlert.service || '-' }}</el-descriptions-item>
              <el-descriptions-item label="&#x73AF;&#x5883;">{{ selectedAlert.environment || '-' }}</el-descriptions-item>
              <el-descriptions-item label="&#x8BA4;&#x9886;&#x4EBA;">
                <div class="claimant-cell" v-if="selectedAlert.claimants?.length">
                  <el-tag v-for="item in selectedAlert.claimants" :key="item.id" size="small" class="mini-tag claimant-tag">{{ item.claimant }}</el-tag>
                </div>
                <span v-else>-</span>
              </el-descriptions-item>
              <el-descriptions-item label="&#x805A;&#x5408;&#x952E;">{{ selectedAlert.group_key || '-' }}</el-descriptions-item>
              <el-descriptions-item label="&#x63CF;&#x8FF0;">{{ selectedAlert.message }}</el-descriptions-item>
            </el-descriptions>
          </section>
          <section class="alert-detail-card log-evidence-card" v-loading="alertLogEvidenceLoading">
            <div class="detail-section-title">
              <h4>日志证据</h4>
              <span>
                {{ alertLogEvidence?.summary?.collection || 'ClickHouse' }}
                / {{ alertLogEvidence?.summary?.window_minutes || '-' }}m
                / {{ alertLogEvidence?.summary?.count || 0 }} 条
              </span>
            </div>
            <span v-if="alertLogEvidence?.summary?.error" class="detail-empty">{{ alertLogEvidence.summary.error }}</span>
            <span v-else-if="!alertLogEvidenceLoading && !alertLogEvidenceLogs.length" class="detail-empty">暂无匹配日志样本</span>
            <div v-else class="log-evidence-list">
              <article v-for="(log, index) in alertLogEvidenceLogs" :key="`${log.timestamp || index}-${index}`" class="log-evidence-item">
                <div class="log-evidence-meta">
                  <el-tag size="small" :type="logLevelType(log.level)">{{ String(log.level || '-').toUpperCase() }}</el-tag>
                  <span>{{ formatTime(log.timestamp) || log.timestamp || '-' }}</span>
                  <strong>{{ log.source || '-' }}</strong>
                </div>
                <p>{{ log.message || '-' }}</p>
              </article>
            </div>
          </section>
          <section class="alert-detail-card analysis-card" v-loading="alertAnalysisLoading">
            <div class="detail-section-title">
              <h4>智能研判</h4>
              <div class="analysis-heading-actions">
                <el-tag v-if="alertAnalysisLatest" size="small" :type="analysisStatusType(alertAnalysisLatest.status)">
                  {{ analysisStatusText(alertAnalysisLatest.status) }}
                </el-tag>
                <el-button
                  v-if="canManageAlerts && !['pending', 'running'].includes(alertAnalysisLatest?.status)"
                  link
                  type="primary"
                  size="small"
                  :loading="alertAnalysisSubmitting"
                  @click="submitAlertAnalysis"
                >{{ alertAnalysisLatest ? '重新研判' : '开始研判' }}</el-button>
              </div>
            </div>
            <span v-if="alertAnalysisUnavailable" class="detail-empty">当前后端版本暂未启用智能研判接口</span>
            <span v-else-if="!alertAnalysisLoading && !alertAnalysisLatest" class="detail-empty">该告警暂无研判记录</span>
            <template v-else-if="alertAnalysisLatest">
              <el-descriptions class="alert-detail-summary analysis-summary" :column="1" size="small" border>
                <el-descriptions-item label="置信度">{{ analysisConfidenceText(alertAnalysisLatest.confidence) }}</el-descriptions-item>
                <el-descriptions-item label="证据覆盖">{{ analysisSourceCoverageText }}</el-descriptions-item>
                <el-descriptions-item label="根因">{{ alertAnalysisLatest.root_cause || alertAnalysisLatest.summary || '尚未形成明确结论' }}</el-descriptions-item>
                <el-descriptions-item label="建议">{{ analysisSuggestionText(alertAnalysisLatest) }}</el-descriptions-item>
              </el-descriptions>
              <div v-if="analysisCandidates.length" class="analysis-evidence">
                <strong>候选根因</strong>
                <ol><li v-for="item in analysisCandidates" :key="item.code || item.title">{{ item.title || item.code }}（{{ analysisConfidenceText(item.score) }}）</li></ol>
              </div>
              <div v-if="analysisEvidenceItems.length" class="analysis-evidence">
                <strong>关键证据</strong>
                <ol>
                  <li v-for="(item, index) in analysisEvidenceItems" :key="index">{{ item }}</li>
                </ol>
              </div>
            </template>
          </section>
          <div v-if="canManageAlerts || canNotifyAlerts" class="detail-actions">
            <el-button v-if="!selectedAlert.current_user_claimed" size="small" type="success" @click="runAlertAction(selectedAlert, 'claim')">&#x8BA4;&#x9886;</el-button>
            <el-button v-if="selectedAlert.current_user_claimed" size="small" @click="runAlertAction(selectedAlert, 'unclaim')">&#x53D6;&#x6D88;&#x8BA4;&#x9886;</el-button>
            <el-button v-if="canManageAlerts" size="small" type="warning" @click="openMuteDialog(selectedAlert)">&#x5C4F;&#x853D;</el-button>
            <el-button v-if="canNotifyAlerts" size="small" type="primary" @click="runAlertAction(selectedAlert, 'notify')">&#x53D1;&#x9001;&#x901A;&#x77E5;</el-button>
            <el-button v-if="canManageAlerts" size="small" @click="runAlertAction(selectedAlert, 'close')">&#x5173;&#x95ED;&#x544A;&#x8B66;</el-button>
          </div>
          <section class="alert-detail-card">
            <div class="detail-section-title">
              <h4>&#x6807;&#x7B7E;</h4>
              <span>{{ Object.keys(selectedAlert.labels || {}).length }} 项</span>
            </div>
            <div class="kv-list">
              <el-tag v-for="(value, key) in selectedAlert.labels" :key="key" size="small">{{ key }}={{ value }}</el-tag>
              <span v-if="!Object.keys(selectedAlert.labels || {}).length" class="detail-empty">暂无标签</span>
            </div>
          </section>
          <section class="alert-detail-card">
            <div class="detail-section-title">
              <h4>&#x5904;&#x7406;&#x8BB0;&#x5F55;</h4>
              <span>{{ (selectedAlert.actions || []).length }} 条</span>
            </div>
            <el-timeline class="alert-detail-timeline">
              <el-timeline-item v-for="item in selectedAlert.actions || []" :key="item.id" :timestamp="formatTime(item.created_at)">
                {{ item.actor || '\u7CFB\u7EDF' }} / {{ item.action_display || item.action }} / {{ item.note || '-' }}
              </el-timeline-item>
            </el-timeline>
            <span v-if="!(selectedAlert.actions || []).length" class="detail-empty">暂无处理记录</span>
          </section>
        </div>
      </template>
    </el-drawer>

    <AlertRuleWizard
      v-model="ruleWizardVisible"
      :templates="alertRulePresets"
      @save="saveWizardRule"
    />

    <el-dialog v-model="ruleDialog.visible" title="&#x544A;&#x8B66;&#x89C4;&#x5219;" width="760px">
      <el-form :model="ruleDialog.form" label-width="130px">
        <el-form-item label="&#x89C4;&#x5219;&#x540D;&#x79F0;"><el-input v-model="ruleDialog.form.name" /></el-form-item>
        <el-form-item label="&#x89C4;&#x5219;&#x7F16;&#x7801;"><el-input v-model="ruleDialog.form.code" placeholder="&#x7559;&#x7A7A;&#x5219;&#x81EA;&#x52A8;&#x751F;&#x6210;" /></el-form-item>
        <el-form-item label="&#x6570;&#x636E;&#x6E90;">
          <el-select v-model="ruleDialog.form.source_type">
            <el-option v-for="item in ruleSourceOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="&#x7EA7;&#x522B;">
          <el-select v-model="ruleDialog.form.level">
            <el-option label="&#x4E25;&#x91CD;" value="critical" />
            <el-option label="&#x8B66;&#x544A;" value="warning" />
            <el-option label="&#x4FE1;&#x606F;" value="info" />
          </el-select>
        </el-form-item>
        <template v-if="isLogRule(ruleDialog.form)">
          <el-form-item label="&#x65E5;&#x5FD7;&#x8303;&#x56F4;">
            <el-select v-model="ruleDialog.form.log_collection">
              <el-option v-for="item in logCollectionOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="&#x65E5;&#x5FD7;&#x7EA7;&#x522B;">
            <el-checkbox-group v-model="ruleDialog.form.log_levels">
              <el-checkbox v-for="item in logLevelOptions" :key="item" :label="item">{{ item }}</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          <div class="split-grid">
            <el-form-item label="&#x7EDF;&#x8BA1;&#x65F6;&#x95F4;"><el-input-number v-model="ruleDialog.form.window_minutes" :min="1" :max="1440" /> <span class="field-suffix">&#x5206;&#x949F;</span></el-form-item>
            <el-form-item label="&#x805A;&#x5408;&#x7EF4;&#x5EA6;">
              <el-select v-model="ruleDialog.form.log_group_by" clearable placeholder="&#x603B;&#x91CF;">
                <el-option label="&#x6309;&#x5BB9;&#x5668;" value="container" />
                <el-option label="&#x6309;&#x670D;&#x52A1;" value="service" />
                <el-option label="&#x6309;&#x547D;&#x540D;&#x7A7A;&#x95F4;" value="namespace" />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item label="&#x5305;&#x542B;&#x5173;&#x952E;&#x5B57;"><el-input v-model="ruleDialog.form.keyword" clearable placeholder="&#x4E0D;&#x586B;&#x5219;&#x4E0D;&#x9650;&#x5236;" /></el-form-item>
        </template>
        <template v-else>
          <el-form-item label="&#x76D1;&#x63A7;&#x6307;&#x6807;">
            <el-select v-if="!ruleDialog.form.custom_query_enabled" v-model="ruleDialog.form.metric_key" filterable>
              <el-option v-for="item in metricOptionsFor(ruleDialog.form.source_type)" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-input v-else v-model="ruleDialog.form.custom_query" type="textarea" :rows="3" spellcheck="false" placeholder="输入 PromQL 查询语句" />
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="ruleDialog.form.custom_query_enabled">使用自定义 PromQL 查询</el-checkbox>
          </el-form-item>
          <el-alert title="&#x7CFB;&#x7EDF;&#x6839;&#x636E;&#x6240;&#x9009;&#x6307;&#x6807;&#x81EA;&#x52A8;&#x7EC4;&#x88C5;&#x67E5;&#x8BE2;&#xFF0C;&#x65E0;&#x9700;&#x7F16;&#x5199;&#x6307;&#x6807;&#x8BED;&#x53E5;" type="info" :closable="false" show-icon class="rule-form-tip" />
        </template>
        <div class="split-grid">
          <el-form-item label="&#x89E6;&#x53D1;&#x6761;&#x4EF6;">
            <el-select v-model="ruleDialog.form.operator">
              <el-option label="&#x5927;&#x4E8E;" value="&gt;" />
              <el-option label="&#x5927;&#x4E8E;&#x7B49;&#x4E8E;" value="&gt;=" />
              <el-option label="&#x5C0F;&#x4E8E;" value="&lt;" />
              <el-option label="&#x5C0F;&#x4E8E;&#x7B49;&#x4E8E;" value="&lt;=" />
              <el-option label="&#x7B49;&#x4E8E;" value="==" />
            </el-select>
          </el-form-item>
          <el-form-item label="&#x9608;&#x503C;"><el-input-number v-model="ruleDialog.form.threshold" :min="0" :precision="2" /></el-form-item>
        </div>
        <el-form-item label="&#x6807;&#x7B7E;"><MatcherEditor v-model="ruleDialog.form.label_rows" mode="equals" /></el-form-item>
        <el-form-item label="&#x6CE8;&#x89E3;"><MatcherEditor v-model="ruleDialog.form.annotation_rows" mode="equals" /></el-form-item>
        <div class="split-grid">
          <el-form-item label="&#x5DE1;&#x68C0;&#x95F4;&#x9694;"><el-input-number v-model="ruleDialog.form.interval_seconds" :min="10" /> <span class="field-suffix">s</span></el-form-item>
          <el-form-item label="&#x6301;&#x7EED;&#x65F6;&#x95F4;"><el-input-number v-model="ruleDialog.form.duration_seconds" :min="0" /> <span class="field-suffix">s</span></el-form-item>
        </div>
        <el-form-item label="&#x80FD;&#x529B;&#x5F00;&#x5173;">
          <el-checkbox v-model="ruleDialog.form.notify_enabled">&#x547D;&#x4E2D;&#x540E;&#x901A;&#x77E5;</el-checkbox>
          <el-checkbox v-model="ruleDialog.form.auto_analyze">&#x547D;&#x4E2D;&#x540E; AI &#x7814;&#x5224;</el-checkbox>
        </el-form-item>
        <el-form-item label="&#x542F;&#x7528;"><el-switch v-model="ruleDialog.form.is_enabled" /></el-form-item>
        <el-form-item label="&#x8BF4;&#x660E;"><el-input v-model="ruleDialog.form.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleDialog.visible = false">&#x53D6;&#x6D88;</el-button>
        <el-button type="primary" @click="saveAlertRule">&#x4FDD;&#x5B58;</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="channelDialog.visible" title="&#x901A;&#x77E5;&#x6E20;&#x9053;" width="700px">
      <el-form :model="channelDialog.form" label-width="130px">
        <el-form-item label="&#x540D;&#x79F0;"><el-input v-model="channelDialog.form.name" /></el-form-item>
        <el-form-item label="&#x7C7B;&#x578B;">
          <el-select v-model="channelDialog.form.channel_type">
            <el-option v-for="item in channelOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="&#x901A;&#x77E5;&#x5730;&#x5740;"><el-input v-model="channelDialog.form.webhook_url" /></el-form-item>
        <el-form-item label="&#x8BBF;&#x95EE;&#x4EE4;&#x724C;"><el-input v-model="channelDialog.form.access_token" show-password /></el-form-item>
        <el-form-item v-if="channelDialog.form.channel_type === 'feishu'" label="签名密钥" required>
          <el-input v-model="channelDialog.form.secret" show-password placeholder="飞书机器人签名校验必填；编辑时留存掩码即可" />
        </el-form-item>
        <el-form-item label="&#x9ED8;&#x8BA4;&#x63A5;&#x6536;&#x5730;&#x5740;"><el-input v-model="channelDialog.form.to" placeholder="&#x591A;&#x4E2A;&#x63A5;&#x6536;&#x5730;&#x5740;&#x6216;&#x624B;&#x673A;&#x53F7;&#xFF0C;&#x4F7F;&#x7528;&#x82F1;&#x6587;&#x9017;&#x53F7;&#x5206;&#x9694;" /></el-form-item>
        <el-collapse class="channel-advanced">
          <el-collapse-item title="高级模板" name="template">
            <p class="field-help">默认直接使用告警标题和告警详情。仅在需要自定义格式时填写，支持 {title}、{level}、{service}、{resource}、{message}。</p>
            <el-form-item label="&#x6807;&#x9898;&#x6A21;&#x677F;"><el-input v-model="channelDialog.form.template_title" /></el-form-item>
            <el-form-item label="&#x5185;&#x5BB9;&#x6A21;&#x677F;"><el-input v-model="channelDialog.form.template_body" type="textarea" :rows="4" /></el-form-item>
          </el-collapse-item>
        </el-collapse>
        <el-form-item label="&#x6062;&#x590D;&#x901A;&#x77E5;"><el-switch v-model="channelDialog.form.send_resolved" /></el-form-item>
        <el-form-item label="&#x542F;&#x7528;"><el-switch v-model="channelDialog.form.is_enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="channelDialog.visible = false">&#x53D6;&#x6D88;</el-button>
        <el-button type="primary" @click="saveChannel">&#x4FDD;&#x5B58;</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="recipientDialog.visible" title="&#x63A5;&#x6536;&#x4EBA;" width="620px">
      <el-form :model="recipientDialog.form" label-width="120px">
        <el-form-item label="&#x59D3;&#x540D;"><el-input v-model="recipientDialog.form.name" /></el-form-item>
        <el-form-item label="接收渠道">
          <el-select v-model="recipientDialog.form.preferred_channels" multiple filterable placeholder="选择通知方式">
            <el-option v-for="item in channelOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="recipientDialog.form.preferred_channels.includes('sms') || recipientDialog.form.preferred_channels.includes('voice')" label="&#x624B;&#x673A;&#x53F7;"><el-input v-model="recipientDialog.form.phone" /></el-form-item>
        <el-form-item v-if="recipientDialog.form.preferred_channels.includes('email')" label="&#x90AE;&#x7BB1;"><el-input v-model="recipientDialog.form.email" /></el-form-item>
        <el-alert type="info" :closable="false" title="飞书、钉钉和企微使用已配置的机器人渠道，无需填写个人标识。" />
        <el-form-item label="&#x542F;&#x7528;"><el-switch v-model="recipientDialog.form.is_enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="recipientDialog.visible = false">&#x53D6;&#x6D88;</el-button>
        <el-button type="primary" @click="saveRecipient">&#x4FDD;&#x5B58;</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="recipientGroupDialog.visible" title="&#x63A5;&#x6536;&#x7EC4;" width="620px">
      <el-form :model="recipientGroupDialog.form" label-width="120px">
        <el-form-item label="&#x7EC4;&#x540D;"><el-input v-model="recipientGroupDialog.form.name" /></el-form-item>
        <el-form-item label="&#x63A5;&#x6536;&#x4EBA;">
          <el-select v-model="recipientGroupDialog.form.recipient_ids" multiple filterable>
            <el-option v-for="item in recipients" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="&#x5E73;&#x53F0;&#x7528;&#x6237;">
          <el-select v-model="recipientGroupDialog.form.user_ids" multiple filterable>
            <el-option v-for="item in users" :key="item.id" :label="item.display_name || item.username" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="&#x542F;&#x7528;"><el-switch v-model="recipientGroupDialog.form.is_enabled" /></el-form-item>
        <el-form-item label="&#x8BF4;&#x660E;"><el-input v-model="recipientGroupDialog.form.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="recipientGroupDialog.visible = false">&#x53D6;&#x6D88;</el-button>
        <el-button type="primary" @click="saveRecipientGroup">&#x4FDD;&#x5B58;</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="notificationRuleDialog.visible" title="&#x901A;&#x77E5;&#x89C4;&#x5219;" width="760px">
      <el-form :model="notificationRuleDialog.form" label-width="130px">
        <el-form-item label="&#x540D;&#x79F0;"><el-input v-model="notificationRuleDialog.form.name" /></el-form-item>
        <el-form-item label="&#x5339;&#x914D;&#x6761;&#x4EF6;"><MatcherEditor v-model="notificationRuleDialog.form.matchers" /></el-form-item>
        <el-form-item label="&#x6700;&#x4F4E;&#x7EA7;&#x522B;">
          <el-select v-model="notificationRuleDialog.form.min_level" clearable>
            <el-option label="&#x4E25;&#x91CD;" value="critical" />
            <el-option label="&#x8B66;&#x544A;" value="warning" />
            <el-option label="&#x4FE1;&#x606F;" value="info" />
          </el-select>
        </el-form-item>
        <el-form-item label="&#x901A;&#x77E5;&#x6E20;&#x9053;">
          <el-select v-model="notificationRuleDialog.form.channel_ids" multiple>
            <el-option v-for="item in channels" :key="item.id" :label="`${item.name} / ${channelText(item.channel_type)}`" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="&#x63A5;&#x6536;&#x7EC4;">
          <el-select v-model="notificationRuleDialog.form.recipient_group_ids" multiple>
            <el-option v-for="item in recipientGroups" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="&#x63A5;&#x6536;&#x4EBA;">
          <el-select v-model="notificationRuleDialog.form.recipient_ids" multiple>
            <el-option v-for="item in recipients" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="&#x805A;&#x5408;&#x89C4;&#x5219;">
          <el-select v-model="notificationRuleDialog.form.aggregation_rule" clearable>
            <el-option v-for="item in aggregationRules" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="&#x5347;&#x7EA7;&#x7B56;&#x7565;">
          <el-select v-model="notificationRuleDialog.form.escalation_policy" clearable>
            <el-option v-for="item in escalationPolicies" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="&#x901A;&#x77E5;&#x65F6;&#x673A;">
          <el-checkbox v-model="notificationRuleDialog.form.notify_on_fire">&#x89E6;&#x53D1;</el-checkbox>
          <el-checkbox v-model="notificationRuleDialog.form.notify_on_resolved">&#x6062;&#x590D;</el-checkbox>
          <el-checkbox v-model="notificationRuleDialog.form.notify_on_escalation">&#x5347;&#x7EA7;</el-checkbox>
        </el-form-item>
        <el-form-item label="&#x542F;&#x7528;"><el-switch v-model="notificationRuleDialog.form.is_enabled" /></el-form-item>
        <el-form-item label="&#x8BF4;&#x660E;"><el-input v-model="notificationRuleDialog.form.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="notificationRuleDialog.visible = false">&#x53D6;&#x6D88;</el-button>
        <el-button type="primary" @click="saveNotificationRule">&#x4FDD;&#x5B58;</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="policyDialog.visible" :title="policyDialog.title" width="760px">
      <el-form :model="policyDialog.form" label-width="130px">
        <el-form-item label="&#x540D;&#x79F0;"><el-input v-model="policyDialog.form.name" /></el-form-item>
        <el-form-item v-if="policyDialog.kind !== 'inhibition'" label="&#x5339;&#x914D;&#x6761;&#x4EF6;"><MatcherEditor v-model="policyDialog.form.matchers" /></el-form-item>

        <template v-if="policyDialog.kind === 'aggregation'">
          <el-form-item label="&#x5206;&#x7EC4;&#x7EF4;&#x5EA6;">
            <el-select v-model="policyDialog.form.group_by" multiple>
              <el-option v-for="item in dimensionOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="&#x805A;&#x5408;&#x7A97;&#x53E3;"><el-input-number v-model="policyDialog.form.window_minutes" :min="1" /> &#x5206;&#x949F;</el-form-item>
          <el-form-item label="&#x91CD;&#x590D;&#x95F4;&#x9694;"><el-input-number v-model="policyDialog.form.repeat_interval_minutes" :min="1" /> &#x5206;&#x949F;</el-form-item>
        </template>

        <template v-if="policyDialog.kind === 'inhibition'">
          <el-form-item label="&#x6765;&#x6E90;&#x5339;&#x914D;"><MatcherEditor v-model="policyDialog.form.source_matchers" /></el-form-item>
          <el-form-item label="&#x76EE;&#x6807;&#x5339;&#x914D;"><MatcherEditor v-model="policyDialog.form.target_matchers" /></el-form-item>
          <el-form-item label="&#x76F8;&#x7B49;&#x6807;&#x7B7E;">
            <el-select v-model="policyDialog.form.equal_labels" multiple allow-create filterable>
              <el-option v-for="item in dimensionOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="&#x6301;&#x7EED;&#x65F6;&#x95F4;"><el-input-number v-model="policyDialog.form.duration_minutes" :min="1" /> &#x5206;&#x949F;</el-form-item>
        </template>

        <template v-if="policyDialog.kind === 'mute'">
          <el-form-item label="&#x65F6;&#x95F4;&#x8303;&#x56F4;">
            <el-date-picker
              v-model="policyDialog.form.range"
              type="datetimerange"
              value-format="YYYY-MM-DDTHH:mm:ssZ"
              start-placeholder="&#x5F00;&#x59CB;&#x65F6;&#x95F4;"
              end-placeholder="&#x7ED3;&#x675F;&#x65F6;&#x95F4;"
            />
          </el-form-item>
          <el-form-item label="&#x539F;&#x56E0;"><el-input v-model="policyDialog.form.reason" /></el-form-item>
        </template>

        <template v-if="policyDialog.kind === 'escalation'">
          <el-form-item label="&#x91CD;&#x590D;&#x95F4;&#x9694;"><el-input-number v-model="policyDialog.form.repeat_interval_minutes" :min="1" /> &#x5206;&#x949F;</el-form-item>
          <el-form-item label="&#x5347;&#x7EA7;&#x5C42;&#x7EA7;">
            <div class="level-editor">
              <div v-for="(item, index) in policyDialog.form.levels" :key="index" class="level-row">
                <el-input-number v-model="item.after_minutes" :min="0" size="small" />
                <el-input v-model="item.name" size="small" placeholder="&#x5C42;&#x7EA7;&#x540D;&#x79F0;" />
                <el-select v-model="item.channel_ids" multiple size="small" placeholder="&#x901A;&#x77E5;&#x6E20;&#x9053;">
                  <el-option v-for="channel in channels" :key="channel.id" :label="channel.name" :value="channel.id" />
                </el-select>
                <el-button link type="danger" :icon="Delete" @click="policyDialog.form.levels.splice(index, 1)" />
              </div>
              <el-button size="small" :icon="Plus" @click="policyDialog.form.levels.push({ name: '', after_minutes: 30, channel_ids: [] })">&#x65B0;&#x589E;&#x5C42;&#x7EA7;</el-button>
            </div>
          </el-form-item>
        </template>

        <el-form-item label="&#x542F;&#x7528;"><el-switch v-model="policyDialog.form.is_enabled" /></el-form-item>
        <el-form-item label="&#x8BF4;&#x660E;"><el-input v-model="policyDialog.form.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="policyDialog.visible = false">&#x53D6;&#x6D88;</el-button>
        <el-button type="primary" @click="savePolicy">&#x4FDD;&#x5B58;</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="muteDialog.visible" title="&#x5C4F;&#x853D;&#x544A;&#x8B66;" width="420px">
      <el-form :model="muteDialog.form" label-width="96px">
        <el-form-item label="&#x5C4F;&#x853D;&#x65F6;&#x957F;">
          <el-input-number v-model="muteDialog.form.minutes" :min="1" :max="10080" />
          <span class="field-suffix">&#x5206;&#x949F;</span>
        </el-form-item>
        <el-form-item label="&#x5FEB;&#x6377;&#x9009;&#x62E9;">
          <div class="mute-presets">
            <el-button size="small" @click="muteDialog.form.minutes = 30">30m</el-button>
            <el-button size="small" @click="muteDialog.form.minutes = 60">1h</el-button>
            <el-button size="small" @click="muteDialog.form.minutes = 180">3h</el-button>
            <el-button size="small" @click="muteDialog.form.minutes = 1440">1d</el-button>
            <el-button size="small" @click="muteDialog.form.minutes = 10080">7d</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="muteDialog.visible = false">&#x53D6;&#x6D88;</el-button>
        <el-button type="primary" @click="submitMuteDialog">&#x786E;&#x8BA4;&#x5C4F;&#x853D;</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { Bell, Delete, Operation, Plus, Refresh, Search, Setting } from '@element-plus/icons-vue'
import { ElButton, ElInput, ElMessage, ElMessageBox, ElOption, ElPopconfirm, ElSelect, ElTable, ElTableColumn, ElTag } from 'element-plus'
import {
  analyzeAlert,
  claimAlert,
  closeAlert,
  createAlertAggregationRule,
  createAlertEscalationPolicy,
  createAlertInhibitionRule,
  createAlertMuteRule,
  createAlertNotificationChannel,
  createAlertNotificationRule,
  createAlertRecipient,
  createAlertRecipientGroup,
  createAlertRule,
  deleteAlert,
  deleteAlertAggregationRule,
  deleteAlertEscalationPolicy,
  deleteAlertInhibitionRule,
  deleteAlertMuteRule,
  deleteAlertNotificationChannel,
  deleteAlertNotificationRule,
  deleteAlertRecipient,
  deleteAlertRecipientGroup,
  deleteAlertRule,
  evaluateAlertRule,
  escalateAlert,
  getAlertAggregationRules,
  getAlertEscalationPolicies,
  getAlertGroups,
  getAlertAnalysis,
  getAlertLogEvidence,
  getAlertInhibitionRules,
  getAlertMuteRules,
  getAlertNotificationChannels,
  getAlertNotificationLogs,
  getAlertNotificationRules,
  getAlertRecipientGroups,
  getAlertRecipients,
  getAlertRules,
  getAlerts,
  getAlertSummary,
  getUsers,
  muteAlert,
  notifyAlert,
  reopenAlert,
  testAlertNotificationChannel,
  triggerAlertRule,
  unclaimAlert,
  updateAlertAggregationRule,
  updateAlertEscalationPolicy,
  updateAlertInhibitionRule,
  updateAlertMuteRule,
  updateAlertNotificationChannel,
  updateAlertNotificationRule,
  updateAlertRecipient,
  updateAlertRecipientGroup,
  updateAlertRule,
} from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'
import { useBusinessContextStore } from '@/stores/businessContext'
import ObservabilityRouteTabs from '@/components/observability/ObservabilityRouteTabs.vue'
import AlertRuleWizard from '@/components/observability/AlertRuleWizard.vue'

const props = defineProps({
  workspace: { type: String, default: 'events' },
})

const businessContextStore = useBusinessContextStore()
const { currentContext, currentContextId } = storeToRefs(businessContextStore)

function clone(value) {
  return JSON.parse(JSON.stringify(value || []))
}

function listOf(response) {
  return Array.isArray(response) ? response : (response?.results || [])
}

function splitText(value) {
  return String(value || '').split(',').map((item) => item.trim()).filter(Boolean)
}

function matchersToObject(rows) {
  const data = {}
  for (const row of rows || []) {
    if (row.key) data[row.key] = row.value
  }
  return data
}

function jsonText(value) {
  return JSON.stringify(value || {}, null, 2)
}

function metricOptionsFor(sourceType) {
  const options = metricProfiles.filter((item) => item.sources.includes(sourceType))
  return [...options, { value: 'legacy', label: '保留当前指标' }]
}

function metricKeyForQuery(query) {
  const normalized = String(query || '').replace(/\s+/g, '')
  const profile = metricProfiles.find((item) => item.query.replace(/\s+/g, '') === normalized)
  return profile?.value || 'legacy'
}

function isLogRule(form) {
  return form?.source_type === 'clickhouse' || form?.rule_kind === 'log'
}

function conditionFields(config = {}, condition = {}) {
  const levels = Array.isArray(condition.levels) ? condition.levels : []
  const levelCondition = levels.find((item) => item?.level === 'warning') || levels[0] || condition
  return {
    operator: levelCondition?.operator || levelCondition?.op || '>',
    threshold: Number(levelCondition?.threshold ?? levelCondition?.value ?? 0),
  }
}

function parseJsonText(value, label) {
  const raw = String(value || '').trim()
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    throw new Error(`${label} 不是有效 JSON`)
  }
}

function matcherRowsFromObject(obj) {
  return Object.entries(obj || {}).map(([key, value]) => ({ key, op: '==', value }))
}

const MatcherEditor = defineComponent({
  name: 'MatcherEditor',
  props: {
    modelValue: { type: Array, default: () => [] },
    mode: { type: String, default: 'matcher' },
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    const ops = ['==', '!=', '=~', '!~', 'in', 'not in', 'contains']
    function update(index, key, value) {
      const rows = clone(props.modelValue)
      rows[index] = { ...rows[index], [key]: value }
      emit('update:modelValue', rows)
    }
    function remove(index) {
      const rows = clone(props.modelValue)
      rows.splice(index, 1)
      emit('update:modelValue', rows)
    }
    function add() {
      emit('update:modelValue', [...props.modelValue, { key: '', op: '==', value: '' }])
    }
    return () => h('div', { class: 'matcher-editor' }, [
      ...props.modelValue.map((row, index) => h('div', { class: 'matcher-row', key: index }, [
        h(ElInput, { modelValue: row.key, size: 'small', placeholder: '\u5B57\u6BB5\u6216\u6807\u7B7E', onInput: (value) => update(index, 'key', value) }),
        props.mode === 'equals'
          ? null
          : h(ElSelect, { modelValue: row.op || '==', size: 'small', onChange: (value) => update(index, 'op', value) }, () => ops.map((op) => h(ElOption, { key: op, label: op, value: op }))),
        h(ElInput, { modelValue: row.value, size: 'small', placeholder: '\u5339\u914D\u503C', onInput: (value) => update(index, 'value', value) }),
        h(ElButton, { link: true, type: 'danger', icon: Delete, onClick: () => remove(index) }),
      ])),
      h(ElButton, { size: 'small', icon: Plus, onClick: add }, () => '\u65B0\u589E\u5339\u914D'),
    ])
  },
})

const PolicyTable = defineComponent({
  name: 'PolicyTable',
  props: {
    title: { type: String, required: true },
    data: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false },
    canManage: { type: Boolean, default: false },
  },
  emits: ['create', 'edit', 'remove'],
  setup(props, { emit }) {
    return () => h('div', [
      h('div', {
        class: 'section-head',
        style: {
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
          marginBottom: '8px',
          minHeight: '30px',
          width: '100%',
          flexWrap: 'nowrap',
        },
      }, [
        h('h3', {
          style: {
            margin: '0',
            fontSize: '15px',
            fontWeight: '700',
            lineHeight: '1.3',
            flex: '0 1 auto',
          },
        }, props.title),
        props.canManage ? h(ElButton, {
          size: 'small',
          type: 'primary',
          icon: Plus,
          onClick: () => emit('create'),
          style: {
            marginLeft: 'auto',
            flex: '0 0 auto',
          },
        }, () => '\u65B0\u589E\u7B56\u7565') : null,
      ]),
      h(ElTable, { data: props.data, stripe: true, size: 'small', loading: props.loading }, () => [
        h(ElTableColumn, { prop: 'name', label: '\u540D\u79F0', minWidth: 180 }),
        h(ElTableColumn, { prop: 'description', label: '\u8BF4\u660E', minWidth: 220, showOverflowTooltip: true }),
        h(ElTableColumn, { label: '\u72B6\u6001', width: 90 }, {
          default: ({ row }) => h(ElTag, { type: row.is_enabled ? 'success' : 'info', size: 'small' }, () => (row.is_enabled ? '\u542F\u7528' : '\u505C\u7528')),
        }),
        h(ElTableColumn, { prop: 'updated_at', label: '\u66F4\u65B0\u65F6\u95F4', width: 170 }, {
          default: ({ row }) => formatTime(row.updated_at),
        }),
        h(ElTableColumn, { label: '\u64CD\u4F5C', width: 140, fixed: 'right' }, {
          default: ({ row }) => h('div', { class: 'row-actions' }, [
            props.canManage ? h(ElButton, { link: true, size: 'small', onClick: () => emit('edit', row) }, () => '\u7F16\u8F91') : null,
            props.canManage ? h(ElPopconfirm, { title: '\u786E\u8BA4\u5220\u9664\u8BE5\u7B56\u7565\uFF1F', onConfirm: () => emit('remove', row.id) }, {
              reference: () => h(ElButton, { link: true, type: 'danger', size: 'small' }, () => '\u5220\u9664'),
            }) : null,
          ]),
        }),
      ]),
    ])
  },
})

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const isEventWorkspace = computed(() => props.workspace !== 'rules')
const pageTitle = computed(() => (isEventWorkspace.value ? '告警中心' : '告警规则'))
const pageDescription = computed(() => (isEventWorkspace.value
  ? '统一查看实时告警，支持筛选、认领、屏蔽和关联证据排查。'
  : '通过模板或手动配置创建规则，并维护规则的通知方式和接收对象。'))
const activeTab = ref(isEventWorkspace.value ? 'events' : 'rules')
const routeTabs = ['events', 'rules', 'notify', 'logs', 'policies']
const notifyTab = ref('rules')
const policyTab = ref('aggregation')
const eventMode = ref('group')
const eventModeOptions = [
  { label: '\u5217\u8868', value: 'list' },
  { label: '\u5206\u7EC4', value: 'group' },
]

const categoryOptions = [
  { label: '全部', value: '' },
  { label: '服务器', value: 'server' },
  { label: 'K8S', value: 'k8s' },
  { label: '存储', value: 'storage' },
  { label: '数据库', value: 'database' },
]

const providerOptions = [
  { label: '\u5E73\u53F0\u89C4\u5219', value: 'platform' },
]

const ruleSourceOptions = [
  { label: 'Prometheus \u6307\u6807', value: 'prometheus' },
  { label: 'ClickHouse \u65E5\u5FD7', value: 'clickhouse' },
  { label: 'K8S \u8D44\u6E90/\u4E8B\u4EF6', value: 'k8s' },
  { label: 'SLA', value: 'sla' },
  { label: '\u5E73\u53F0\u5185\u7F6E', value: 'platform' },
]

const metricProfiles = [
  { value: 'node-down', label: '主机离线', query: 'up{job=~".*node.*"} == 0', sources: ['prometheus'] },
  { value: 'host-cpu', label: '主机 CPU 使用率', query: '(1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) by (instance)) * 100', sources: ['prometheus'] },
  { value: 'host-memory', label: '主机内存使用率', query: '(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100', sources: ['prometheus'] },
  { value: 'host-disk', label: '主机磁盘使用率', query: '(1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"}) * 100', sources: ['prometheus'] },
  { value: 'host-load', label: '主机负载', query: 'node_load15 / count by(instance)(node_cpu_seconds_total{mode="idle"}) * 100', sources: ['prometheus'] },
  { value: 'k8s-node-not-ready', label: 'K8S 节点不可用数', query: 'sum(kube_node_status_condition{condition="Ready",status!="true"})', sources: ['k8s', 'prometheus'] },
  { value: 'k8s-abnormal-pods', label: 'K8S 异常 Pod 数', query: 'count(kube_pod_status_phase{phase=~"Pending|Failed|Unknown"} == 1)', sources: ['k8s', 'prometheus'] },
  { value: 'k8s-pod-restarts', label: 'Pod 重启次数', query: 'sum by(pod, namespace) (increase(kube_pod_container_status_restarts_total[15m]))', sources: ['k8s', 'prometheus'] },
  { value: 'k8s-pod-cpu', label: 'Pod CPU 使用率', query: 'sum(rate(container_cpu_usage_seconds_total{container!=""}[5m])) by (pod, namespace) / sum(container_spec_cpu_quota{container!=""} / 100000) by (pod,namespace) * 100', sources: ['k8s', 'prometheus'] },
  { value: 'k8s-pod-memory', label: 'Pod 内存使用率', query: 'sum(container_memory_working_set_bytes{container!=""}) by (pod, namespace) / sum(container_spec_memory_limit_bytes{container!=""}) by (pod,namespace) * 100', sources: ['k8s', 'prometheus'] },
  { value: 'k8s-pvc-usage', label: 'PVC 使用率', query: 'kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes * 100', sources: ['k8s', 'prometheus'] },
]

const logCollectionOptions = [
  { label: '容器日志', value: 'container-logs' },
  { label: 'K8S 事件', value: 'k8s-events' },
  { label: 'Ingress 访问日志', value: 'ingress-access' },
]

const logLevelOptions = ['DEBUG', 'INFO', 'WARN', 'WARNING', 'ERROR', 'FATAL', 'CRITICAL']

const channelOptions = [
  { label: '\u77ED\u4FE1', value: 'sms' },
  { label: '\u8BED\u97F3', value: 'voice' },
  { label: '\u90AE\u4EF6', value: 'email' },
  { label: '\u9489\u9489', value: 'dingtalk' },
  { label: '\u98DE\u4E66', value: 'feishu' },
  { label: '\u4F01\u5FAE', value: 'wecom' },
]

const dimensionOptions = [
  { label: '\u6765\u6E90\u7C7B\u578B', value: 'source_type' },
  { label: '\u73AF\u5883', value: 'environment' },
  { label: '\u670D\u52A1', value: 'service' },
  { label: '\u96C6\u7FA4', value: 'cluster' },
  { label: '\u547D\u540D\u7A7A\u95F4', value: 'namespace' },
  { label: '业务线', value: 'business_line' },
  { label: '\u8D44\u6E90\u7C7B\u578B', value: 'resource_type' },
  { label: '\u8D44\u6E90', value: 'resource' },
  { label: '\u7EA7\u522B', value: 'level' },
  { label: '\u5730\u57DF', value: 'region' },
  { label: '\u6807\u7B7E alertname', value: 'label.alertname' },
  { label: '\u6807\u7B7E team', value: 'label.team' },
]

const filters = reactive({
  search: '',
  level: '',
  status: '',
  claimed: '',
  source_type: '',
  environment: '',
})

const loading = ref(false)
const configLoading = ref(false)
const alerts = ref([])
const selectedAlerts = ref([])
const groups = ref([])
const summary = ref({})
const total = ref(0)
const page = ref(1)
const groupBy = ref(['source_type', 'environment', 'service'])
const alertRules = ref([])
const alertRulePresets = ref([])
const channels = ref([])
const recipients = ref([])
const recipientGroups = ref([])
const users = ref([])
const notificationRules = ref([])
const aggregationRules = ref([])
const inhibitionRules = ref([])
const muteRules = ref([])
const escalationPolicies = ref([])
const notificationLogs = ref([])
const ruleWizardVisible = ref(false)
const selectedAlert = ref(null)
const detailVisible = ref(false)
const alertLogEvidence = ref(null)
const alertLogEvidenceLoading = ref(false)
const alertAnalysis = ref(null)
const alertAnalysisLoading = ref(false)
const alertAnalysisSubmitting = ref(false)
const alertAnalysisUnavailable = ref(false)

const canViewAlerts = computed(() => authStore.hasPermission('ops.alert.view'))
const canManageAlerts = computed(() => authStore.hasPermission('ops.alert.manage'))
const canNotifyAlerts = computed(() => authStore.hasPermission('ops.alert.notify'))
const canViewConfig = computed(() => authStore.hasPermission('ops.alert.config.view'))
const canManageConfig = computed(() => authStore.hasPermission('ops.alert.config.manage'))

const statCards = computed(() => [
  { key: 'all', label: '\u5168\u90E8\u544A\u8B66', value: summary.value.total || 0, tone: 'base-card', filter: { status: '', level: '', claimed: '' } },
  { key: 'active', label: '\u6D3B\u8DC3\u544A\u8B66', value: summary.value.active || 0, tone: 'info-card', filter: { status: 'active', level: '', claimed: '' } },
  { key: 'critical', label: '\u4E25\u91CD\u544A\u8B66', value: summary.value.critical || 0, tone: 'danger-card', filter: { status: '', level: 'critical', claimed: '' } },
  { key: 'muted', label: '\u5DF2\u5C4F\u853D\u544A\u8B66', value: summary.value.muted || 0, tone: 'warning-card', filter: { status: 'muted', level: '', claimed: '' } },
])

const activeStatKey = computed(() => {
  const current = {
    status: filters.status || '',
    level: filters.level || '',
    claimed: filters.claimed || '',
  }
  return statCards.value.find((card) => (
    card.filter.status === current.status
    && card.filter.level === current.level
    && card.filter.claimed === current.claimed
  ))?.key || ''
})

const alertLogEvidenceLogs = computed(() => alertLogEvidence.value?.logs || [])
const alertAnalysisLatest = computed(() => {
  const payload = alertAnalysis.value
  if (payload?.latest) return payload.latest
  if (Array.isArray(payload?.results) && payload.results.length) return payload.results[0]
  if (payload && (payload.status || payload.root_cause || payload.summary)) return payload
  const rawAnalysis = selectedAlert.value?.raw_payload?.ai_analysis
  if (rawAnalysis && Object.keys(rawAnalysis).length) return rawAnalysis
  if (selectedAlert.value?.root_cause || selectedAlert.value?.suggestion) {
    return {
      status: 'completed',
      root_cause: selectedAlert.value.root_cause,
      suggestion: selectedAlert.value.suggestion,
    }
  }
  return null
})
const analysisEvidenceItems = computed(() => normalizeEvidence(alertAnalysisLatest.value?.evidence))
const analysisCandidates = computed(() => alertAnalysisLatest.value?.candidates || [])
const analysisSourceCoverageText = computed(() => {
  const coverage = alertAnalysisLatest.value?.evidence?.source_coverage || {}
  const labels = { metrics: '指标', k8s: 'K8S', logs: '日志', events: '事件', changes: '变更', topology: '拓扑' }
  const ready = Object.entries(coverage).filter(([, value]) => value).map(([key]) => labels[key] || key)
  return ready.length ? ready.join('、') : '暂无有效证据源'
})

const environmentOptions = computed(() => {
  const values = new Set()
  for (const item of alerts.value || []) {
    const env = String(item?.environment || '').trim()
    if (env) values.add(env)
  }
  const selected = String(filters.environment || '').trim()
  if (selected) values.add(selected)
  return Array.from(values).sort((a, b) => a.localeCompare(b, 'zh-CN'))
})

const ruleDialog = reactive({ visible: false, form: emptyAlertRule() })
const rulesCategoryFilter = ref('')
const muteDialog = reactive({ visible: false, target: null, form: { minutes: 60 } })
const channelDialog = reactive({ visible: false, form: emptyChannel() })
const recipientDialog = reactive({ visible: false, form: emptyRecipient() })
const recipientGroupDialog = reactive({ visible: false, form: emptyRecipientGroup() })
const notificationRuleDialog = reactive({ visible: false, form: emptyNotificationRule() })
const policyDialog = reactive({ visible: false, kind: 'aggregation', title: '', form: emptyAggregationRule() })

function levelType(level) {
  return { critical: 'danger', warning: 'warning', info: 'info' }[level] || 'info'
}

function logLevelType(level) {
  const normalized = String(level || '').toLowerCase()
  if (['fatal', 'critical', 'error'].includes(normalized)) return 'danger'
  if (['warn', 'warning'].includes(normalized)) return 'warning'
  if (['debug', 'trace'].includes(normalized)) return 'info'
  return 'info'
}

function levelText(level) {
  return { critical: '\u4E25\u91CD', warning: '\u8B66\u544A', info: '\u4FE1\u606F' }[level] || ''
}

function statusType(status) {
  return { active: 'danger', resolved: 'success', muted: 'warning', closed: 'info' }[status] || 'info'
}

function statusText(status) {
  return { active: '\u6D3B\u8DC3', resolved: '\u5DF2\u6062\u590D', muted: '\u5DF2\u5C4F\u853D', closed: '\u5DF2\u5173\u95ED' }[status] || status
}

function providerText(value) {
  return providerOptions.find((item) => item.value === value)?.label || value || '-'
}

const dimensionLabelMap = {
  source_type: '来源类型',
  environment: '环境',
  cluster: '集群',
  namespace: '命名空间',
  service: '服务',
  business_line: '业务线',
  resource_type: '资源类型',
  resource: '资源',
  level: '级别',
  region: '地域',
}

const dimensionValueMap = {
  platform: '平台告警规则',
  prometheus: 'Prometheus 指标',
  clickhouse: 'ClickHouse 日志',
  k8s: 'K8S 资源',
  critical: '严重',
  warning: '警告',
  info: '信息',
}

function groupDimensionEntries(row) {
  const dimensions = row?.dimensions
  if (!dimensions || typeof dimensions !== 'object' || Array.isArray(dimensions)) return []
  return Object.entries(dimensions).map(([key, value]) => ({
    key,
    label: dimensionLabelMap[key] || (key.startsWith('label.') ? `标签 ${key.slice(6)}` : key),
    value: dimensionValueMap[String(value)] || value || '未设置',
  }))
}

function analysisStatusText(value) {
  return { pending: '等待研判', running: '研判中', completed: '已完成', partial: '部分完成', failed: '研判失败', disabled: '未启用' }[value] || value || '未知'
}

function analysisStatusType(value) {
  return { completed: 'success', partial: 'warning', failed: 'danger', disabled: 'info' }[value] || 'primary'
}

function analysisConfidenceText(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return value || '未评估'
  return `${Math.round(number <= 1 ? number * 100 : number)}%`
}

function analysisSuggestionText(analysis) {
  const value = analysis?.suggestions || analysis?.suggested_actions || analysis?.suggestion
  if (Array.isArray(value)) {
    return value.map((item) => (typeof item === 'object' ? item.content || item.summary || item.action : item)).filter(Boolean).join('；') || '-'
  }
  return value || '-'
}

function normalizeEvidence(evidence) {
  if (!evidence) return []
  if (!Array.isArray(evidence) && typeof evidence === 'object') {
    const summaries = []
    const metrics = evidence.metrics || evidence.metric
    const logs = evidence.logs || evidence.log
    const graph = evidence.knowledge_graph || evidence.graph
    const k8s = evidence.k8s
    if (metrics?.summary || metrics?.message) summaries.push(metrics.summary || metrics.message)
    if (logs && typeof logs === 'object') summaries.push(`关联日志状态 ${logs.status || '未知'}，命中 ${logs.sample_count || logs.count || 0} 条样本`)
    if (graph?.summary || graph?.message) summaries.push(graph.summary || graph.message)
    if (k8s?.summary) summaries.push(`K8S：${k8s.summary.ready_nodes || 0}/${k8s.summary.node_count || 0} 个节点 Ready，${k8s.summary.pod_count || 0} 个 Pod`)
    for (const item of evidence.k8s_findings || []) summaries.push(`${item.target || 'K8S'}：${item.message || item.code}`)
    for (const item of evidence.metric_anomalies || []) summaries.push(`${item.title || item.code}：${item.anomaly?.vote_count || 0} 个算法判定异常`)
    for (const item of evidence.diagnostics || []) {
      const text = typeof item === 'object' ? item.message || item.summary : item
      if (text) summaries.push(text)
    }
    if (summaries.length) return summaries.slice(0, 8)
  }
  const source = Array.isArray(evidence)
    ? evidence
    : (evidence.items || evidence.key_evidence || evidence.results || (evidence.summary ? [evidence.summary] : []))
  if (Array.isArray(source)) {
    return source.slice(0, 8).map((item) => {
      if (typeof item !== 'object') return String(item)
      return item.summary || item.message || item.content || item.fact || item.description || ''
    }).filter(Boolean)
  }
  return Object.entries(evidence).slice(0, 8).map(([key, value]) => {
    const text = typeof value === 'object' ? JSON.stringify(value) : String(value)
    return `${key}：${text.length > 240 ? `${text.slice(0, 240)}...` : text}`
  })
}

function categoryText(value) {
  return categoryOptions.find((item) => item.value === value)?.label || value || '-'
}

function ruleSourceText(value) {
  return ruleSourceOptions.find((item) => item.value === value)?.label || value || '-'
}

function channelText(value) {
  return channelOptions.find((item) => item.value === value)?.label || value || '-'
}

function notifyStatusType(value) {
  return { success: 'success', skipped: 'info', error: 'danger' }[value] || 'info'
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
}

function groupMembers(row) {
  const names = (row.recipients || []).map((item) => item.name)
  const platformUsers = (row.users || []).map((item) => item.display_name || item.username)
  return [...names, ...platformUsers].join('\u3001') || '-'
}

function buildAlertParams() {
  const params = { page: page.value }
  if (currentContextId.value) params.knowledge_environment_id = currentContextId.value
  if (filters.search) params.search = filters.search
  if (filters.level) params.level = filters.level
  if (filters.status) params.status = filters.status
  if (filters.claimed) params.claimed = filters.claimed
  if (filters.source_type) params.source_type = filters.source_type
  if (filters.environment) params.environment = filters.environment
  return params
}

async function fetchAlerts() {
  loading.value = true
  try {
    const response = await getAlerts(buildAlertParams())
    alerts.value = listOf(response)
    selectedAlerts.value = []
    total.value = response?.count || alerts.value.length
  } finally {
    loading.value = false
  }
}

async function fetchSummary() {
  summary.value = await getAlertSummary(buildAlertParams())
}

async function fetchGroups() {
  if (eventMode.value !== 'group') return
  loading.value = true
  try {
    groups.value = await getAlertGroups({ ...buildAlertParams(), group_by: groupBy.value.join(',') })
  } finally {
    loading.value = false
  }
}

async function refreshEvents() {
  if (!currentContextId.value) {
    alerts.value = []
    groups.value = []
    summary.value = {}
    total.value = 0
    selectedAlerts.value = []
    return
  }
  const tasks = [fetchSummary()]
  if (eventMode.value === 'group') tasks.push(fetchGroups())
  else tasks.push(fetchAlerts())
  await Promise.all(tasks)
}

function handleFilterChange() {
  page.value = 1
  refreshEvents()
}

async function applyStatFilter(card) {
  const shouldClear = activeStatKey.value === card.key
  filters.status = shouldClear ? '' : card.filter.status
  filters.level = shouldClear ? '' : card.filter.level
  filters.claimed = shouldClear ? '' : card.filter.claimed
  activeTab.value = 'events'
  eventMode.value = 'list'
  page.value = 1
  await refreshEvents()
}

function openGroup(row) {
  eventMode.value = 'list'
  filters.search = row.sample_title || ''
  page.value = 1
  refreshEvents()
}

async function fetchAlertLogEvidence(row) {
  alertLogEvidence.value = null
  if (!row?.id || !canViewAlerts.value) return
  const alertId = row.id
  alertLogEvidenceLoading.value = true
  try {
    const payload = await getAlertLogEvidence(alertId, { limit: 8 })
    if (selectedAlert.value?.id === alertId) {
      alertLogEvidence.value = payload
    }
  } catch (error) {
    if (selectedAlert.value?.id === alertId) {
      alertLogEvidence.value = {
        summary: {
          count: 0,
          error: error?.response?.data?.detail || error?.response?.data?.error || error?.message || '日志证据查询失败',
        },
        logs: [],
      }
    }
  } finally {
    if (selectedAlert.value?.id === alertId) {
      alertLogEvidenceLoading.value = false
    }
  }
}

async function fetchAlertAnalysis(row) {
  alertAnalysis.value = null
  alertAnalysisUnavailable.value = false
  if (!row?.id || !canViewAlerts.value) return
  const alertId = row.id
  alertAnalysisLoading.value = true
  try {
    const payload = await getAlertAnalysis(alertId)
    if (selectedAlert.value?.id === alertId) alertAnalysis.value = payload
  } catch (error) {
    if (selectedAlert.value?.id === alertId) {
      alertAnalysisUnavailable.value = error?.response?.status === 404 || error?.response?.status === 405
    }
  } finally {
    if (selectedAlert.value?.id === alertId) alertAnalysisLoading.value = false
  }
}

async function submitAlertAnalysis() {
  if (!selectedAlert.value?.id) return
  alertAnalysisSubmitting.value = true
  try {
    const payload = await analyzeAlert(selectedAlert.value.id, { force: true })
    alertAnalysis.value = payload
    alertAnalysisUnavailable.value = false
    ElMessage.success('智能研判任务已提交')
    await fetchAlertAnalysis(selectedAlert.value)
  } catch (error) {
    if ([404, 405].includes(error?.response?.status)) alertAnalysisUnavailable.value = true
    ElMessage.error(error?.response?.data?.detail || '智能研判任务提交失败')
  } finally {
    alertAnalysisSubmitting.value = false
  }
}

function openDetail(row) {
  selectedAlert.value = row
  detailVisible.value = true
  fetchAlertLogEvidence(row)
  fetchAlertAnalysis(row)
}

function handleSelectionChange(rows) {
  selectedAlerts.value = rows || []
}

async function runAlertAction(row, action) {
  const actionMap = {
    claim: () => claimAlert(row.id),
    unclaim: () => unclaimAlert(row.id),
    mute: () => muteAlert(row.id, { minutes: 60 }),
    escalate: () => escalateAlert(row.id),
    close: () => closeAlert(row.id),
    reopen: () => reopenAlert(row.id),
    notify: () => notifyAlert(row.id, { action: row.status === 'resolved' ? 'resolved' : 'fire' }),
  }
  await actionMap[action]?.()
  ElMessage.success('\u64CD\u4F5C\u5DF2\u63D0\u4EA4')
  detailVisible.value = false
  await refreshAll()
}

function openMuteDialog(row) {
  muteDialog.target = row
  muteDialog.form.minutes = 60
  muteDialog.visible = true
}

async function submitMuteDialog() {
  if (!muteDialog.target?.id) return
  await muteAlert(muteDialog.target.id, { minutes: Number(muteDialog.form.minutes || 60) })
  muteDialog.visible = false
  ElMessage.success('\u64CD\u4F5C\u5DF2\u63D0\u4EA4')
  detailVisible.value = false
  await refreshAll()
}

async function handleRowCommand(command, row) {
  if (command === 'delete') {
    await deleteAlert(row.id)
    ElMessage.success('\u544A\u8B66\u5DF2\u5220\u9664')
    await refreshAll()
    return
  }
  await runAlertAction(row, command)
}

async function handleBatchDelete() {
  if (!selectedAlerts.value.length) return
  await ElMessageBox.confirm(`确认删除已选中的 ${selectedAlerts.value.length} 条告警？`, '批量删除', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await Promise.all(selectedAlerts.value.map((item) => deleteAlert(item.id)))
  selectedAlerts.value = []
  ElMessage.success('\u5DF2\u5220\u9664\u9009\u4E2D\u544A\u8B66')
  await refreshAll()
}

function ensureTabAccess() {
  const tabs = []
  if (isEventWorkspace.value && canViewAlerts.value) tabs.push('events')
  if (!isEventWorkspace.value && canViewConfig.value) tabs.push('rules', 'notify')
  if (!tabs.includes(activeTab.value)) activeTab.value = tabs[0] || (isEventWorkspace.value ? 'events' : 'rules')
}

async function switchTab(tab) {
  activeTab.value = tab
  await refreshAll()
}

function applyRouteTab() {
  const tab = typeof route.query.tab === 'string' ? route.query.tab.trim() : ''
  const allowedTabs = isEventWorkspace.value ? ['events'] : ['rules', 'notify']
  if (routeTabs.includes(tab) && allowedTabs.includes(tab)) activeTab.value = tab
}

async function changeNotifyTab(tab) {
  notifyTab.value = tab
  await loadNotifyTab()
}

async function changePolicyTab(tab) {
  policyTab.value = tab
  await loadPolicyTab()
}

async function loadNotifyTab() {
  if (!canViewConfig.value) return
  configLoading.value = true
  try {
    if (notifyTab.value === 'rules') {
      const [rules, channelList, recipientList, groupList, aggregationList, escalationList] = await Promise.all([
        getAlertNotificationRules(),
        getAlertNotificationChannels(),
        getAlertRecipients(),
        getAlertRecipientGroups(),
        getAlertAggregationRules(),
        getAlertEscalationPolicies(),
      ])
      notificationRules.value = listOf(rules)
      channels.value = listOf(channelList)
      recipients.value = listOf(recipientList)
      recipientGroups.value = listOf(groupList)
      aggregationRules.value = listOf(aggregationList)
      escalationPolicies.value = listOf(escalationList)
    } else if (notifyTab.value === 'channels') {
      channels.value = listOf(await getAlertNotificationChannels())
    } else {
      const [recipientList, groupList, userList] = await Promise.all([
        getAlertRecipients(),
        getAlertRecipientGroups(),
        getUsers(),
      ])
      recipients.value = listOf(recipientList)
      recipientGroups.value = listOf(groupList)
      users.value = listOf(userList)
    }
  } finally {
    configLoading.value = false
  }
}

async function loadPolicyTab() {
  if (!canViewConfig.value) return
  configLoading.value = true
  try {
    if (policyTab.value === 'aggregation') {
      aggregationRules.value = listOf(await getAlertAggregationRules())
    } else if (policyTab.value === 'inhibition') {
      inhibitionRules.value = listOf(await getAlertInhibitionRules())
    } else if (policyTab.value === 'mute') {
      muteRules.value = listOf(await getAlertMuteRules())
    } else {
      const [policyList, channelList] = await Promise.all([
        getAlertEscalationPolicies(),
        getAlertNotificationChannels(),
      ])
      escalationPolicies.value = listOf(policyList)
      channels.value = listOf(channelList)
    }
  } finally {
    configLoading.value = false
  }
}

async function fetchAlertRules() {
  configLoading.value = true
  try {
    const params = {}
    if (rulesCategoryFilter.value) params.category = rulesCategoryFilter.value
    if (currentContext.value?.metric_datasource) params.metric_datasource_id = currentContext.value.metric_datasource
    const [ruleList, presetList] = await Promise.all([getAlertRules(params), getAlertRules({ page_size: 200 })])
    alertRules.value = listOf(ruleList)
    alertRulePresets.value = listOf(presetList).filter((item) => item.source && item.source !== 'custom')
  } finally {
    configLoading.value = false
  }
}

async function fetchNotificationLogs() {
  configLoading.value = true
  try {
    notificationLogs.value = listOf(await getAlertNotificationLogs())
  } finally {
    configLoading.value = false
  }
}

async function refreshAll() {
  ensureTabAccess()
  if (activeTab.value === 'events' && canViewAlerts.value) await refreshEvents()
  if (activeTab.value === 'rules' && canViewConfig.value) {
    await fetchAlertRules()
  }
  if (activeTab.value === 'notify' && canViewConfig.value) await loadNotifyTab()
  if (activeTab.value === 'policies' && canViewConfig.value) await loadPolicyTab()
  if (activeTab.value === 'logs' && canViewAlerts.value) await fetchNotificationLogs()
}

function emptyAlertRule() {
  return {
    id: null,
    name: '',
    code: '',
    category: '',
    source_type: 'k8s',
    rule_kind: 'metric',
    level: 'warning',
    query_config: {},
    condition: {},
    metric_key: 'k8s-node-not-ready',
    metric_query: '',
    custom_query_enabled: false,
    custom_query: '',
    log_collection: 'container-logs',
    log_levels: ['ERROR'],
    window_minutes: 5,
    log_group_by: '',
    keyword: '',
    operator: '>',
    threshold: 0,
    label_rows: [],
    annotation_rows: [],
    interval_seconds: 60,
    duration_seconds: 0,
    notify_enabled: true,
    auto_analyze: true,
    is_enabled: true,
    description: '',
  }
}

function openAlertRule(row = null) {
  const config = row?.query_config || {}
  const condition = row?.condition || {}
  const query = config.promql || config.query || config.metric || ''
  const fields = conditionFields(config, condition)
  ruleDialog.form = row ? {
    ...emptyAlertRule(),
    ...row,
    query_config: config,
    condition,
    rule_kind: row.source_type === 'clickhouse' || (row.source_type === 'k8s' && Boolean(config.collection) && !query) ? 'log' : 'metric',
    metric_key: metricKeyForQuery(query),
    metric_query: query,
    custom_query_enabled: metricKeyForQuery(query) === 'legacy' && Boolean(query),
    custom_query: query,
    log_collection: config.collection || 'container-logs',
    log_levels: Array.isArray(config.levels) ? config.levels : (Array.isArray(config.level) ? config.level : [config.level || condition.level || 'ERROR'].filter(Boolean)),
    window_minutes: Number(config.window_minutes || config.window || condition.window_minutes || 5),
    log_group_by: config.group_by || condition.group_by || '',
    keyword: condition.keyword || config.keyword || '',
    ...fields,
    label_rows: matcherRowsFromObject(row.labels),
    annotation_rows: matcherRowsFromObject(row.annotations),
  } : emptyAlertRule()
  ruleDialog.visible = true
}

function openWizardForSource() {
  ruleWizardVisible.value = true
}

async function saveWizardRule(data) {
  try {
    await createAlertRule(data)
    ElMessage.success('告警规则已保存')
    await fetchAlertRules()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '告警规则保存失败')
  }
}

function buildAlertRulePayload(form) {
  const selectedMetric = metricProfiles.find((item) => item.value === form.metric_key)
  const query = form.custom_query_enabled ? form.custom_query.trim() : (selectedMetric?.query || form.metric_query)
  if (!isLogRule(form) && !query) throw new Error('请选择监控指标或填写自定义 PromQL 查询')
  const query_config = isLogRule(form)
    ? {
        collection: form.log_collection,
        levels: form.log_levels || [],
        window_minutes: form.window_minutes,
        ...(form.log_group_by ? { group_by: form.log_group_by } : {}),
      }
    : { query }
  const condition = {
    operator: form.operator,
    threshold: form.threshold,
    ...(isLogRule(form) && form.keyword ? { keyword: form.keyword } : {}),
  }
  const data = {
    ...form,
    source: form.id ? form.source : 'custom',
    query_config,
    condition,
    labels: matchersToObject(form.label_rows),
    annotations: matchersToObject(form.annotation_rows),
  }
  delete data.metric_key
  delete data.rule_kind
  delete data.metric_query
  delete data.custom_query_enabled
  delete data.custom_query
  delete data.log_collection
  delete data.log_levels
  delete data.window_minutes
  delete data.log_group_by
  delete data.keyword
  delete data.operator
  delete data.threshold
  delete data.label_rows
  delete data.annotation_rows
  return data
}

async function saveAlertRule() {
  try {
    const data = buildAlertRulePayload(ruleDialog.form)
    if (data.id) await updateAlertRule(data.id, data)
    else await createAlertRule(data)
    ruleDialog.visible = false
    ElMessage.success('\u544A\u8B66\u89C4\u5219\u5DF2\u4FDD\u5B58')
    await fetchAlertRules()
  } catch (error) {
    ElMessage.error(error.message || '\u544A\u8B66\u89C4\u5219\u4FDD\u5B58\u5931\u8D25')
  }
}

async function removeAlertRule(id) {
  await deleteAlertRule(id)
  ElMessage.success('\u544A\u8B66\u89C4\u5219\u5DF2\u5220\u9664')
  await fetchAlertRules()
}

async function dryRunAlertRule(row) {
  const result = await evaluateAlertRule(row.id, { dry_run: true })
  const lines = [
    `规则：${row.name}`,
    `匹配结果：${result.matched_count || 0}`,
    `预计触发：${result.would_fire_count || 0}`,
  ]
  if (result.error) lines.push(`错误：${result.error}`)
  await ElMessageBox.alert(lines.join('\n'), '规则试运行', {
    confirmButtonText: '知道了',
  })
}

async function testAlertRule(row) {
  await ElMessageBox.confirm('\u624B\u52A8\u89E6\u53D1\u4F1A\u751F\u6210\u4E00\u6761\u544A\u8B66\u4E8B\u4EF6\uFF0C\u786E\u8BA4\u7EE7\u7EED\uFF1F', '\u624B\u52A8\u89E6\u53D1', {
    type: 'warning',
    confirmButtonText: '\u89E6\u53D1',
    cancelButtonText: '\u53D6\u6D88',
  })
  await triggerAlertRule(row.id, {
    title: row.name,
    message: row.description || row.name,
    labels: row.labels || {},
    resource_type: row.source_type,
    resource: row.code,
    evidence: { manual: true },
  })
  ElMessage.success('\u544A\u8B66\u89C4\u5219\u5DF2\u89E6\u53D1')
  await refreshAll()
}

function emptyChannel() {
  return { id: null, name: '', channel_type: 'dingtalk', webhook_url: '', access_token: '', secret: '', to: '', template_title: '', template_body: '', send_resolved: true, is_enabled: true, timeout_seconds: 8 }
}

function openChannel(row = null) {
  if (row) {
    const config = row.config || {}
    const configTo = config.to || config.phones || []
    channelDialog.form = {
      ...emptyChannel(),
      ...row,
      webhook_url: config.webhook_url || config.url || '',
      access_token: config.access_token || config.token || '',
      secret: config.secret || config.sign_secret || '',
      to: Array.isArray(configTo) ? configTo.join(',') : String(configTo || ''),
    }
  } else {
    channelDialog.form = emptyChannel()
  }
  channelDialog.visible = true
}

async function saveChannel() {
  const data = { ...channelDialog.form }
  if (data.channel_type === 'feishu' && !data.secret) {
    return ElMessage.warning('飞书渠道必须填写签名密钥')
  }
  const recipientsText = splitText(data.to)
  data.config = {
    ...(data.webhook_url ? { webhook_url: data.webhook_url } : {}),
    ...(data.access_token ? { access_token: data.access_token } : {}),
    ...(data.channel_type === 'feishu' && data.secret ? { secret: data.secret } : {}),
    ...(data.channel_type === 'email' ? { to: recipientsText } : {}),
    ...((data.channel_type === 'sms' || data.channel_type === 'voice') ? { phones: recipientsText } : {}),
  }
  delete data.webhook_url
  delete data.access_token
  delete data.secret
  delete data.to
  if (data.id) await updateAlertNotificationChannel(data.id, data)
  else await createAlertNotificationChannel(data)
  channelDialog.visible = false
  ElMessage.success('\u901A\u77E5\u6E20\u9053\u5DF2\u4FDD\u5B58')
  await loadNotifyTab()
}

async function removeChannel(id) {
  await deleteAlertNotificationChannel(id)
  ElMessage.success('\u901A\u77E5\u6E20\u9053\u5DF2\u5220\u9664')
  await loadNotifyTab()
}

async function testChannel(row) {
  const result = listOf(await testAlertNotificationChannel(row.id))
  const log = result[0] || {}
  if (log.status === 'success') {
    ElMessage.success('测试通知发送成功')
  } else {
    await ElMessageBox.alert(
      [
        `状态：${log.status_display || log.status || '-'}`,
        `错误：${log.error_message || '-'}`,
        `响应：${log.response_body || '-'}`,
      ].join('\n'),
      '测试通知结果',
      { confirmButtonText: '知道了' },
    )
  }
  await fetchNotificationLogs()
}

function emptyRecipient() {
  return { id: null, name: '', preferred_channels: [], phone: '', email: '', is_enabled: true }
}

function openRecipient(row = null) {
  recipientDialog.form = row
    ? { ...emptyRecipient(), ...row, preferred_channels: row.preferred_channels?.length ? [...row.preferred_channels] : [...(row.contact_channels || [])] }
    : emptyRecipient()
  recipientDialog.visible = true
}

async function saveRecipient() {
  const data = { ...recipientDialog.form }
  if (!data.name?.trim()) return ElMessage.warning('请输入接收人姓名')
  if (!data.preferred_channels?.length) return ElMessage.warning('请选择至少一个接收渠道')
  if (data.preferred_channels.includes('email') && !data.email?.trim()) return ElMessage.warning('邮件渠道需要填写邮箱')
  if ((data.preferred_channels.includes('sms') || data.preferred_channels.includes('voice')) && !data.phone?.trim()) return ElMessage.warning('短信或语音渠道需要填写手机号')
  if (data.id) await updateAlertRecipient(data.id, data)
  else await createAlertRecipient(data)
  recipientDialog.visible = false
  ElMessage.success('\u63A5\u6536\u4EBA\u5DF2\u4FDD\u5B58')
  await loadNotifyTab()
}

async function removeRecipient(id) {
  await deleteAlertRecipient(id)
  ElMessage.success('\u63A5\u6536\u4EBA\u5DF2\u5220\u9664')
  await loadNotifyTab()
}

function emptyRecipientGroup() {
  return { id: null, name: '', recipient_ids: [], user_ids: [], is_enabled: true, description: '' }
}

function openRecipientGroup(row = null) {
  recipientGroupDialog.form = row
    ? {
        ...emptyRecipientGroup(),
        ...row,
        recipient_ids: (row.recipients || []).map((item) => item.id),
        user_ids: (row.users || []).map((item) => item.id),
      }
    : emptyRecipientGroup()
  recipientGroupDialog.visible = true
}

async function saveRecipientGroup() {
  const data = { ...recipientGroupDialog.form }
  if (data.id) await updateAlertRecipientGroup(data.id, data)
  else await createAlertRecipientGroup(data)
  recipientGroupDialog.visible = false
  ElMessage.success('\u63A5\u6536\u7EC4\u5DF2\u4FDD\u5B58')
  await loadNotifyTab()
}

async function removeRecipientGroup(id) {
  await deleteAlertRecipientGroup(id)
  ElMessage.success('\u63A5\u6536\u7EC4\u5DF2\u5220\u9664')
  await loadNotifyTab()
}

function emptyNotificationRule() {
  return {
    id: null,
    name: '',
    matchers: [],
    min_level: '',
    channel_ids: [],
    recipient_ids: [],
    recipient_group_ids: [],
    aggregation_rule: null,
    escalation_policy: null,
    notify_on_fire: true,
    notify_on_resolved: true,
    notify_on_escalation: true,
    is_enabled: true,
    description: '',
  }
}

function openNotificationRule(row = null) {
  notificationRuleDialog.form = row
    ? {
        ...emptyNotificationRule(),
        ...row,
        channel_ids: (row.channels || []).map((item) => item.id),
        recipient_ids: (row.recipients || []).map((item) => item.id),
        recipient_group_ids: (row.recipient_groups || []).map((item) => item.id),
        matchers: clone(row.matchers || []),
      }
    : emptyNotificationRule()
  notificationRuleDialog.visible = true
}

async function saveNotificationRule() {
  const data = { ...notificationRuleDialog.form }
  if (data.id) await updateAlertNotificationRule(data.id, data)
  else await createAlertNotificationRule(data)
  notificationRuleDialog.visible = false
  ElMessage.success('\u901A\u77E5\u89C4\u5219\u5DF2\u4FDD\u5B58')
  await loadNotifyTab()
}

async function removeNotificationRule(id) {
  await deleteAlertNotificationRule(id)
  ElMessage.success('\u901A\u77E5\u89C4\u5219\u5DF2\u5220\u9664')
  await loadNotifyTab()
}

function emptyAggregationRule() {
  return { id: null, name: '', matchers: [], group_by: ['source_type', 'environment', 'service'], window_minutes: 5, repeat_interval_minutes: 30, is_enabled: true, description: '' }
}

function emptyInhibitionRule() {
  return { id: null, name: '', source_matchers: [], target_matchers: [], equal_labels: ['service', 'resource'], duration_minutes: 60, is_enabled: true, description: '' }
}

function emptyMuteRule() {
  return { id: null, name: '', matchers: [], range: [], starts_at: null, ends_at: null, reason: '', is_enabled: true, description: '' }
}

function emptyEscalationPolicy() {
  return { id: null, name: '', matchers: [], levels: [{ name: '\u4E00\u7EA7\u5347\u7EA7', after_minutes: 30, channel_ids: [] }], repeat_interval_minutes: 30, is_enabled: true, description: '' }
}

function openAggregationRule(row = null) {
  policyDialog.kind = 'aggregation'
  policyDialog.title = '\u805A\u5408\u89C4\u5219'
  policyDialog.form = row ? { ...emptyAggregationRule(), ...row, matchers: clone(row.matchers), group_by: clone(row.group_by) } : emptyAggregationRule()
  policyDialog.visible = true
}

function openInhibitionRule(row = null) {
  policyDialog.kind = 'inhibition'
  policyDialog.title = '\u6291\u5236\u89C4\u5219'
  policyDialog.form = row ? { ...emptyInhibitionRule(), ...row, source_matchers: clone(row.source_matchers), target_matchers: clone(row.target_matchers), equal_labels: clone(row.equal_labels) } : emptyInhibitionRule()
  policyDialog.visible = true
}

function openMuteRule(row = null) {
  policyDialog.kind = 'mute'
  policyDialog.title = '\u5C4F\u853D\u89C4\u5219'
  policyDialog.form = row ? { ...emptyMuteRule(), ...row, matchers: clone(row.matchers), range: row.starts_at && row.ends_at ? [row.starts_at, row.ends_at] : [] } : emptyMuteRule()
  policyDialog.visible = true
}

function openEscalationPolicy(row = null) {
  policyDialog.kind = 'escalation'
  policyDialog.title = '\u5347\u7EA7\u7B56\u7565'
  policyDialog.form = row ? { ...emptyEscalationPolicy(), ...row, matchers: clone(row.matchers), levels: clone(row.levels || []) } : emptyEscalationPolicy()
  policyDialog.visible = true
}

async function savePolicy() {
  const data = { ...policyDialog.form }
  if (policyDialog.kind === 'mute') {
    data.starts_at = data.range?.[0] || null
    data.ends_at = data.range?.[1] || null
  }
  const actionMap = {
    aggregation: [createAlertAggregationRule, updateAlertAggregationRule, loadPolicyTab],
    inhibition: [createAlertInhibitionRule, updateAlertInhibitionRule, loadPolicyTab],
    mute: [createAlertMuteRule, updateAlertMuteRule, loadPolicyTab],
    escalation: [createAlertEscalationPolicy, updateAlertEscalationPolicy, loadPolicyTab],
  }
  const [createFn, updateFn, refreshFn] = actionMap[policyDialog.kind]
  if (data.id) await updateFn(data.id, data)
  else await createFn(data)
  policyDialog.visible = false
  ElMessage.success('\u7B56\u7565\u5DF2\u4FDD\u5B58')
  await refreshFn()
}

async function removeAggregationRule(id) {
  await deleteAlertAggregationRule(id)
  ElMessage.success('\u805A\u5408\u89C4\u5219\u5DF2\u5220\u9664')
  await loadPolicyTab()
}

async function removeInhibitionRule(id) {
  await deleteAlertInhibitionRule(id)
  ElMessage.success('\u6291\u5236\u89C4\u5219\u5DF2\u5220\u9664')
  await loadPolicyTab()
}

async function removeMuteRule(id) {
  await deleteAlertMuteRule(id)
  ElMessage.success('\u5C4F\u853D\u89C4\u5219\u5DF2\u5220\u9664')
  await loadPolicyTab()
}

async function removeEscalationPolicy(id) {
  await deleteAlertEscalationPolicy(id)
  ElMessage.success('\u5347\u7EA7\u7B56\u7565\u5DF2\u5220\u9664')
  await loadPolicyTab()
}

function applyRouteFilters() {
  applyRouteTab()
  filters.search = typeof route.query.search === 'string' ? route.query.search.trim() : ''
  filters.level = typeof route.query.level === 'string' ? route.query.level.trim() : ''
  if (route.query.claimed === '0' || route.query.ack === '0') filters.claimed = '0'
  else if (route.query.claimed === '1' || route.query.ack === '1') filters.claimed = '1'
  else filters.claimed = ''
}

watch(
  () => [route.query.tab || '', route.query.search || '', route.query.level || '', route.query.claimed || '', route.query.ack || ''].join('|'),
  async () => {
    applyRouteFilters()
    page.value = 1
    await refreshAll()
  },
)

watch(currentContextId, async () => {
  page.value = 1
  selectedAlert.value = null
  await refreshAll()
})

onMounted(async () => {
  await businessContextStore.loadContexts()
  applyRouteFilters()
  users.value = listOf(await getUsers())
  await refreshAll()
})
</script>

<style scoped>
.alerts-page {
  --alert-primary: #3370ff;
  --alert-bg: #f7f8fa;
  --alert-panel: #ffffff;
  --alert-border-soft: #eff0f2;
  --alert-text: #1f2329;
  --alert-muted: #646a73;
  --alert-subtle: #8f959e;
  --alert-shadow: 0 8px 24px rgba(31, 35, 41, 0.06);
  background: linear-gradient(180deg, rgba(247, 248, 250, 0.94), rgba(255, 255, 255, 0) 180px), var(--alert-bg);
  color: var(--alert-text);
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 100%;
}

.hero,
.hero-title-row,
.hero-actions,
.toolbar,
.row-actions,
.group-toolbar,
.section-head,
.detail-actions,
.matcher-row,
.level-row,
.claimant-cell {
  align-items: center;
  display: flex;
  gap: 4px;
}

.claimant-cell {
  flex-wrap: wrap;
}

.claimant-tag {
  margin: 0;
}

.hero.panel {
  background: linear-gradient(180deg, #ffffff 0%, #fffdf8 100%);
  border: 1px solid var(--alert-border-soft);
  border-radius: 12px;
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04);
  justify-content: space-between;
  padding: 12px 14px;
}

.hero-copy {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.hero-title-row {
  align-items: center;
  gap: 10px;
}

.hero-title-row h2 {
  color: #0f172a;
  font-size: 23px;
  font-weight: 700;
  line-height: 1.1;
  margin: 0;
}

.page-inline-desc {
  color: #64748b;
  font-size: 13px;
  line-height: 1.45;
  margin: 0;
  flex: 0 1 auto;
  transform: translateY(1px);
}

.hero-icon {
  align-items: center;
  background: linear-gradient(135deg, #0f766e, #0ea5e9);
  border-radius: 16px;
  color: #fff;
  display: inline-flex;
  height: 40px;
  justify-content: center;
  width: 40px;
}

.hero-actions .el-button {
  border-radius: 10px;
  font-weight: 500;
  min-height: 32px;
  padding: 0 14px;
}

.panel {
  background: var(--alert-panel);
  border: 1px solid var(--alert-border-soft);
  border-radius: 16px;
  box-shadow: var(--alert-shadow);
  padding: 12px 14px;
}

.alert-center-tabs .neo-tab-btn {
  min-height: 36px;
  padding: 0 18px;
}

.alert-center-tabs.theme-blue .neo-tab-btn.active {
  color: #245bdb;
  background: rgba(51, 112, 255, 0.1);
  box-shadow: inset 0 0 0 1px rgba(51, 112, 255, 0.08);
}

.alert-center-tabs {
  margin: 0;
}

.alert-sub-tabs {
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.alert-sub-tabs .neo-sub-tab-btn {
  min-height: 30px;
  padding: 0 14px;
}

.alert-top-stats {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 0;
}

.alert-summary-card {
  justify-content: center;
  min-height: 68px;
  padding: 14px 16px;
}

.alert-summary-card.audit-card--action:hover {
  border-color: rgba(36, 91, 219, 0.16);
  box-shadow: 0 10px 20px rgba(36, 91, 219, 0.06);
}

.alert-summary-card.audit-card--action.is-active {
  border-color: rgba(36, 91, 219, 0.24);
  background: linear-gradient(180deg, #f4f7ff 0%, #ffffff 100%);
  box-shadow: 0 0 0 1px rgba(36, 91, 219, 0.05), 0 12px 22px rgba(36, 91, 219, 0.08);
}

.alert-summary-card .stat-label {
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.alert-summary-card .stat-value {
  color: #1f2329;
  font-size: 24px;
}

.toolbar,
.group-toolbar {
  background: #fbfcff;
  border: 1px solid var(--alert-border-soft);
  border-radius: 12px;
  margin-bottom: 8px;
  padding: 8px 10px;
}

.toolbar {
  flex-wrap: wrap;
}

.toolbar-spacer {
  flex: 1 1 auto;
}

.section-actions {
  align-items: center;
  display: flex;
  gap: 8px;
}

.toolbar .el-input {
  width: 280px;
}

.toolbar .el-select {
  width: 120px;
}

.group-toolbar .el-select {
  min-width: 420px;
}

.toolbar-label {
  color: var(--alert-muted);
  font-size: 12px;
  font-weight: 600;
}

.data-table {
  width: 100%;
}

.link-title {
  background: transparent;
  border: 0;
  color: var(--alert-text);
  cursor: pointer;
  font-weight: 600;
  padding: 0;
  text-align: left;
}

.link-title:hover {
  color: var(--alert-primary);
}

.alert-id-cell {
  color: var(--alert-text);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
}

.sub-line {
  color: var(--alert-subtle);
  margin-top: 3px;
}

.group-key {
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
  font-weight: 600;
}

.group-dimensions {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 14px;
  line-height: 1.45;
}

.group-dimensions span {
  color: var(--alert-text);
  font-size: 12px;
}

.group-dimensions strong {
  color: var(--alert-subtle);
  font-weight: 600;
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding-top: 8px;
}

.section-head {
  justify-content: space-between;
  margin-bottom: 8px;
  min-height: 30px;
}

.section-head h3 {
  font-size: 15px;
  font-weight: 700;
  margin: 0;
}

.split-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.split-panel {
  background: #fbfcff;
  border: 1px solid var(--alert-border-soft);
  border-radius: 14px;
  padding: 10px 12px;
}

.mini-tag {
  margin: 0 4px 4px 0;
}

.separator {
  color: #cbd5e1;
  margin: 0 6px;
}

.mono {
  color: var(--alert-muted);
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
}

.rule-name-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.rule-name-cell strong {
  color: var(--alert-text);
  font-size: 13px;
  line-height: 1.35;
}

.rule-name-cell span {
  color: var(--alert-subtle);
  font-size: 12px;
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
  line-height: 1.35;
  word-break: break-word;
}

.alert-detail-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.detail-head {
  align-items: flex-start;
  background: linear-gradient(135deg, #ffffff 0%, #f6faff 100%);
  border: 1px solid rgba(51, 112, 255, 0.16);
  border-radius: 10px;
  box-shadow: 0 8px 20px rgba(31, 35, 41, 0.05);
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 0;
  padding: 10px 12px;
}

.detail-badges {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.detail-alert-id {
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 999px;
  color: #475569;
  font-size: 12px;
  font-weight: 500;
  line-height: 22px;
  padding: 0 9px;
}

.detail-title {
  color: var(--alert-text);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.45;
}

.detail-fingerprint {
  color: var(--alert-subtle);
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
  font-size: 11px;
  line-height: 1.45;
  word-break: break-all;
}

.alert-detail-card {
  background: #fff;
  border: 1px solid var(--alert-border-soft);
  border-radius: 10px;
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.035);
  padding: 8px;
}

.alert-detail-summary {
  overflow: hidden;
  border-radius: 8px;
}

.alert-detail-summary :deep(.el-descriptions__table) {
  border-radius: 8px;
}

.alert-detail-summary :deep(.el-descriptions__cell) {
  border-color: #edf0f5;
}

.alert-detail-summary :deep(.el-descriptions__label) {
  background: #f8fafc;
  box-sizing: border-box;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
  min-width: 64px;
  padding: 6px 8px;
  text-align: left;
  white-space: nowrap;
  width: 64px;
  word-break: keep-all;
}

.alert-detail-summary :deep(.el-descriptions__content) {
  color: #334155;
  font-size: 12px;
  line-height: 1.45;
  padding: 6px 8px;
  word-break: break-word;
}

.log-evidence-card {
  min-height: 74px;
}

.analysis-card {
  min-height: 88px;
}

.analysis-heading-actions {
  align-items: center;
  display: flex;
  gap: 6px;
}

.analysis-evidence {
  color: #334155;
  font-size: 12px;
  margin-top: 9px;
}

.analysis-evidence ol {
  margin: 6px 0 0;
  padding-left: 20px;
}

.analysis-evidence li {
  line-height: 1.55;
  margin-bottom: 3px;
}

.log-evidence-list {
  display: grid;
  gap: 7px;
  max-height: 320px;
  overflow: auto;
}

.log-evidence-item {
  background: #f8fafc;
  border: 1px solid #edf0f5;
  border-radius: 8px;
  padding: 7px;
}

.log-evidence-meta {
  align-items: center;
  color: #64748b;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 11px;
  line-height: 1.4;
  margin-bottom: 5px;
}

.log-evidence-meta strong {
  color: #334155;
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
  font-weight: 600;
  word-break: break-all;
}

.log-evidence-item p {
  color: #1e293b;
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.detail-actions {
  background: #fff;
  border: 1px solid var(--alert-border-soft);
  border-radius: 10px;
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.035);
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 8px;
}

.detail-actions :deep(.el-button) {
  margin-left: 0;
}

.detail-section-title {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin-bottom: 7px;
}

.detail-section-title h4 {
  color: var(--alert-text);
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
  margin: 0;
}

.detail-section-title span,
.detail-empty {
  color: var(--alert-muted);
  font-size: 12px;
}

.field-suffix {
  color: var(--alert-muted);
  margin-left: 8px;
}

.mute-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.kv-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-bottom: 0;
}

.alert-detail-timeline {
  margin-top: 2px;
  padding-left: 2px;
}

.alert-detail-timeline :deep(.el-timeline-item) {
  padding-bottom: 10px;
}

.alert-detail-timeline :deep(.el-timeline-item__timestamp) {
  color: #8f959e;
  font-size: 11px;
  line-height: 1.3;
}

.alert-detail-timeline :deep(.el-timeline-item__content) {
  color: #334155;
  font-size: 12px;
  line-height: 1.45;
}

.matcher-editor,
.level-editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}

.matcher-row,
.level-row {
  flex-wrap: nowrap;
  width: 100%;
}

.matcher-row .el-input {
  flex: 1;
}

.matcher-row .el-select {
  width: 110px;
}

.level-row {
  background: #fbfcff;
  border: 1px solid var(--alert-border-soft);
  border-radius: 12px;
  padding: 7px 8px;
}

.level-row .el-input {
  width: 150px;
}

.level-row .el-select {
  min-width: 220px;
}

.channel-advanced {
  margin: 4px 0 14px;
}

.channel-advanced :deep(.el-collapse-item__content) {
  padding-bottom: 0;
}

.field-help {
  margin: 0 0 12px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.alerts-page :deep(.el-input__wrapper),
.alerts-page :deep(.el-select__wrapper) {
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 0 0 1px var(--alert-border-soft) inset;
}

.alerts-page :deep(.el-drawer__header) {
  margin-bottom: 8px;
}

.alerts-page :deep(.el-drawer__body) {
  padding-top: 8px;
}

.alerts-page :deep(.alert-detail-drawer .el-drawer__header) {
  border-bottom: 1px solid #edf0f5;
  margin-bottom: 0;
  padding: 14px 18px 10px;
}

.alerts-page :deep(.alert-detail-drawer .el-drawer__body) {
  background: #f7f8fa;
  padding: 10px 14px 14px;
}

.alerts-page :deep(.el-button--primary) {
  --el-button-bg-color: var(--alert-primary);
  --el-button-border-color: var(--alert-primary);
  --el-button-hover-bg-color: #2b63db;
  --el-button-hover-border-color: #2b63db;
  border-radius: 10px;
}

.alerts-page :deep(.el-button:not(.is-link)) {
  border-radius: 10px;
}

.alerts-page :deep(.el-segmented) {
  --el-segmented-item-selected-bg-color: #ffffff;
  --el-segmented-item-selected-color: var(--alert-primary);
  background: #f2f3f5;
  border-radius: 10px;
  padding: 2px;
}

.alerts-page :deep(.el-table) {
  --el-table-border-color: var(--alert-border-soft);
  --el-table-header-bg-color: #fbfcff;
  --el-table-header-text-color: var(--alert-muted);
  --el-table-row-hover-bg-color: #f7faff;
  border-radius: 12px;
  color: var(--alert-text);
  overflow: hidden;
}

.alerts-page :deep(.el-tag) {
  border-radius: 999px;
  font-weight: 500;
}

.alerts-page :deep(.el-dialog),
.alerts-page :deep(.el-drawer) {
  border-radius: 10px;
}

@media (max-width: 1100px) {
  .alert-top-stats,
  .split-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .data-table :deep(.el-table__header),
  .data-table :deep(.el-table__body),
  .data-table :deep(.el-scrollbar__view) {
    width: 100% !important;
  }

  .group-data-table :deep(col:nth-child(3)),
  .group-data-table :deep(col:nth-child(4)),
  .group-data-table :deep(col:nth-child(5)),
  .group-data-table :deep(col:nth-child(6)),
  .group-data-table :deep(col:nth-child(7)),
  .group-data-table :deep(th:nth-child(3)),
  .group-data-table :deep(th:nth-child(4)),
  .group-data-table :deep(th:nth-child(5)),
  .group-data-table :deep(th:nth-child(6)),
  .group-data-table :deep(th:nth-child(7)),
  .group-data-table :deep(td:nth-child(3)),
  .group-data-table :deep(td:nth-child(4)),
  .group-data-table :deep(td:nth-child(5)),
  .group-data-table :deep(td:nth-child(6)),
  .group-data-table :deep(td:nth-child(7)) {
    display: none;
  }

  .list-data-table :deep(col:nth-child(1)),
  .list-data-table :deep(col:nth-child(2)),
  .list-data-table :deep(col:nth-child(6)),
  .list-data-table :deep(col:nth-child(7)),
  .list-data-table :deep(col:nth-child(8)),
  .list-data-table :deep(col:nth-child(9)),
  .list-data-table :deep(col:nth-child(10)),
  .list-data-table :deep(col:nth-child(11)),
  .list-data-table :deep(th:nth-child(1)),
  .list-data-table :deep(th:nth-child(2)),
  .list-data-table :deep(th:nth-child(6)),
  .list-data-table :deep(th:nth-child(7)),
  .list-data-table :deep(th:nth-child(8)),
  .list-data-table :deep(th:nth-child(9)),
  .list-data-table :deep(th:nth-child(10)),
  .list-data-table :deep(th:nth-child(11)),
  .list-data-table :deep(td:nth-child(1)),
  .list-data-table :deep(td:nth-child(2)),
  .list-data-table :deep(td:nth-child(6)),
  .list-data-table :deep(td:nth-child(7)),
  .list-data-table :deep(td:nth-child(8)),
  .list-data-table :deep(td:nth-child(9)),
  .list-data-table :deep(td:nth-child(10)),
  .list-data-table :deep(td:nth-child(11)) {
    display: none;
  }
}

@media (max-width: 760px) {
  .hero.panel,
  .hero-title-row,
  .matcher-row,
  .level-row {
    align-items: stretch;
    flex-direction: column;
  }

  .page-inline-desc {
    flex-basis: 100%;
    padding-left: 54px;
  }

  .alert-top-stats,
  .split-grid {
    grid-template-columns: 1fr;
  }

  .toolbar .el-input,
  .toolbar .el-select,
  .group-toolbar .el-select,
  .level-row .el-input,
  .level-row .el-select,
  .matcher-row .el-select {
    min-width: 0;
    width: 100%;
  }
}
</style>
