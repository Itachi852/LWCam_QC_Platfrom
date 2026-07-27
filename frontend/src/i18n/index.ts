import { computed } from 'vue'
import { createI18n } from 'vue-i18n'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import zhCN from '@/i18n/locales/zh-CN'
import enUS from '@/i18n/locales/en-US'

export type AppLocale = 'zh-CN' | 'en-US'

const STORAGE_KEY = 'lwcam-locale'

function initialLocale(): AppLocale {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'zh-CN' || stored === 'en-US') return stored
  return 'zh-CN'
}

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale(),
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
})

export function useAppLocale() {
  const locale = computed(() => i18n.global.locale.value as AppLocale)
  const elementLocale = computed(() => (locale.value === 'en-US' ? en : zhCn))

  function setLocale(value: AppLocale) {
    i18n.global.locale.value = value
    localStorage.setItem(STORAGE_KEY, value)
  }

  function toggleLocale() {
    setLocale(locale.value === 'zh-CN' ? 'en-US' : 'zh-CN')
  }

  return { locale, elementLocale, setLocale, toggleLocale }
}

export function translateValue(prefix: string, value: string | undefined | null) {
  if (!value) return ''
  const key = `${prefix}.${value}`
  const translated = i18n.global.t(key)
  return translated === key ? value : translated
}
