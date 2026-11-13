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

/**
 * Writes the counts of messages (`{n}`, `{count}`) as the locale writes numbers: vue-i18n puts
 * a plural count, and a number given as `n` or `count`, in as it is (`1234`, not `1,234`).
 */
function formatCounts(composer: { t: unknown; n: unknown }): void {
  const translate = composer.t as (...args: unknown[]) => string
  const number = composer.n as (value: number) => string
  const format = (value: unknown): unknown => (typeof value === 'number' ? number(value) : value)
  composer.t = (key: unknown, ...args: unknown[]): string => {
    const [first, second, ...rest] = args
    if (typeof first === 'number') {
      // t(key, plural) and t(key, plural, options): the plural count is the message's {n}.
      const named = { n: format(first), count: format(first) }
      if (typeof second === 'object' && second !== null) {
        return translate(key, named, { ...second, plural: first }, ...rest)
      }
      return translate(key, named, first, ...rest)
    }
    if (typeof first === 'object' && first !== null && !Array.isArray(first)) {
      const given = first as Record<string, unknown>
      const named = { ...given }
      if ('n' in given) named.n = format(given.n)
      if ('count' in given) named.count = format(given.count)
      // A plural count with named values: {n} and {count} default to it, formatted.
      if (typeof second === 'number') {
        named.n ??= format(second)
        named.count ??= format(second)
      }
      // Without one, vue-i18n takes the plural form from a numeric `n` or `count`.
      const counted = [given.count, given.n].find((value) => typeof value === 'number')
      if (args.length === 1 && counted !== undefined) return translate(key, named, counted)
      return translate(key, named, ...args.slice(1))
    }
    return translate(key, ...args)
  }
}

export function createAppI18n(locale: Locale = 'en') {
  const i18n = createI18n({
    legacy: false,
    locale,
    fallbackLocale: 'en',
    messages: { en },
  })
  formatCounts(i18n.global)
  return i18n
}
