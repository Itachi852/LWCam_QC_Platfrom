<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts/core'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { PieChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import AppShell from '@/components/AppShell.vue'
import { adminApi } from '@/api'
import { translateValue } from '@/i18n'
import type { StatsOverview } from '@/types'

echarts.use([TooltipComponent, LegendComponent, PieChart, CanvasRenderer])

const { t, locale } = useI18n()
const loading = ref(false)
const chartRef = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
const stats = ref<StatsOverview>({
  todayNewTasks: 0,
  todayCompletedTasks: 0,
  todayQcPassRate: 0,
  totalUsers: 0,
  totalTasks: 0,
  pendingClaimTasks: 0,
  taskTrend: [],
  taskStatusDistribution: [],
  reviewerWorkload: [],
})

const statusDistribution = computed(() =>
  {
    void locale.value
    return stats.value.taskStatusDistribution.map((item) => ({
      name: translateValue('metadataQcStatus', item.status || item.label),
      value: item.count,
    }))
  },
)

async function load() {
  loading.value = true
  try {
    const { data } = await adminApi.stats()
    stats.value = data.data
    await nextTick()
    renderChart()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

function renderChart() {
  if (!chartRef.value) return
  chart ||= echarts.init(chartRef.value)
  chart.setOption({
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, left: 'center' },
    series: [
      {
        name: t('admin.stats.distribution'),
        type: 'pie',
        radius: ['46%', '70%'],
        center: ['50%', '42%'],
        avoidLabelOverlap: true,
        data: statusDistribution.value,
      },
    ],
  })
}

function resizeChart() {
  chart?.resize()
}

watch(locale, () => {
  void nextTick(() => renderChart())
})

onMounted(() => {
  load()
  window.addEventListener('resize', resizeChart)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  chart?.dispose()
})
</script>

<template>
  <AppShell>
    <div class="page-title">
      <div>
        <h1>{{ t('admin.stats.title') }}</h1>
        <p>{{ t('admin.stats.subtitle') }}</p>
      </div>
      <el-button :icon="'Refresh'" :loading="loading" @click="load">{{ t('common.refresh') }}</el-button>
    </div>

    <div class="metric-grid">
      <div class="metric accent"><span>{{ t('admin.stats.todayNew') }}</span><strong>{{ stats.todayNewTasks }}</strong></div>
      <div class="metric green"><span>{{ t('admin.stats.todayCompleted') }}</span><strong>{{ stats.todayCompletedTasks }}</strong></div>
      <div class="metric green"><span>{{ t('admin.stats.todayPassRate') }}</span><strong>{{ stats.todayQcPassRate }}%</strong></div>
      <div class="metric"><span>{{ t('admin.stats.pendingClaim') }}</span><strong>{{ stats.pendingClaimTasks }}</strong></div>
      <div class="metric"><span>{{ t('admin.stats.totalUsers') }}</span><strong>{{ stats.totalUsers }}</strong></div>
      <div class="metric"><span>{{ t('admin.stats.totalTasks') }}</span><strong>{{ stats.totalTasks }}</strong></div>
    </div>

    <div class="stats-grid">
      <section class="panel chart-panel">
        <div class="panel-heading">
          <h2>{{ t('admin.stats.distribution') }}</h2>
        </div>
        <div ref="chartRef" class="status-chart" />
      </section>
      <section class="panel table-panel table-panel--compact">
        <el-table :data="stats.taskStatusDistribution" height="360">
          <el-table-column :label="t('common.status')">
            <template #default="{ row }">{{ translateValue('metadataQcStatus', row.status || row.label) }}</template>
          </el-table-column>
          <el-table-column prop="count" :label="t('admin.stats.count')" width="120" />
        </el-table>
      </section>
    </div>
    <section class="panel table-panel" style="margin-top: 16px">
      <div class="panel-heading"><h2>{{ t('admin.stats.reviewerWorkload') }}</h2></div>
      <el-table :data="stats.reviewerWorkload">
        <el-table-column prop="reviewerName" :label="t('admin.stats.reviewer')" min-width="160" />
        <el-table-column prop="total" :label="t('admin.stats.totalReviewed')" width="130" />
        <el-table-column prop="approved" :label="t('admin.stats.approved')" width="130" />
        <el-table-column prop="rejected" :label="t('admin.stats.rejected')" width="130" />
      </el-table>
    </section>
  </AppShell>
</template>
