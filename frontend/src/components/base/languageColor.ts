import { computed } from 'vue'

import type { Language } from '@/api/types'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

import { findLanguage, isUndetermined } from './languages'

/** How many language colours the palette has (`--rf-lang-1` … `--rf-lang-8`). */
export const LANGUAGE_SLOTS = 8

/** A language colour: a slot of the palette, or the neutral one of an undetermined language. */
export type LanguageSlot = number | 'und'

/** One key per language: `en`, `eng` and `en-GB` share a colour, so do `pt` and `pt-BR`. */
export function languageKey(languages: readonly Language[], tag: string): string {
  const found = findLanguage(languages, tag)
  const base = found?.variant ? findLanguage(languages, tag.split(/[-_]/)[0]) : found
  return (base?.iso639_3 ?? base?.iso639_2b ?? tag.split(/[-_]/)[0] ?? tag).toLowerCase()
}

/** FNV-1a: the same language lands on the same slot in every session. */
function hash(text: string): number {
  let value = 0x811c9dc5
  for (const char of text) {
    value ^= char.codePointAt(0) ?? 0
    value = Math.imul(value, 0x01000193)
  }
  return value >>> 0
}

/**
 * The colour slot of a language. The preferred languages take the first slots in their order;
 * any other language takes a slot from its name, among those the preferred ones left free.
 */
export function languageSlot(
  tag: string | null | undefined,
  languages: readonly Language[],
  preferred: readonly string[],
): LanguageSlot {
  if (isUndetermined(tag)) return 'und'
  const key = languageKey(languages, tag ?? '')
  const order: string[] = []
  for (const each of preferred) {
    if (isUndetermined(each)) continue
    const preferredKey = languageKey(languages, each)
    if (!order.includes(preferredKey)) order.push(preferredKey)
    if (order.length === LANGUAGE_SLOTS) break
  }
  const index = order.indexOf(key)
  if (index >= 0) return index + 1
  const free = Array.from({ length: LANGUAGE_SLOTS }, (_, i) => i + 1).slice(order.length)
  const pool = free.length > 0 ? free : Array.from({ length: LANGUAGE_SLOTS }, (_, i) => i + 1)
  return pool[hash(key) % pool.length] ?? 1
}

/** The CSS colour of a slot. */
export function slotColor(slot: LanguageSlot): string {
  return `var(--rf-lang-${slot})`
}

/** A language's colour from the user's preferred languages (audio, then subtitles, then favourites). */
export function useLanguageColor(): (tag: string | null | undefined) => string {
  const settings = useSettingsStore()
  const system = useSystemStore()
  const preferred = computed(() => {
    const languages = settings.settings?.languages
    return [
      ...(languages?.preferred_audio ?? []),
      ...(languages?.preferred_subtitle ?? []),
      ...(languages?.favourites ?? []),
    ]
  })
  return (tag) => slotColor(languageSlot(tag, system.languages, preferred.value))
}
