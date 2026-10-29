import { describe, expect, it } from 'vitest'

import { en } from '@/i18n'

import { findLiteralText } from './literalText'
import { findMissingKeys } from './messageKeys'

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
})
