import { toRaw } from 'vue'

import type { Language } from '@/api/types'
import { findLanguage } from '@/components/base/languages'

export type Container = 'mkv' | 'mp4' | 'webm'

/** What a track gets: the English name, the ISO 639-2 code of the container and the BCP 47 tag. */
export interface WrittenAs {
  name: string
  iso639_2: string
  tag: string
}

/** MKV and WebM write ISO 639-2/B, MP4 writes ISO 639-2/T. */
export function writtenAs(language: Language, container: Container = 'mkv'): WrittenAs {
  return {
    name: language.english_name,
    iso639_2: container === 'mp4' ? language.iso639_2t : language.iso639_2b,
    tag: language.tag,
  }
}

/** Case- and accent-insensitive form for matching (`Français` → `francais`). */
export function fold(text: string): string {
  return text.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().trim()
}

// The shape `LanguageTag` accepts on the server.
const TAG_SHAPE = /^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$/
const SCRIPT = /^[A-Za-z]{4}$/
const REGION = /^([A-Za-z]{2}|\d{3})$/
// They name no script or region; the server would take them, but they say nothing.
const UNKNOWN = new Set(['Zzzz', 'ZZ'])

function displayName(type: 'script' | 'region', locale: string, code: string): string | undefined {
  try {
    return new Intl.DisplayNames([locale], { type, fallback: 'none' }).of(code)
  } catch {
    return undefined
  }
}

/** `at` → `AT`, `DD` → `DE`, `999` → `ZZ`: the region as it is canonical. */
function canonicalRegion(region: string): string {
  try {
    return new Intl.Locale(Intl.getCanonicalLocales(`und-${region}`)[0] ?? '').region ?? region
  } catch {
    return region
  }
}

function withSubtags(name: string, parts: (string | undefined)[]): string {
  const shown = parts.filter((part): part is string => part !== undefined)
  return shown.length > 0 ? `${name} (${shown.join(', ')})` : name
}

/**
 * The language of a typed code or tag (`hun`, `ger-AT`, `pt_br`, `zh-hans-tw`): a listed
 * entry, or one made from a listed base language with a known script and region. `undefined`
 * for anything else, variant and extension subtags included.
 */
export function resolveTag(languages: readonly Language[], text: string): Language | undefined {
  const typed = text.trim().replaceAll('_', '-')
  if (!TAG_SHAPE.test(typed) || typed.length > 64) return undefined
  const listed = findLanguage(languages, typed)
  if (listed) return listed
  const [primary = '', ...rest] = typed.split('-')
  const base = findLanguage(languages, primary)
  if (!base || base.variant || rest.length === 0 || rest.length > 2) return undefined

  let script: string | undefined
  let region: string | undefined
  const next = rest[0] ?? ''
  if (SCRIPT.test(next)) {
    script = next.charAt(0).toUpperCase() + next.slice(1).toLowerCase()
    rest.shift()
  }
  if (rest.length > 0) {
    const candidate = rest.shift() ?? ''
    if (!REGION.test(candidate)) return undefined
    region = canonicalRegion(candidate)
  }
  if (rest.length > 0) return undefined
  if (script !== undefined && (UNKNOWN.has(script) || !displayName('script', 'en', script))) {
    return undefined
  }
  if (region !== undefined && (UNKNOWN.has(region) || !displayName('region', 'en', region))) {
    return undefined
  }

  const tag = [base.tag, script, region].filter(Boolean).join('-')
  const again = findLanguage(languages, tag)
  if (again) return again
  const nativeLocale = (() => {
    try {
      return Intl.getCanonicalLocales(tag)[0] ?? 'en'
    } catch {
      return 'en'
    }
  })()
  const native = (type: 'script' | 'region', code: string | undefined) =>
    code === undefined ? undefined : (displayName(type, nativeLocale, code) ?? code)
  return {
    ...base,
    tag,
    english_name: withSubtags(base.english_name, [
      script && displayName('script', 'en', script),
      region && displayName('region', 'en', region),
    ]),
    native_name: withSubtags(base.native_name, [
      native('script', script),
      native('region', region),
    ]),
    variant: true,
  }
}

