<template><div class="native-chart-shell"><div v-if="empty" class="native-chart-empty">暂无数据</div><div v-show="!empty" ref="chartRef" class="native-chart-canvas" /></div></template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import echarts from '@/lib/echarts'

const props = defineProps({ panel: { type: Object, required: true }, dark: { type: Boolean, default: false } })
const chartRef = ref(null)
let chart = null
let resizeObserver = null
const type = computed(() => props.panel?.type || 'timeseries')
const series = computed(() => props.panel?.data?.series || [])
const rows = computed(() => props.panel?.data?.rows || [])
const empty = computed(() => type.value === 'timeseries' ? !series.value.some((item) => item.points?.length) : !rows.value.length)
const palette = computed(() => props.dark ? ['#4ba3ff', '#28d6a0', '#ff7180', '#b08cff', '#f4b85d', '#48c9e8', '#6d8cff', '#e67ad0'] : ['#356bd8', '#19ad83', '#ed6b73', '#836be8', '#e6a33b', '#2aabc2'])
function formatValue(value) { const n = Number(value || 0); if (props.panel?.unit === 'bytes' || props.panel?.unit === 'Bps') { if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} Gi`; if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} Mi`; if (n >= 1024) return `${(n / 1024).toFixed(1)} Ki` } return n.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }
function axisStyle() { return { color: props.dark ? '#7f94b2' : '#64748b' } }
function buildOption() {
  const text = props.dark ? '#a9bad1' : '#536a82'; const line = props.dark ? '#2c3a52' : '#dce5ef'; const colors = palette.value
  if (type.value === 'timeseries') return { animation: false, color: colors, tooltip: { trigger: 'axis', valueFormatter: formatValue, backgroundColor: props.dark ? '#202b3e' : '#fff', borderColor: props.dark ? '#465a78' : '#d9e3ef', textStyle: { color: props.dark ? '#e8f0fb' : '#31465d' } }, legend: { type: 'scroll', bottom: 0, left: 0, textStyle: { color: text, fontSize: 10 }, data: series.value.map((item) => item.name) }, grid: { left: 48, right: 18, top: 15, bottom: 34 }, xAxis: { type: 'time', axisLabel: axisStyle(), axisLine: { lineStyle: { color: line } } }, yAxis: { type: 'value', axisLabel: { ...axisStyle(), formatter: formatValue }, splitLine: { lineStyle: { color: line, type: 'dashed' } } }, series: series.value.map((item, index) => ({ name: item.name || `series-${index + 1}`, type: 'line', showSymbol: false, smooth: true, lineStyle: { width: 2, color: colors[index % colors.length] }, areaStyle: { color: `${colors[index % colors.length]}18` }, data: item.points || [] })) }
  if (type.value === 'pie') return { animation: false, color: colors, tooltip: { trigger: 'item', valueFormatter: formatValue }, legend: { type: 'scroll', orient: 'vertical', right: 0, top: 'middle', textStyle: { color: text, fontSize: 10 } }, series: [{ type: 'pie', radius: ['42%', '70%'], center: ['38%', '50%'], itemStyle: { borderColor: props.dark ? '#1a2232' : '#fff', borderWidth: 2 }, label: { color: text, fontSize: 10 }, data: rows.value.slice(0, 12).map((item) => ({ name: item.name || '--', value: Number(item.value || 0) })) }] }
  const visible = rows.value.slice(0, 20).reverse(); return { animation: false, color: colors, tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: formatValue }, grid: { left: 112, right: 18, top: 10, bottom: 26 }, xAxis: { type: 'value', axisLabel: { ...axisStyle(), formatter: formatValue }, splitLine: { lineStyle: { color: line, type: 'dashed' } } }, yAxis: { type: 'category', data: visible.map((item) => item.name || '--'), axisLabel: { ...axisStyle(), width: 100, overflow: 'truncate' }, axisLine: { lineStyle: { color: line } } }, series: [{ type: 'bar', barMaxWidth: 18, itemStyle: { borderRadius: [0, 4, 4, 0] }, data: visible.map((item, index) => ({ value: Number(item.value || 0), itemStyle: { color: colors[index % colors.length] } })) }] }
}
async function renderChart() { await nextTick(); if (!chartRef.value || empty.value) return; if (!chart) chart = echarts.init(chartRef.value, null, { renderer: 'canvas' }); chart.setOption(buildOption(), true); chart.resize() }
function resize() { chart?.resize() }
watch(() => props.panel, renderChart, { deep: true }); watch(empty, renderChart)
onMounted(() => { renderChart(); resizeObserver = typeof ResizeObserver !== 'undefined' && chartRef.value ? new ResizeObserver(resize) : null; resizeObserver?.observe(chartRef.value); window.addEventListener('resize', resize) })
onBeforeUnmount(() => { window.removeEventListener('resize', resize); resizeObserver?.disconnect(); chart?.dispose(); chart = null })
</script>

<style scoped>
.native-chart-shell { position: relative; width: 100%; min-height: 150px; }
.native-chart-canvas { width: 100%; height: 250px; }
.native-chart-empty { display: grid; min-height: 150px; place-items: center; color: #7c90ab; font-size: 12px; }
</style>
