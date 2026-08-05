import { computed } from 'vue'
import { createI18n } from 'vue-i18n'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import zhCN from '@/i18n/locales/zh-CN'
import enUS from '@/i18n/locales/en-US'

export type AppLocale = 'zh-CN' | 'en-US'

export const i18n = createI18n({
  legacy: false,
  locale: 'en-US',
  fallbackLocale: 'en-US',
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
})

export function useAppLocale() {
  const locale = computed(() => i18n.global.locale.value as AppLocale)
  const elementLocale = computed(() => (locale.value === 'en-US' ? en : zhCn))

  return { locale, elementLocale }
}

export function translateValue(prefix: string, value: string | undefined | null) {
  if (!value) return ''
  const key = `${prefix}.${value}`
  const translated = i18n.global.t(key)
  return translated === key ? value : translated
}
