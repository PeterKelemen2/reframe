import { describe, expect, it } from 'vitest'

import { findLiteralText } from './literalText'

function sfc(template: string): string {
  return `<script setup lang="ts">\nconst x = 'Not template text'\n</script>\n\n<template>\n${template}\n</template>\n`
}

function texts(template: string): string[] {
  return findLiteralText(sfc(template), 'Test.vue').map((found) => found.text)
}

describe('findLiteralText', () => {
  it('reports a text node with a letter, with its line', () => {
    const found = findLiteralText(sfc('<div>\n  <p>Save changes</p>\n</div>'), 'Test.vue')
    expect(found).toEqual([{ file: 'Test.vue', line: 7, where: 'text', text: 'Save changes' }])
  })

  it('reports text with a letter in any script, next to an interpolation', () => {
    expect(texts('<span>{{ count }} файлов</span>')).toEqual(['файлов'])
    expect(texts('<span>日本語</span>')).toEqual(['日本語'])
  })

  it('passes symbols, numbers and interpolations', () => {
    expect(texts('<p>{{ a }} · {{ b }} → 100 % × 2 — 3 ⓘ</p><!-- a comment -->')).toEqual([])
  })

  it('reports a static attribute that a user sees, on elements and components', () => {
    expect(
      texts(
        [
          '<img alt="Poster" />',
          '<span title="Info" aria-label="Close" aria-description="Closes it" />',
          '<input placeholder="Search" />',
          '<Button label="Save" />',
          '<Column header="Name" />',
          '<DataTable empty-message="Nothing" />',
          '<Tag value="Default" />',
        ].join('\n'),
      ),
    ).toEqual([
      'Poster',
      'Info',
      'Close',
      'Closes it',
      'Search',
      'Save',
      'Name',
      'Nothing',
      'Default',
    ])
  })

  it('passes attributes that are not shown, and shown ones without a letter', () => {
    expect(
      texts(
        [
          '<div class="card" id="main" data-view="queue" role="img" />',
          '<Button severity="secondary" icon="pi pi-check" type="button" label="+" />',
          '<input value="mkv" name="container" />',
          '<span title="—" />',
        ].join('\n'),
      ),
    ).toEqual([])
  })

  it('reports a string literal shown through {{ }}, a bound attribute or v-tooltip', () => {
    expect(
      texts(
        [
          "<p>{{ 'Hello' }}</p>",
          '<p>{{ ok ? t(\'a.b\') : "Fallback" }}</p>',
          '<Button :label="\'Save\'" />',
          '<span v-tooltip="\'Hint\'" />',
          '<p>{{ `${n} files` }}</p>',
        ].join('\n'),
      ),
    ).toEqual(['Hello', 'Fallback', 'Save', 'Hint', ' files'])
  })

  it('passes message keys, comparisons and literals in bindings that are not shown', () => {
    expect(
      texts(
        [
          "<p>{{ t('base.issues.none') }}</p>",
          "<p>{{ $t('a.b', { n: 1 }) }}</p>",
          "<p>{{ kind === 'audio' ? t('a') : t('b') }}</p>",
          "<Button :label=\"t('x.y')\" :aria-label=\"te('x.z') ? t('x.z') : name\" />",
          '<span :class="{ \'is-open\': open }" :data-kind="\'audio\'" />',
          '<p>{{ `${w}×${h}` }}</p>',
        ].join('\n'),
      ),
    ).toEqual([])
  })

  it('reads nothing outside the template, and nothing from a file without one', () => {
    expect(findLiteralText('<script setup lang="ts">\nconst a = 1\n</script>\n', 'A.vue')).toEqual(
      [],
    )
    expect(texts('<div />')).toEqual([])
  })
})
