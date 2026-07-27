<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api'
import { useAppLocale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import logoCn from '@/assets/lifewood-logo-cn.jpg'

const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n()
const { locale, toggleLocale } = useAppLocale()
const loading = ref(false)
const form = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })

function logout() {
  auth.clear()
  router.push('/login')
}

async function submit() {
  if (form.newPassword !== form.confirmPassword) {
    ElMessage.error(t('auth.passwordMismatch'))
    return
  }
  loading.value = true
  try {
    const { data } = await authApi.changePassword(form.oldPassword, form.newPassword)
    auth.setUser(data.data)
    ElMessage.success(t('auth.passwordChanged'))
    router.push(data.data.homePath || '/admin/stats')
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
        <img :src="logoCn" :alt="t('common.logoAlt')" />
        <h1>LWCam</h1>
        <p>{{ t('common.appSubtitle') }}</p>
      </div>
    </section>
    <section class="auth-form-wrap">
      <el-form class="auth-form" :model="form" label-position="top" @keyup.enter="submit">
        <div class="auth-language">
          <el-button text :icon="'Connection'" @click="toggleLocale">
            {{ locale === 'zh-CN' ? t('common.languageEnglish') : t('common.languageChinese') }}
          </el-button>
        </div>
        <h2>{{ t('auth.changePassword') }}</h2>
        <p class="hint">{{ t('auth.changePasswordHint') }}</p>
        <el-form-item :label="t('auth.oldPassword')">
          <el-input v-model="form.oldPassword" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item :label="t('auth.newPassword')">
          <el-input v-model="form.newPassword" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item :label="t('auth.confirmPassword')">
          <el-input v-model="form.confirmPassword" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-button type="primary" size="large" :loading="loading" style="width: 100%" @click="submit">
          {{ t('auth.changePassword') }}
        </el-button>
        <el-button size="large" style="width: 100%; margin: 12px 0 0" @click="logout">
          {{ t('common.logout') }}
        </el-button>
      </el-form>
    </section>
  </div>
</template>
