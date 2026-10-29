import { toRaw } from 'vue'

import type { Language } from '@/api/types'

/** Tags that name no language: shown as undetermined. */
const UNDETERMINED = new Set(['', 'und'])

const indexes = new WeakMap<readonly Language[], Map<string, Language>>()

/** Every tag and ISO 639 code of the list, lower case; a base language wins over its variants. */
function indexOf(languages: readonly Language[]): Map<string, Language> {
  const raw = toRaw(languages)
  let index = indexes.get(raw)
  if (index) return index
  index = new Map()
  const ordered = [...raw.filter((l) => !l.variant), ...raw.filter((l) => l.variant)]
  for (const language of ordered) {
    const codes = [
      language.tag,
      language.iso639_1,
      language.iso639_2b,
      language.iso639_2t,
      language.iso639_3,
    ]
    for (const code of codes) {
      const key = code?.toLowerCase()
      if (key && !index.has(key)) index.set(key, language)
    }
  }
  indexes.set(raw, index)
  return index
}

export function isUndetermined(tag: string | null | undefined): boolean {
  return UNDETERMINED.has((tag ?? '').trim().toLowerCase())
}

/** The language of a BCP 47 tag or an ISO 639 code (`hu`, `hun`, `pt-BR`), if the list has it. */
export function findLanguage(
  languages: readonly Language[],
  tag: string | null | undefined,
): Language | undefined {
  if (isUndetermined(tag)) return undefined
  return indexOf(languages).get((tag ?? '').trim().toLowerCase())
}
