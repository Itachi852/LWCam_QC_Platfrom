<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import logo from '@/assets/lifewood-logo.jpg'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const { t } = useI18n()
const loading = ref(false)
const form = reactive({ username: 'admin', password: 'admin123' })

async function submit() {
  loading.value = true
  try {
    const { data } = await authApi.login(form)
    auth.setAuth(data.data.token, data.data.user)
    if (data.data.user.mustChangePassword) {
      router.push('/change-password')
      return
    }
    router.push((route.query.redirect as string) || data.data.user.homePath || '/admin/stats')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <section class="brand-panel">
      <div>
        <img :src="logo" :alt="t('common.logoAlt')" />
        <h1>LWCam</h1>
        <p>{{ t('common.appSubtitle') }}</p>
      </div>
    </section>
    <section class="auth-form-wrap">
      <el-form class="auth-form" :model="form" label-position="top" @keyup.enter="submit">
        <h2>{{ t('auth.login') }}</h2>
        <p class="hint">{{ t('auth.loginHint') }}</p>
        <el-form-item :label="t('auth.username')">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item :label="t('auth.password')">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-button type="primary" size="large" :loading="loading" style="width: 100%" @click="submit">{{ t('auth.login') }}</el-button>
        <p class="hint">{{ t('auth.accountManagedByAdmin') }}</p>
      </el-form>
    </section>
  </div>
</template>

