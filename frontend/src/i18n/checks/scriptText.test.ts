import { describe, expect, it } from 'vitest'

import { findScriptText } from './scriptText'

function found(code: string, file = 'a.ts'): string[] {
  return findScriptText(code, file).map((f) => `${f.line} ${f.where} ${f.text}`)
}

describe('findScriptText', () => {
  it('reports a toast, a menu item and a PrimeVue option written as a literal, with its line', () => {
    expect(
      found(
        [
          "toasts.push({ severity: 'error', summary: 'Saved', detail: `${n} files` })",
          "const items = [{ label: 'Open', command: open }]",
          "const pt = { root: { 'aria-label': 'Close' } }",
        ].join('\n'),
      ),
    ).toEqual(['1 summary: Saved', '1 detail: … files', '2 label: Open', '3 aria-label: Close'])
  })

  it('passes translated text, names written like code, symbols and other keys', () => {
    expect(
      found(
        [
          "toasts.push({ severity: 'error', summary: t('a.saved'), detail: name })",
          "const tones = { title: 'title', label: 'audio_codec' }",
          "const x = { separator: ' · ', value: 'Main', label: '→ 2' }",
        ].join('\n'),
      ),
    ).toEqual([])
  })

  it('looks into the branches of a conditional, a fallback and a concatenation', () => {
    expect(
      found("x = { summary: ok ? 'Done' : t('a.failed'), detail: d ?? 'None' + '!' }"),
    ).toEqual(['1 summary: Done', '1 detail: None'])
  })

  it('reports an accessible name, a title or a text set on an element in code', () => {
    expect(
      found(
        [
          "el.setAttribute('aria-label', 'Play')",
          "el.setAttribute('data-x', 'Play')",
          "el.title = 'More'",
          'el.ariaValueText = `${p} percent`',
          "el.textContent = 'Ready'",
          "el.className = 'Ready'",
          "window.alert('Oops')",
        ].join('\n'),
      ),
    ).toEqual([
      '1 setAttribute(aria-label) Play',
      '3 .title = More',
      '4 .ariaValueText = … percent',
      '5 .textContent = Ready',
      '7 alert() Oops',
    ])
  })

  it('reports text joined from translated pieces in a fixed order', () => {
    expect(
      found(
        [
          "a = t('x.one') + ': ' + t('x.two')",
          'b = `${t("x.one")} files`',
          "c = [t('x.one'), t('x.two')].join(' · ')",
          "d = t('x.one') + suffix",
          "e = [t('x.one'), other].join(', ')",
        ].join('\n'),
      ).map((line) => line.split(' ').slice(0, 2).join(' ')),
    ).toEqual(['1 joined', '2 joined', '3 joined'])
  })

  it('reports a number written with toFixed where it becomes text, and only there', () => {
    expect(
      found(
        [
          "a = t('u.mib', { value: (b / 1024).toFixed(1) })",
          'b = `${size.toFixed(3)} s`',
          'c = Number(x.toFixed(6))',
          'd = `${ratio.toFixed(2)}:1`',
        ].join('\n'),
      ),
    ).toEqual(['1 number (b / 1024).toFixed(1)', '2 number size.toFixed(3)'])
  })

  it("reports a number written with toPrecision or the browser's locale", () => {
    expect(
      found(
        [
          "a = t('u.x', { value: ratio.toPrecision(3) })",
          "b = t('u.x', { value: bytes.toLocaleString() })",
          "c = t('u.x', { value: bytes.toLocaleString(locale.value) })",
        ].join('\n'),
      ),
    ).toEqual(['1 number ratio.toPrecision(3)', '2 number bytes.toLocaleString()'])
  })

  it('reports values a template joins in a fixed order, but not data separators', () => {
    const sfc = [
      '<template>',
      '  <p><span>{{ chip.label }}: {{ chip.value }}</span></p>',
      "  <span>{{ t('x.rule') }} {{ row.number }}</span>",
      '  <span>{{ a }} · {{ b }}</span>',
      '  <span>{{ width }}×{{ height }}</span>',
      "  <span>{{ t('x.failed') }} {{ ok ? t('x.one') : t('x.two') }}</span>",
      '  <span>{{ first }} {{ second }}</span>',
      '</template>',
    ].join('\n')
    expect(found(sfc, 'A.vue')).toEqual([
      '2 joined {{ chip.label }}: {{ chip.value }}',
      "3 joined {{ t('x.rule') }} {{ row.number }}",
    ])
  })

  it('reports an InputNumber without the app locale', () => {
    const sfc = [
      '<template>',
      '  <InputNumber v-model="a" :locale="locale" />',
      '  <InputNumber v-model="b" locale="en" />',
      '  <InputNumber v-model="c" />',
      '</template>',
    ].join('\n')
    expect(found(sfc, 'A.vue')).toEqual(['4 InputNumber no :locale'])
  })

  it("reads a component's scripts and bound template expressions, at their lines in the file", () => {
    const sfc = [
      '<script setup lang="ts">',
      "const items = [{ label: 'Open' }]",
      '</script>',
      '',
      '<template>',
      '  <Menu :model="items" :pt="{ root: { \'aria-label\': \'Actions\' } }" />',
      '  <span>{{ value.toFixed(1) }}</span>',
      '</template>',
    ].join('\n')
    expect(found(sfc, 'A.vue')).toEqual([
      '2 label: Open',
      '6 aria-label: Actions',
      '7 number value.toFixed(1)',
    ])
  })
})
