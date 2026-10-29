import { defineStore } from 'pinia'
import { hasInjectionContext, inject } from 'vue'
import { I18nInjectionKey, type I18n } from 'vue-i18n'

import { createAppI18n } from '@/i18n'

// Pinia creates a setup store inside the app's injection context, so this gets the instance the
// components use (and follows its locale). Without an app (a test) it gets an English one.
const useTexts = defineStore('apiTexts', () => {
  const injected = hasInjectionContext() ? inject<I18n | null>(I18nInjectionKey, null) : null
  const i18n = injected ?? createAppI18n()
  const translate = i18n.global.t as (key: string, named?: Record<string, unknown>) => string
  return { translate }
})

/** A message of the API layer, for text that no component shows itself (toasts). */
export function text(key: string, named?: Record<string, unknown>): string {
  return useTexts().translate(key, named ?? {})
}