/** A tag as the picker shows it: listed, made from its subtags, or `undefined` (shown raw). */
export function describeTag(
  languages: readonly Language[],
  tag: string | null | undefined,
): Language | undefined {
  return tag ? resolveTag(languages, tag) : undefined
}

interface Searchable {
  tag: string
  codes: Set<string>
  english: string
  native: string
  words: string[]
}

const searchables = new WeakMap<Language, Searchable>()
const WORD_SPLIT = /[\s()\-,/（）、，]+/u

function searchable(language: Language): Searchable {
  const raw = toRaw(language)
  let found = searchables.get(raw)
  if (found) return found
  const english = fold(raw.english_name)
  const native = fold(raw.native_name)
  const codes = [raw.iso639_1, raw.iso639_2b, raw.iso639_2t, raw.iso639_3]
  found = {
    tag: raw.tag.toLowerCase(),
    codes: new Set(codes.filter((code): code is string => code !== null)),
    english,
    native,
    words: [english, native].flatMap((name) => name.split(WORD_SPLIT)).filter(Boolean),
  }
  searchables.set(raw, found)
  return found
}

/** Best first: the tag, an ISO code, an exact name, a name prefix, a word prefix, a substring. */
function rank(language: Language, folded: string, typedTag: string | undefined): number {
  const s = searchable(language)
  if (language.tag === typedTag || folded === s.tag) return 0
  if (s.codes.has(folded)) return 1
  if (folded === s.english) return 2
  if (folded === s.native) return 3
  if (s.english.startsWith(folded) || s.native.startsWith(folded)) return 4
  if (s.words.some((word) => word.startsWith(folded))) return 5
  if (s.english.includes(folded) || s.native.includes(folded)) return 6
  return -1
}

export interface SearchResult {
  /** The favourites that match, in the order of the settings. */
  favourites: Language[]
  others: Language[]
}

/**
 * The picker's search. An empty query gives every favourite, then every other language in
 * list order. A typed tag whose base language is listed (`de-AT`) adds an entry for it.
 * `exclude` hides languages by tag (an ordered list's members).
 */
export function searchLanguages(
  languages: readonly Language[],
  query: string,
  favouriteTags: readonly string[] = [],
  exclude: readonly string[] = [],
): SearchResult {
  const excluded = new Set(
    exclude.map((tag) => describeTag(languages, tag)?.tag ?? tag.toLowerCase()),
  )
  const favourites: Language[] = []
  for (const tag of favouriteTags) {
    const language = describeTag(languages, tag)
    if (language && !favourites.some((f) => f.tag === language.tag)) favourites.push(language)
  }
  const favouriteIndex = new Map(favourites.map((language, index) => [language.tag, index]))
  const shown = (language: Language) => !excluded.has(language.tag)

  const text = query.trim()
  if (text === '') {
    return {
      favourites: favourites.filter(shown),
      others: languages.filter((l) => !favouriteIndex.has(l.tag) && shown(l)),
    }
  }

  const folded = fold(text)
  const typed = resolveTag(languages, text)
  const pool = [...favourites, ...languages.filter((l) => !favouriteIndex.has(l.tag))]
  if (typed && !pool.some((l) => l.tag === typed.tag)) pool.push(typed)
  const scored = pool
    .filter(shown)
    .map((language) => ({ language, rank: rank(language, folded, typed?.tag) }))
    .filter((entry) => entry.rank >= 0)
  scored.sort(
    (a, b) =>
      a.rank - b.rank ||
      (favouriteIndex.get(a.language.tag) ?? 0) - (favouriteIndex.get(b.language.tag) ?? 0) ||
      searchable(a.language).english.localeCompare(searchable(b.language).english) ||
      a.language.tag.localeCompare(b.language.tag),
  )
  const matched = scored.map((entry) => entry.language)
  return {
    favourites: matched.filter((l) => favouriteIndex.has(l.tag)),
    others: matched.filter((l) => !favouriteIndex.has(l.tag)),
  }
}
