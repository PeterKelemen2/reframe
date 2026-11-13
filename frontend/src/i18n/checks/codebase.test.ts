import { describe, expect, it } from 'vitest'

import { en } from '@/i18n'

import { ALLOWED_SCRIPT_TEXT } from './allowed'
import { findLiteralText } from './literalText'
import { findMissingKeys } from './messageKeys'
import { findScriptText, type ScriptText } from './scriptText'

const components = import.meta.glob<string>('/src/**/*.vue', {
  query: '?raw',
  import: 'default',
  eager: true,
})

// Tests and these checks hold bad keys on purpose.
const scripts = import.meta.glob<string>(
  ['/src/**/*.ts', '!/src/**/*.test.ts', '!/src/**/*.d.ts', '!/src/i18n/checks/**'],
  { query: '?raw', import: 'default', eager: true },
)

/** Test helpers hold sample data, never shown by the app. */
const TEST_HELPER = /(^|\/)testing(\/|\.ts$)|[A-Za-z]Testing\.ts$/

function key(found: Omit<ScriptText, 'line'>): string {
  return `${found.file} ${found.where} ${found.text}`
}

describe('the code base', () => {
  it('has no literal user-visible text in a template', () => {
    expect(Object.keys(components).length).toBeGreaterThan(20)
    const found = Object.entries(components).flatMap(([file, source]) =>
      findLiteralText(source, file),
    )
    expect(found.map((f) => `${f.file}:${f.line} ${f.where}: ${f.text}`)).toEqual([])
  })

  it('uses only message keys that the English messages have', () => {
    expect(Object.keys(scripts).length).toBeGreaterThan(20)
    const found = Object.entries({ ...components, ...scripts }).flatMap(([file, source]) =>
      findMissingKeys(source, file, en),
    )
    expect(found.map((f) => `${f.file}:${f.line} ${f.key} (${f.problem})`)).toEqual([])
  })

  it('builds no user-visible text in code without vue-i18n, but for the allowed findings', () => {
    const found = Object.entries({ ...components, ...scripts })
      .filter(([file]) => !TEST_HELPER.test(file))
      .flatMap(([file, source]) => findScriptText(source, file))
    const allowed = ALLOWED_SCRIPT_TEXT.map(key)
    const unlisted = found.filter((f) => {
      const index = allowed.indexOf(key(f))
      if (index === -1) return true
      allowed.splice(index, 1)
      return false
    })
    expect(unlisted.map((f) => `${f.file}:${f.line} ${f.where} ${f.text}`)).toEqual([])
    expect(allowed, 'allowed findings that no longer happen: remove them').toEqual([])
  })
})
