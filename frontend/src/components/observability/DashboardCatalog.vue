<template>
  <section class="panel dashboard-catalog">
    <div class="section-head">
      <div>
        <h3>看板目录</h3>
        <p>所有监控页面统一由 JSON 看板定义渲染。</p>
      </div>
      <div class="section-actions">
        <el-input v-model="keyword" size="small" clearable placeholder="搜索看板" />
        <el-select v-model="tag" size="small" clearable placeholder="标签">
          <el-option v-for="item in tags" :key="item" :label="item" :value="item" />
        </el-select>
      </div>
    </div>

    <div class="dashboard-catalog__grid">
      <button
        v-for="item in filtered"
        :key="item.id"
        type="button"
        class="dashboard-catalog__card"
        :class="{ active: String(item.id) === String(modelValue) }"
        @click="$emit('update:modelValue', item.id)"
      >
        <strong>{{ item.title }}</strong>
        <span>{{ item.description || 'Xing-Cloud JSON 看板' }}</span>
        <small>{{ (item.tags || []).join(' / ') || '未分类' }} / {{ item.panels?.length || item.panel_count || 0 }} 面板</small>
      </button>
    </div>

    <el-empty v-if="!filtered.length" description="暂无看板定义" :image-size="86" />
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  dashboards: { type: Array, default: () => [] },
  modelValue: { type: [String, Number], default: '' },
})

defineEmits(['update:modelValue'])

const keyword = ref('')
const tag = ref('')
const tags = computed(() => Array.from(new Set(props.dashboards.flatMap((item) => item.tags || []))).sort())
const filtered = computed(() => props.dashboards.filter((item) => {
  const text = `${item.title || ''} ${item.description || ''} ${(item.tags || []).join(' ')}`.toLowerCase()
  const keywordOk = !keyword.value || text.includes(keyword.value.toLowerCase())
  const tagOk = !tag.value || (item.tags || []).includes(tag.value)
  return keywordOk && tagOk
}))
</script>

<style scoped>
.dashboard-catalog {
  display: grid;
  gap: 12px;
}

.section-head p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
}

.section-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.section-actions .el-input {
  width: 220px;
}

.section-actions .el-select {
  width: 150px;
}

.dashboard-catalog__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.dashboard-catalog__card {
  min-height: 128px;
  text-align: left;
  border: 1px solid rgba(226, 232, 240, 0.92);
  border-radius: 8px;
  padding: 14px;
  background: #fff;
  display: grid;
  gap: 6px;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.dashboard-catalog__card:hover,
.dashboard-catalog__card.active {
  border-color: #2563eb;
  box-shadow: 0 10px 28px rgba(37, 99, 235, 0.1);
  transform: translateY(-1px);
}

.dashboard-catalog__card strong {
  color: #0f172a;
  font-size: 15px;
}

.dashboard-catalog__card span,
.dashboard-catalog__card small {
  color: #64748b;
  line-height: 1.5;
}
</style>
