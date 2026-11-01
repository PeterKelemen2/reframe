import { createI18n } from 'vue-i18n'

type AreaMessages = Record<string, unknown>

/**
 * One file per area (`messages/en/video.json` holds the `video.` keys), so that the areas of
 * the app never share a message file.
 */
const files = import.meta.glob<AreaMessages>(
  ['./messages/en/*.json', '!./messages/en/sandbox.json'],
  { eager: true, import: 'default' },
)
/** The dev-only sandbox's messages stay out of the production bundle with the sandbox. */
const devFiles = import.meta.env.DEV
  ? import.meta.glob<AreaMessages>('./messages/en/sandbox.json', { eager: true, import: 'default' })
  : {}

function byArea(modules: Record<string, AreaMessages>): Record<string, AreaMessages> {
  return Object.fromEntries(
    Object.entries(modules).map(([path, messages]) => [
      /([^/]+)\.json$/.exec(path)?.[1] ?? path,
      messages,
    ]),
  )
}

/** English is the source locale. Other locales must have the same keys. */
export const en = byArea({ ...files, ...devFiles })

export const SUPPORTED_LOCALES = ['en'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

export function createAppI18n(locale: Locale = 'en') {
  return createI18n({
    legacy: false,
    locale,
    fallbackLocale: 'en',
    messages: { en },
  })
}
