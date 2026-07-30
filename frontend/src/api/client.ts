import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { i18n } from '@/i18n'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import type { ApiResponse } from '@/types'

const request = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

function localizedApiMessage(payload?: ApiResponse<unknown>) {
  const detail = payload?.data as
    | { errorKey?: string; errorParams?: Record<string, unknown> }
    | null
    | undefined
  if (detail?.errorKey) {
    const key = `admin.exports.errors.${detail.errorKey}`
    if (i18n.global.te(key)) {
      return i18n.global.t(key, detail.errorParams || {})
    }
  }
  return payload?.message
}

request.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

request.interceptors.response.use(
  (response) => {
    if (response.config.responseType === 'blob') return response
    const payload = response.data as ApiResponse<unknown>
    if (payload.code !== 0) {
      return Promise.reject(new Error(localizedApiMessage(payload) || i18n.global.t('errors.requestFailed')))
    }
    return response
  },
  (error: AxiosError<ApiResponse<unknown>>) => {
    const message =
      localizedApiMessage(error.response?.data) ||
      error.message ||
      i18n.global.t('errors.network')
    if (error.response?.status === 401) {
      const auth = useAuthStore()
      auth.clear()
      if (router.currentRoute.value.path !== '/login') {
        router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
      }
    }
    return Promise.reject(new Error(message))
  },
)

export default request

