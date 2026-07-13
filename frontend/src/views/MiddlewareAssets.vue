<template>
  <div class="middleware-page fade-in">
    <section class="middleware-hero">
      <div class="hero-copy">
        <span class="hero-icon"><el-icon><Coin /></el-icon></span>
        <div>
          <h2>中间件资产</h2>
          <p>统一纳管数据库、缓存、消息队列与搜索类运行组件，作为监控接入、告警规则和 AIOps 研判的资产底座。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :icon="Refresh" :loading="loading" @click="loadOverview">刷新</el-button>
      </div>
    </section>

    <section class="asset-summary-grid">
      <button
        v-for="item in categoryCards"
        :key="item.key"
        type="button"
        class="asset-summary-card"
        :class="[`is-${item.tone}`, { active: activeCategory === item.key }]"
        @click="activeCategory = item.key"
      >
        <span class="summary-icon"><el-icon><component :is="item.icon" /></el-icon></span>
        <span class="summary-body">
          <strong>{{ item.value }}</strong>
          <span>{{ item.label }}</span>
          <small>{{ item.desc }}</small>
        </span>
      </button>
    </section>

    <section class="asset-workspace">
      <div class="workspace-toolbar">
        <div class="toolbar-tabs">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            type="button"
            :class="{ active: activeCategory === tab.key }"
            @click="activeCategory = tab.key"
          >
            <el-icon><component :is="tab.icon" /></el-icon>
            <span>{{ tab.label }}</span>
          </button>
        </div>
        <div class="toolbar-meta">
          <el-tag size="small" effect="plain" :type="warningCount ? 'warning' : 'success'">
            {{ warningCount ? `${warningCount} 项待关注` : '运行正常' }}
          </el-tag>
          <span>最近同步：{{ formatTime(overview.updated_at) }}</span>
        </div>
      </div>

      <div v-if="activeCategory === 'database'" class="definition-grid">
        <article v-for="item in databaseAssets" :key="item.name" class="definition-card">
          <div class="definition-head">
            <div>
              <strong>{{ item.name }}</strong>
              <span>{{ item.engine }}</span>
            </div>
            <el-tag size="small" effect="plain" :type="statusType(item.monitoring?.status || item.status)">
              {{ statusLabel(item.monitoring?.status || item.status) }}
            </el-tag>
          </div>
          <div class="definition-meta">
            <span>环境：{{ item.environment }}</span>
            <span>监控：{{ item.metrics }}</span>
            <span>日志：{{ item.logs }}</span>
            <span v-if="item.monitoring?.connections !== undefined && item.monitoring?.connections !== null">
              连接：{{ item.monitoring.connections }} / {{ item.monitoring.max_connections || '-' }}
            </span>
            <span>{{ item.monitoring?.message || '监控状态待同步' }}</span>
          </div>
        </article>
      </div>

      <template v-else-if="activeCategory === 'redis'">
        <div class="table-head">
          <div>
            <strong>Redis 实例</strong>
            <span>
              按集群、角色、复制延迟和内存水位识别风险。
              Prometheus：{{ statusLabel(redisMonitoring.status) }}
            </span>
          </div>
          <el-button v-if="canManage" size="small" :icon="Plus" @click="importRedisTemplate">导入模板</el-button>
        </div>
        <el-table :data="redisInstances" stripe border>
          <el-table-column prop="name" label="实例" min-width="170" show-overflow-tooltip />
          <el-table-column prop="cluster" label="集群" min-width="130" show-overflow-tooltip />
          <el-table-column prop="role" label="角色" width="100" />
          <el-table-column prop="endpoint" label="地址" min-width="150" show-overflow-tooltip />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="内存" width="130">
            <template #default="{ row }">
              <el-progress :percentage="Number(row.memory_usage) || 0" :stroke-width="8" :show-text="false" />
              <span class="metric-mini">{{ row.memory_usage }}%</span>
            </template>
          </el-table-column>
          <el-table-column prop="qps" label="QPS" width="110" />
          <el-table-column prop="replication_delay_ms" label="复制延迟(ms)" width="135" />
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" :disabled="!canManage" @click="runRedisAction(row, 'restart')">重启</el-button>
              <el-button link type="warning" size="small" :disabled="!canManage || row.role !== 'replica'" @click="runRedisAction(row, 'promote')">提升</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else-if="activeCategory === 'mq'">
        <div class="table-head">
          <div>
            <strong>Kafka / MQ 集群</strong>
            <span>Kafka 接入位已预留，当前复用 RocketMQ 演示数据校验资产框架。</span>
          </div>
        </div>
        <div class="definition-grid mq-ready-grid">
          <article v-for="item in kafkaAssets" :key="item.name" class="definition-card">
            <div class="definition-head">
              <div>
                <strong>{{ item.name }}</strong>
                <span>{{ item.engine }}</span>
              </div>
              <el-tag size="small" effect="plain" type="info">{{ item.status }}</el-tag>
            </div>
            <div class="definition-meta">
              <span>接入方式：{{ item.metrics }}</span>
              <span>用途：{{ item.usage }}</span>
            </div>
          </article>
        </div>
        <el-table :data="rocketmqClusters" stripe border>
          <el-table-column prop="name" label="集群" min-width="150" show-overflow-tooltip />
          <el-table-column prop="environment" label="环境" width="100" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="broker_count" label="Broker" width="100" />
          <el-table-column prop="topic_count" label="Topic" width="100" />
          <el-table-column prop="tps" label="TPS" width="120" />
        </el-table>
      </template>

      <template v-else>
        <div class="table-head">
          <div>
            <strong>搜索与日志组件</strong>
            <span>展示 Elasticsearch 集群、节点和索引资产，后续可承接 OpenSearch。</span>
          </div>
        </div>
        <el-table :data="esClusters" stripe border>
          <el-table-column prop="name" label="集群" min-width="150" show-overflow-tooltip />
          <el-table-column prop="environment" label="环境" width="100" />
          <el-table-column prop="health" label="健康" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="row.health === 'green' ? 'success' : 'warning'">{{ row.health }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="nodes" label="节点" width="90" />
          <el-table-column prop="indices" label="索引" width="100" />
          <el-table-column prop="storage" label="容量" width="110" />
          <el-table-column prop="unassigned_shards" label="未分配分片" width="130" />
        </el-table>
      </template>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Coin,
  Connection,
  Grid,
  Plus,
  Refresh,
  Search,
} from '@element-plus/icons-vue'
import { getMiddlewareOverview, runMiddlewareAction } from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const loading = ref(false)
const activeCategory = ref('database')
const overview = ref({})

