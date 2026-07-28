<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppShell from '@/components/AppShell.vue'
import { adminApi } from '@/api'
import { translateValue } from '@/i18n'
import { useAdaptivePageSize } from '@/composables/useAdaptivePageSize'
import type { ProjectOption, UserAdmin } from '@/types'

const { t } = useI18n()
const { pageSize } = useAdaptivePageSize({ rowHeight: 49, headerHeight: 230, footerHeight: 76, safePadding: 48, minRows: 6 })
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const users = ref<UserAdmin[]>([])
const projects = ref<ProjectOption[]>([])
const selectedUser = ref<UserAdmin | null>(null)
const total = ref(0)
const query = reactive({ page: 1, size: pageSize.value, keyword: '', role: '', status: '' })
const form = reactive({ id: 0, userId: '', password: '', role: 'qc', status: 'active', projectIds: [] as number[] })

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / query.size)))
const pageStart = computed(() => (total.value ? (query.page - 1) * query.size + 1 : 0))
const pageEnd = computed(() => Math.min(total.value, query.page * query.size))
const activeUsers = computed(() => users.value.filter((user) => user.status === 'active').length)
const disabledUsers = computed(() => users.value.filter((user) => user.status === 'disabled').length)

async function load() {
  loading.value = true
  try {
    query.size = pageSize.value
    const { data } = await adminApi.users(query)
    users.value = data.data.records
    total.value = data.data.total
    selectedUser.value = users.value.find((user) => user.id === selectedUser.value?.id) || users.value[0] || null
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function loadProjectOptions() {
  const { data } = await adminApi.projectOptions()
  projects.value = data.data
}

function search() {
  query.page = 1
  void load()
}

function changePage(nextPage: number) {
  if (nextPage < 1 || nextPage > totalPages.value || nextPage === query.page) return
  query.page = nextPage
  void load()
}

function openCreate() {
  Object.assign(form, { id: 0, userId: '', password: '', role: 'qc', status: 'active', projectIds: [] })
  dialogVisible.value = true
}

function openEdit(row: UserAdmin) {
  if (row.role === 'super_admin') return
  Object.assign(form, {
    id: row.id,
    userId: row.userId,
    password: '',
    role: row.role,
    status: row.status,
    projectIds: [...row.projectIds],
  })
  dialogVisible.value = true
}

async function save() {
  if (form.role === 'qc' && form.status === 'active' && !form.projectIds.length) {
    ElMessage.warning(t('admin.users.projectRequired'))
    return
  }
  saving.value = true
  try {
    if (form.id) {
      await adminApi.updateUser(form.id, { role: form.role, status: form.status, projectIds: form.role === 'qc' ? form.projectIds : [] })
    } else {
      await adminApi.createUser({ userId: form.userId, password: form.password, role: form.role, projectIds: form.role === 'qc' ? form.projectIds : [] })
    }
    dialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    saving.value = false
  }
}

async function remove(row: UserAdmin) {
  await ElMessageBox.confirm(t('admin.users.deleteConfirm', { username: row.userId }), t('common.confirm'))
  await adminApi.deleteUser(row.id)
  await load()
}

async function resetPassword(row: UserAdmin) {
  const result = await ElMessageBox.prompt(t('admin.users.newPassword'), t('admin.users.resetPassword', { username: row.userId }), { inputType: 'password' })
  await adminApi.resetPassword(row.id, result.value)
  ElMessage.success(t('admin.users.resetDone'))
  await load()
}

watch(() => form.role, (role) => {
  if (role !== 'qc') form.projectIds = []
})

watch(pageSize, (value, oldValue) => {
  if (!oldValue || value === oldValue) return
  query.size = value
  query.page = 1
  void load()
})

onMounted(async () => {
  try {
    await Promise.all([load(), loadProjectOptions()])
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
})
</script>

<template>
  <AppShell>
    <div class="page-title">
      <div><h1>{{ t('admin.users.title') }}</h1><p>{{ t('admin.users.subtitle') }}</p></div>
      <el-button type="primary" :icon="'Plus'" @click="openCreate">{{ t('common.new') }}</el-button>
    </div>
    <div class="toolbar">
      <el-input v-model="query.keyword" :placeholder="t('admin.users.keyword')" style="width: 220px" clearable @keyup.enter="search" />
      <el-select v-model="query.role" :placeholder="t('admin.users.role')" style="width: 160px" clearable>
        <el-option :label="translateValue('roles', 'super_admin')" value="super_admin" />
        <el-option :label="translateValue('roles', 'admin')" value="admin" />
        <el-option :label="translateValue('roles', 'qc')" value="qc" />
      </el-select>
      <el-select v-model="query.status" :placeholder="t('admin.users.status')" style="width: 140px" clearable>
        <el-option :label="translateValue('userStatus', 'active')" value="active" />
        <el-option :label="translateValue('userStatus', 'disabled')" value="disabled" />
      </el-select>
      <el-button :icon="'Search'" @click="search">{{ t('common.search') }}</el-button>
    </div>

    <div class="workbench-grid">
      <section class="panel table-panel">
        <el-table v-loading="loading" :data="users" row-key="id" highlight-current-row class="adaptive-table" :height="pageSize * 49 + 49" @row-click="selectedUser = $event">
          <el-table-column prop="userId" :label="t('admin.users.username')" width="105" show-overflow-tooltip />
          <el-table-column :label="t('admin.users.status')" width="72"><template #default="{ row }">{{ translateValue('userStatus', row.status) }}</template></el-table-column>
          <el-table-column :label="t('admin.users.role')" width="85"><template #default="{ row }">{{ translateValue('roles', row.role) }}</template></el-table-column>
          <el-table-column :label="t('admin.users.projects')" min-width="100" show-overflow-tooltip><template #default="{ row }">{{ row.projectNames.join(', ') || '—' }}</template></el-table-column>
          <el-table-column :label="t('common.actions')" width="190" class-name="user-actions-column">
            <template #default="{ row }">
              <div class="user-row-actions">
                <el-button link type="primary" :disabled="row.role === 'super_admin'" @click.stop="openEdit(row)">{{ t('common.edit') }}</el-button>
                <el-button link @click.stop="resetPassword(row)">{{ t('common.password') }}</el-button>
                <el-button link type="danger" :disabled="row.role === 'super_admin'" @click.stop="remove(row)">{{ t('common.delete') }}</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
        <footer class="bottom-pager">
          <el-button :disabled="query.page <= 1" :icon="'ArrowLeft'" @click="changePage(query.page - 1)">{{ t('common.previousPage') }}</el-button>
          <span class="pager-status">{{ t('common.pageStatus', { page: query.page, pages: totalPages, total }) }}<small>{{ t('common.rangeStatus', { start: pageStart, end: pageEnd }) }}</small></span>
          <el-button :disabled="query.page >= totalPages" @click="changePage(query.page + 1)">{{ t('common.nextPage') }}<el-icon class="el-icon--right"><ArrowRight /></el-icon></el-button>
        </footer>
      </section>

      <aside class="panel metadata-panel">
        <template v-if="selectedUser">
          <p class="eyebrow">{{ t('admin.users.selectedTitle') }}</p>
          <h2>{{ selectedUser.userId }}</h2>
          <dl class="metadata-list">
            <div><dt>{{ t('admin.users.role') }}</dt><dd>{{ translateValue('roles', selectedUser.role) }}</dd></div>
            <div><dt>{{ t('admin.users.projects') }}</dt><dd>{{ selectedUser.projectNames.join(', ') || '—' }}</dd></div>
            <div><dt>{{ t('admin.users.status') }}</dt><dd>{{ translateValue('userStatus', selectedUser.status) }}</dd></div>
            <div><dt>{{ t('admin.users.createdAt') }}</dt><dd>{{ selectedUser.createdAt }}</dd></div>
            <div><dt>{{ t('admin.users.lastLoginAt') }}</dt><dd>{{ selectedUser.lastLoginAt || t('common.notFilled') }}</dd></div>
            <div><dt>{{ t('admin.users.mustChangePassword') }}</dt><dd>{{ selectedUser.mustChangePassword ? t('common.confirm') : '—' }}</dd></div>
          </dl>
        </template>
        <p v-else class="muted">{{ t('admin.users.emptyDetail') }}</p>
        <div class="metadata-metrics">
          <div><span>{{ t('admin.users.activeUsers') }}</span><strong>{{ activeUsers }}</strong></div>
          <div><span>{{ t('admin.users.disabledUsers') }}</span><strong>{{ disabledUsers }}</strong></div>
        </div>
      </aside>
    </div>

    <el-dialog v-model="dialogVisible" :title="form.id ? t('admin.users.editTitle') : t('admin.users.createTitle')" width="520px">
      <el-form :model="form" label-position="top">
        <el-form-item v-if="!form.id" :label="t('admin.users.username')"><el-input v-model="form.userId" /></el-form-item>
        <el-form-item v-if="!form.id" :label="t('auth.password')"><el-input v-model="form.password" type="password" show-password /></el-form-item>
        <el-form-item :label="t('admin.users.role')">
          <el-select v-model="form.role" style="width: 100%">
            <el-option :label="translateValue('roles', 'admin')" value="admin" />
            <el-option :label="translateValue('roles', 'qc')" value="qc" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.role === 'qc'" :label="t('admin.users.projects')">
          <el-select v-model="form.projectIds" multiple filterable style="width: 100%" :placeholder="t('admin.users.selectProjects')">
            <el-option v-for="project in projects" :key="project.id" :label="`${project.projectName} (${project.projectId})`" :value="project.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.id" :label="t('admin.users.status')">
          <el-radio-group v-model="form.status">
            <el-radio-button value="active">{{ translateValue('userStatus', 'active') }}</el-radio-button>
            <el-radio-button value="disabled">{{ translateValue('userStatus', 'disabled') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </AppShell>
</template>

<style scoped>
.user-row-actions {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  white-space: nowrap;
}

.user-row-actions .el-button {
  flex: 0 0 auto;
  margin-left: 0;
  padding-right: 0;
  padding-left: 0;
}
</style>
