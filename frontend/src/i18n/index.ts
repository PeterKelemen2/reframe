import { createI18n } from 'vue-i18n'

import en from './locales/en.json'

/** English is the source locale. Other locales must have the same keys. */
export type MessageSchema = typeof en

export const SUPPORTED_LOCALES = ['en'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

export function createAppI18n(locale: Locale = 'en') {
  return createI18n<[MessageSchema], Locale>({
    legacy: false,
    locale,
    fallbackLocale: 'en',
    messages: { en },
  })
}