const canManage = computed(() => authStore.hasPermission('ops.middleware.manage'))
const redis = computed(() => overview.value.redis || {})
const rocketmq = computed(() => overview.value.rocketmq || {})
const elasticsearch = computed(() => overview.value.elasticsearch || {})
const redisMonitoring = computed(() => redis.value.monitoring || {})
const redisInstances = computed(() => redis.value.instances || [])
const rocketmqClusters = computed(() => rocketmq.value.clusters || [])
const esClusters = computed(() => elasticsearch.value.clusters || [])

const databaseAssets = computed(() => {
  const assets = overview.value.database?.assets
  if (Array.isArray(assets) && assets.length) return assets
  return [
    {
      name: 'xing-cloud-mysql',
      engine: 'MySQL',
      environment: 'xing-cloud',
      status: 'not_connected',
      metrics: 'mysqld_exporter',
      logs: 'ClickHouse 容器日志',
      monitoring: { status: 'not_connected', message: '等待 Prometheus 同步' },
    },
    {
      name: '业务 PostgreSQL',
      engine: 'PostgreSQL',
      environment: '预留',
      status: 'framework_ready',
      metrics: 'postgres_exporter',
      logs: 'ClickHouse 容器日志',
      monitoring: { status: 'framework_ready', message: '框架就绪，待接入 postgres_exporter' },
    },
  ]
})

