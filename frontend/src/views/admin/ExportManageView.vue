<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppShell from '@/components/AppShell.vue'
import { adminApi } from '@/api'
import type { ExportPreflight, ExportRun } from '@/types'

const { t } = useI18n()
const loading = ref(false)
const running = ref(false)
const preflight = ref<ExportPreflight>()
const current = ref<ExportRun>()
const runs = ref<ExportRun[]>([])
let pollTimer: number | undefined

const isActive = computed(() => ['QUEUED', 'RUNNING'].includes(current.value?.status || ''))
const canRun = computed(() =>
  Boolean(preflight.value?.ready && preflight.value.eligibleCount > 0 && !isActive.value),
)
const canRetry = computed(() =>
  Boolean(!isActive.value && current.value?.items.some((item) => item.status === 'FAILED')),
)
const progress = computed(() => {
  if (!current.value?.total) return 0
  return Math.round(((current.value.succeeded + current.value.failed) * 100) / current.value.total)
})

async function loadAll() {
  loading.value = true
  try {
    const [preflightResult, runsResult] = await Promise.all([
      adminApi.exportPreflight(),
      adminApi.exportRuns(),
    ])
    preflight.value = preflightResult.data.data
    current.value = preflight.value.activeRun
    runs.value = runsResult.data.data
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function poll() {
  try {
    const { data } = await adminApi.currentExport()
    current.value = data.data || undefined
    if (!isActive.value) {
      const [preflightResult, runsResult] = await Promise.all([
        adminApi.exportPreflight(),
        adminApi.exportRuns(),
      ])
      preflight.value = preflightResult.data.data
      runs.value = runsResult.data.data
    }
  } catch {
    // The next poll or manual refresh will retry.
  }
}

async function startExport() {
  try {
    await ElMessageBox.confirm(
      t('admin.exports.runConfirm', { count: preflight.value?.eligibleCount || 0 }),
      t('admin.exports.run'),
      { type: 'warning' },
    )
  } catch {
    return
  }
  running.value = true
  try {
    const { data } = await adminApi.runExport()
    current.value = data.data
    ElMessage.success(t('admin.exports.started'))
  } catch (error) {
    ElMessage.error((error as Error).message)
    await loadAll()
  } finally {
    running.value = false
  }
}

async function retryFailed() {
  running.value = true
  try {
    const { data } = await adminApi.retryExport()
    current.value = data.data
    ElMessage.success(t('admin.exports.started'))
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    running.value = false
  }
}

function formatDate(value?: string) {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

onMounted(() => {
  void loadAll()
  pollTimer = window.setInterval(() => void poll(), 3000)
})

onBeforeUnmount(() => {
  if (pollTimer !== undefined) window.clearInterval(pollTimer)
})
</script>

<template>
  <AppShell>
    <div class="page-title">
      <div>
        <h1>{{ t('admin.exports.title') }}</h1>
        <p>{{ t('admin.exports.subtitle') }}</p>
      </div>
      <el-button :icon="'Refresh'" :loading="loading" @click="loadAll">{{ t('common.refresh') }}</el-button>
    </div>

    <el-alert
      v-if="preflight && !preflight.ready"
      type="error"
      :title="t('admin.exports.notReady')"
      :description="preflight.errors.join('；')"
      show-icon
      :closable="false"
    />

    <div class="metric-grid export-metrics">
      <div class="metric accent">
        <span>{{ t('admin.exports.eligible') }}</span><strong>{{ preflight?.eligibleCount || 0 }}</strong>
      </div>
      <div class="metric">
        <span>{{ t('admin.exports.status') }}</span><strong class="status-text">{{ current?.status || 'IDLE' }}</strong>
      </div>
      <div class="metric green">
        <span>{{ t('admin.exports.succeeded') }}</span><strong>{{ current?.succeeded || 0 }}</strong>
      </div>
      <div class="metric">
        <span>{{ t('admin.exports.failed') }}</span><strong>{{ current?.failed || 0 }}</strong>
      </div>
    </div>

    <section class="panel action-panel">
      <div>
        <h2>{{ t('admin.exports.batch') }}</h2>
        <p v-if="preflight?.config">
          {{ preflight.config.csvEncoding }} / {{ preflight.config.csvLineEnding }} ·
          {{ preflight.config.outputDir }}
        </p>
      </div>
      <div class="actions">
        <el-button :disabled="!canRetry" :loading="running" @click="retryFailed">
          {{ t('admin.exports.retry') }}
        </el-button>
        <el-button type="primary" :disabled="!canRun" :loading="running" @click="startExport">
          {{ t('admin.exports.run') }}
        </el-button>
      </div>
      <el-progress v-if="current" :percentage="progress" :status="current.failed ? 'exception' : undefined" />
    </section>

    <section v-if="current?.items?.length" class="panel table-panel">
      <div class="panel-heading"><h2>{{ t('admin.exports.currentItems') }}</h2></div>
      <el-table :data="current.items" max-height="360">
        <el-table-column prop="folderId" label="Folder ID" width="110" />
        <el-table-column prop="status" :label="t('admin.exports.status')" width="130" />
        <el-table-column prop="groupId" label="Group ID" min-width="220" />
        <el-table-column prop="zipPath" label="ZIP" min-width="260" show-overflow-tooltip />
        <el-table-column prop="error" :label="t('admin.exports.error')" min-width="260" show-overflow-tooltip />
      </el-table>
    </section>

    <section class="panel table-panel">
      <div class="panel-heading"><h2>{{ t('admin.exports.history') }}</h2></div>
      <el-table :data="runs" max-height="320">
        <el-table-column prop="runId" label="Run ID" min-width="240" show-overflow-tooltip />
        <el-table-column prop="status" :label="t('admin.exports.status')" width="150" />
        <el-table-column prop="createdBy" :label="t('admin.exports.createdBy')" width="140" />
        <el-table-column :label="t('admin.exports.createdAt')" min-width="180">
          <template #default="{ row }">{{ formatDate(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column prop="total" :label="t('admin.exports.total')" width="90" />
        <el-table-column prop="succeeded" :label="t('admin.exports.succeeded')" width="90" />
        <el-table-column prop="failed" :label="t('admin.exports.failed')" width="90" />
      </el-table>
    </section>
  </AppShell>
</template>

<style scoped>
.page-title,
.action-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}
.page-title { margin-bottom: 20px; }
.page-title h1 { margin: 0 0 6px; font-size: 28px; }
.page-title p, .action-panel p { margin: 0; color: var(--el-text-color-secondary); }
.export-metrics { margin: 20px 0; }
.status-text { font-size: 20px !important; }
.action-panel { padding: 22px 24px; margin-bottom: 20px; flex-wrap: wrap; }
.action-panel h2 { margin: 0 0 8px; }
.action-panel .el-progress { flex-basis: 100%; }
.actions { display: flex; gap: 10px; }
.table-panel { margin-bottom: 20px; overflow: hidden; }
.panel-heading { padding: 18px 22px; border-bottom: 1px solid var(--el-border-color-lighter); }
.panel-heading h2 { margin: 0; font-size: 18px; }
</style>
