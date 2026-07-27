<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { translateValue, useAppLocale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import logo from '@/assets/lifewood-logo.jpg'

const auth = useAuthStore()
const router = useRouter()
const { t } = useI18n()
const { locale, toggleLocale } = useAppLocale()

const navItems = computed(() => {
  const role = auth.user?.role
  if (role === 'qc') {
    return [
      { to: '/qc/tasks', icon: 'Download', label: t('qc.pending') },
      { to: '/qc/my-tasks', icon: 'Finished', label: t('qc.mine') },
      { to: '/qc/completed', icon: 'CircleCheck', label: t('qc.completed') },
    ]
  }
  return [
    { to: '/admin/stats', icon: 'DataAnalysis', label: t('nav.stats') },
    { to: '/admin/users', icon: 'User', label: t('nav.users') },
    { to: '/admin/qc-tasks', icon: 'Unlock', label: t('nav.qcTasks') },
  ]
})

function logout() {
  auth.clear()
  router.push('/login')
}
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand-mini">
        <img :src="logo" alt="lifewood" />
      </div>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.to" :to="item.to" class="nav-item">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
    </aside>

    <main class="main">
      <header class="topbar">
        <div>
          <strong>{{ auth.user?.userId }}</strong>
          <span class="muted"> / {{ translateValue('roles', auth.user?.role) }}</span>
          <span v-if="auth.user?.mustChangePassword" class="muted"> · {{ t('auth.passwordChangeHint') }}</span>
        </div>
        <div class="topbar-actions">
          <el-button class="topbar-action-button topbar-action-button--language" :icon="'Connection'" @click="toggleLocale">{{ locale === 'zh-CN' ? t('common.languageEnglish') : t('common.languageChinese') }}</el-button>
          <el-button class="topbar-action-button" :icon="'SwitchButton'" @click="logout">{{ t('common.logout') }}</el-button>
        </div>
      </header>
      <section class="content">
        <slot />
      </section>
    </main>
  </div>
</template>