const kafkaAssets = [
  { name: 'Kafka 集群', engine: 'Kafka', status: '框架就绪', metrics: 'kafka_exporter / JMX exporter', usage: '消息队列资产、消费滞后与 Topic 风险' },
  { name: 'RocketMQ 集群', engine: 'RocketMQ', status: '演示数据', metrics: '平台内置示例', usage: '验证 MQ 资产页结构与告警风险展示' },
]

const tabs = [
  { key: 'database', label: '数据库', icon: Coin },
  { key: 'redis', label: 'Redis', icon: Grid },
  { key: 'mq', label: 'Kafka / MQ', icon: Connection },
  { key: 'search', label: '搜索组件', icon: Search },
]

const warningCount = computed(() => {
  const redisWarnings = redis.value.summary?.warning_count || 0
  const mqWarnings = rocketmq.value.summary?.warning_count || 0
  const esWarnings = elasticsearch.value.summary?.warning_count || 0
  return redisWarnings + mqWarnings + esWarnings
})

const categoryCards = computed(() => [
  {
    key: 'database',
    label: '数据库资产',
    value: databaseAssets.value.length,
    desc: `${overview.value.database?.summary?.monitored_count || 0} 个已监控`,
    icon: Coin,
    tone: 'database',
  },
  {
    key: 'redis',
    label: '缓存实例',
    value: redis.value.summary?.instance_count || 0,
    desc: `${redis.value.summary?.cluster_count || 0} 个 Redis 集群`,
    icon: Grid,
    tone: 'redis',
  },
  {
    key: 'mq',
    label: '消息队列',
    value: (rocketmq.value.summary?.cluster_count || 0) + 1,
    desc: 'Kafka 预留 + RocketMQ 演示',
    icon: Connection,
    tone: 'mq',
  },
  {
    key: 'search',
    label: '搜索组件',
    value: elasticsearch.value.summary?.cluster_count || 0,
    desc: `${elasticsearch.value.summary?.node_count || 0} 个节点`,
    icon: Search,
    tone: 'search',
  },
])

function statusType(status) {
  if (['healthy', 'online', 'green'].includes(status)) return 'success'
  if (['warning', 'yellow'].includes(status)) return 'warning'
  if (['critical', 'red', 'offline'].includes(status)) return 'danger'
  return 'info'
}

function statusLabel(status) {
  return {
    healthy: '健康',
    warning: '告警',
    online: '在线',
    offline: '离线',
    green: '健康',
    yellow: '风险',
    red: '异常',
    critical: '异常',
    not_connected: '未接入',
    framework_ready: '框架就绪',
  }[status] || status || '未知'
}

