import { describe, expect, it } from 'vitest'

import { findMissingKeys } from './messageKeys'

const messages = {
  base: {
    issues: { none: 'No issues', show: 'Show' },
    role: { main: 'Main' },
  },
}

function missing(source: string): string[] {
  return findMissingKeys(source, 'a.ts', messages).map((m) => `${m.key}:${m.problem}`)
}

describe('findMissingKeys', () => {
  it('reports a key that no message file has, with its line', () => {
    expect(findMissingKeys("const a = 1\nt('base.issues.nope')", 'a.ts', messages)).toEqual([
      { file: 'a.ts', line: 2, key: 'base.issues.nope', problem: 'missing' },
    ])
  })

  it('passes keys that exist, and only those', () => {
    expect(missing('t(\'base.issues.none\'); t("base.issues.show", { n: 1 })')).toEqual([])
    expect(missing("t('base.constructor'); t('base.issues.toString')")).toEqual([
      'base.constructor:missing',
      'base.issues.toString:missing',
    ])
  })

  it('reads t, $t, te and <i18n-t keypath>', () => {
    expect(
      missing(
        [
          '{{ $t("base.gone") }}',
          "te('base.absent')",
          '<i18n-t keypath="base.away" />',
          'i18n.global.t(`base.elsewhere`)',
        ].join('\n'),
      ),
    ).toEqual([
      'base.gone:missing',
      'base.absent:missing',
      'base.elsewhere:missing',
      'base.away:missing',
    ])
  })

  it('reports a key that names a group of messages, except for tm', () => {
    expect(missing("t('base.role')")).toEqual(['base.role:not a message'])
    expect(missing("tm('base.role')")).toEqual([])
    expect(missing("tm('base.role.main')")).toEqual(['base.role.main:not a message'])
  })

  it('ignores keys built at run time and calls that are not t', () => {
    expect(
      missing(
        [
          "t('base.' + area)",
          't(`base.${area}.title`)',
          't(key)',
          "store.set('/appearance/theme', value)",
          "emit('update')",
          "format('x.y')",
        ].join('\n'),
      ),
    ).toEqual([])
  })
})
