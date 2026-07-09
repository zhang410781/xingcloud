<template>
  <div class="native-chart-shell">
    <div v-if="empty" class="native-chart-empty">暂无数据</div>
    <div v-show="!empty" ref="chartRef" class="native-chart-canvas"></div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import echarts from '@/lib/echarts'

const props = defineProps({
  panel: {
    type: Object,
    required: true,
  },
})

const chartRef = ref(null)
let chart = null
let resizeObserver = null

const panelType = computed(() => props.panel?.type || '')
const series = computed(() => Array.isArray(props.panel?.data?.series) ? props.panel.data.series : [])
const rows = computed(() => Array.isArray(props.panel?.data?.rows) ? props.panel.data.rows : [])
const empty = computed(() => {
  if (panelType.value === 'timeseries') {
    return !series.value.some((item) => Array.isArray(item.points) && item.points.length)
  }
  return !rows.value.length
})

function formatAxisValue(value) {
  const number = Number(value || 0)
  if (props.panel?.unit === 'bytes') {
    if (number >= 1024 ** 3) return `${(number / 1024 ** 3).toFixed(1)}Gi`
    if (number >= 1024 ** 2) return `${(number / 1024 ** 2).toFixed(1)}Mi`
    if (number >= 1024) return `${(number / 1024).toFixed(1)}Ki`
  }
  if (Math.abs(number) >= 1000) return number.toLocaleString('zh-CN', { maximumFractionDigits: 1 })
  return Number(number.toFixed(2)).toLocaleString('zh-CN')
}

function buildTimeseriesOption() {
  return {
    animation: false,
    color: ['#2563eb', '#059669', '#dc2626', '#7c3aed', '#ea580c', '#0891b2', '#4f46e5', '#16a34a'],
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => formatAxisValue(value),
    },
    legend: {
      type: 'scroll',
      top: 0,
      right: 4,
      textStyle: { color: '#475569', fontSize: 11 },
    },
    grid: { left: 48, right: 20, top: 36, bottom: 34 },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisLabel: { color: '#64748b' },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: '#64748b',
        formatter: (value) => formatAxisValue(value),
      },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
    },
    series: series.value.map((item) => ({
      name: item.name || 'value',
      type: 'line',
      showSymbol: false,
      smooth: true,
      lineStyle: { width: 2 },
      data: Array.isArray(item.points) ? item.points : [],
    })),
  }
}

function buildBarOption() {
  const visibleRows = rows.value.slice(0, 20).reverse()
  return {
    animation: false,
    color: ['#2563eb'],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value) => formatAxisValue(value),
    },
    grid: { left: 112, right: 24, top: 16, bottom: 26 },
    xAxis: {
      type: 'value',
      axisLabel: {
        color: '#64748b',
        formatter: (value) => formatAxisValue(value),
      },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
    },
    yAxis: {
      type: 'category',
      data: visibleRows.map((item) => item.name || '--'),
      axisLabel: { color: '#475569', width: 96, overflow: 'truncate' },
      axisLine: { lineStyle: { color: '#cbd5e1' } },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 18,
      data: visibleRows.map((item) => Number(item.value || 0)),
    }],
  }
}

async function renderChart() {
  await nextTick()
  if (!chartRef.value || empty.value) return
  if (!chart) chart = echarts.init(chartRef.value, null, { renderer: 'canvas' })
  chart.setOption(panelType.value === 'timeseries' ? buildTimeseriesOption() : buildBarOption(), true)
  chart.resize()
}

function handleResize() {
  chart?.resize()
}

watch(() => props.panel, renderChart, { deep: true })
watch(empty, renderChart)

onMounted(() => {
  renderChart()
  if (typeof ResizeObserver !== 'undefined' && chartRef.value) {
    resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(chartRef.value)
  }
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  if (resizeObserver && chartRef.value) resizeObserver.unobserve(chartRef.value)
  resizeObserver = null
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.native-chart-shell {
  position: relative;
  width: 100%;
  min-height: 260px;
}

.native-chart-canvas {
  width: 100%;
  height: 280px;
}

.native-chart-empty {
  min-height: 260px;
  display: grid;
  place-items: center;
  color: #94a3b8;
  font-size: 13px;
  background: #f8fafc;
  border-radius: 6px;
}
</style>