function formatTime(value) {
  if (!value) return '未同步'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

async function loadOverview() {
  loading.value = true
  try {
    overview.value = await getMiddlewareOverview()
  } finally {
    loading.value = false
  }
}

async function runRedisAction(row, action) {
  try {
    const response = await runMiddlewareAction({ module: 'redis', target_id: row.id, action })
    overview.value = response.data || overview.value
    ElMessage.success(action === 'promote' ? '已提升 Redis 副本' : 'Redis 操作已提交')
  } catch (error) {}
}

async function importRedisTemplate() {
  try {
    const response = await runMiddlewareAction({
      module: 'redis',
      action: 'import_template',
      payload: { scope: 'instance', template_key: 'replica' },
    })
    overview.value = response.data || overview.value
    ElMessage.success('Redis 模板已导入')
  } catch (error) {}
}

onMounted(loadOverview)
</script>

<style scoped>
.middleware-page {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.middleware-hero {
  align-items: center;
  background: linear-gradient(135deg, #ffffff 0%, #f5fbfb 52%, #f8fafc 100%);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 16px;
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.05);
  display: flex;
  justify-content: space-between;
  padding: 14px 18px;
}

.hero-copy {
  align-items: center;
  display: flex;
  gap: 12px;
  min-width: 0;
}

.hero-icon {
  align-items: center;
  background: linear-gradient(135deg, #2563eb, #0f766e);
  border-radius: 14px;
  color: #fff;
  display: inline-flex;
  flex: 0 0 auto;
  font-size: 21px;
  height: 42px;
  justify-content: center;
  width: 42px;
}

.hero-copy h2 {
  color: #0f172a;
  font-size: 23px;
  line-height: 1.15;
  margin: 0;
}

.hero-copy p {
  color: #475569;
  font-size: 13px;
  line-height: 1.45;
  margin: 4px 0 0;
}

.hero-actions {
  display: flex;
  flex: 0 0 auto;
  gap: 8px;
}

.asset-summary-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.asset-summary-card {
  align-items: center;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
  color: inherit;
  cursor: pointer;
  display: flex;
  gap: 12px;
  min-height: 92px;
  padding: 14px;
  text-align: left;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.asset-summary-card:hover,
.asset-summary-card.active {
  border-color: rgba(37, 99, 235, 0.28);
  box-shadow: 0 16px 30px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.summary-icon {
  align-items: center;
  border-radius: 12px;
  color: #fff;
  display: inline-flex;
  flex: 0 0 auto;
  font-size: 20px;
  height: 40px;
  justify-content: center;
  width: 40px;
}

.is-database .summary-icon { background: linear-gradient(135deg, #2563eb, #60a5fa); }
.is-redis .summary-icon { background: linear-gradient(135deg, #dc2626, #fb7185); }
.is-mq .summary-icon { background: linear-gradient(135deg, #7c3aed, #22c55e); }
.is-search .summary-icon { background: linear-gradient(135deg, #0f766e, #f59e0b); }

.summary-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.summary-body strong {
  color: #0f172a;
  font-size: 24px;
  line-height: 1.05;
}

.summary-body span {
  color: #334155;
  font-size: 13px;
  font-weight: 700;
  margin-top: 4px;
}

.summary-body small {
  color: #64748b;
  font-size: 12px;
  line-height: 1.35;
  margin-top: 4px;
}

.asset-workspace {
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 14px;
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.05);
  padding: 12px;
}

.workspace-toolbar {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
  margin-bottom: 12px;
}

.toolbar-tabs {
  align-items: center;
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 10px;
  display: inline-flex;
  gap: 4px;
  padding: 4px;
}

.toolbar-tabs button {
  align-items: center;
  background: transparent;
  border: 0;
  border-radius: 8px;
  color: #475569;
  cursor: pointer;
  display: inline-flex;
  font-size: 13px;
  font-weight: 700;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
}

.toolbar-tabs button.active {
  background: #fff;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08);
  color: #1d4ed8;
}

.toolbar-meta {
  align-items: center;
  color: #64748b;
  display: flex;
  flex-wrap: wrap;
  font-size: 12px;
  gap: 8px;
  justify-content: flex-end;
}

.definition-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.mq-ready-grid {
  margin-bottom: 12px;
}

.definition-card {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 10px;
  padding: 12px;
}

.definition-head {
  align-items: flex-start;
  display: flex;
  gap: 10px;
  justify-content: space-between;
}

.definition-head div,
.definition-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.definition-head strong {
  color: #0f172a;
  font-size: 15px;
}

.definition-head span,
.definition-meta span {
  color: #64748b;
  font-size: 12px;
  line-height: 1.35;
}

.definition-meta {
  margin-top: 12px;
}

.table-head {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
}

.table-head div {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.table-head strong {
  color: #0f172a;
  font-size: 15px;
}

.table-head span,
.metric-mini {
  color: #64748b;
  font-size: 12px;
}

.metric-mini {
  display: inline-block;
  margin-top: 4px;
}

@media (max-width: 1080px) {
  .asset-summary-grid,
  .definition-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .middleware-hero,
  .workspace-toolbar,
  .table-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .asset-summary-grid,
  .definition-grid {
    grid-template-columns: 1fr;
  }

  .toolbar-tabs {
    flex-wrap: wrap;
  }
}
</style>
