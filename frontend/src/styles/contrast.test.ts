import PrimeVue from 'primevue/config'
import InputText from 'primevue/inputtext'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { type App, createApp, h } from 'vue'

import { DARK_MODE_CLASS, ReframePreset } from './theme'

type Scheme = 'light' | 'dark'

let app: App | undefined
const variables: Record<Scheme, Map<string, string>> = { light: new Map(), dark: new Map() }

/** The `--p-*` declarations PrimeVue writes for our preset: `:root` (light) and the dark class. */
beforeAll(() => {
  app = createApp({ render: () => h(InputText) })
  app.use(PrimeVue, {
    theme: { preset: ReframePreset, options: { darkModeSelector: `.${DARK_MODE_CLASS}` } },
  })
  app.mount(document.createElement('div'))
  const css = [...document.head.querySelectorAll('style[data-primevue-style-id]')]
    .map((style) => style.textContent ?? '')
    .join('\n')
  for (const [, selector = '', body = ''] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const scheme: Scheme | null = selector.includes(`.${DARK_MODE_CLASS}`)
      ? 'dark'
      : selector.includes(':root')
        ? 'light'
        : null
    if (scheme === null) continue
    for (const [, name = '', value = ''] of body.matchAll(/(--p-[\w-]+)\s*:\s*([^;]+)/g)) {
      variables[scheme].set(name, value.trim())
    }
  }
})

afterAll(() => app?.unmount())

function resolve(name: string, scheme: Scheme, depth = 0): string {
  const value =
    (scheme === 'dark' ? variables.dark.get(name) : undefined) ?? variables.light.get(name)
  if (value === undefined) throw new Error(`${name} is not defined`)
  const reference = /^var\((--p-[\w-]+)\)$/.exec(value)
  if (reference?.[1] && depth < 20) return resolve(reference[1], scheme, depth + 1)
  return value
}

function luminance(color: string): number {
  const hex = /^#([\da-f]{6})$/i.exec(color)?.[1]
  if (!hex) throw new Error(`not a solid colour: ${color}`)
  const [r = 0, g = 0, b = 0] = [0, 2, 4].map((i) => {
    const c = Number.parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.040_45 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(foreground: string, background: string, scheme: Scheme): number {
  const a = luminance(resolve(`--p-${foreground}`, scheme))
  const b = luminance(resolve(`--p-${background}`, scheme))
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

const SURFACES = ['content-background', 'app-background']
const TONES = ['error', 'warn', 'info', 'ok', 'busy', 'off']

/** WCAG AA: 4.5:1 for text. */
const TEXT_PAIRS: [string, string][] = [
  ...SURFACES.flatMap((bg): [string, string][] => [
    ['text-color', bg],
    ['text-muted-color', bg],
    ['primary-color', bg],
    ...TONES.map((tone): [string, string] => [`status-${tone}-color`, bg]),
  ]),
  ['primary-contrast-color', 'primary-color'],
  ['form-field-color', 'form-field-background'],
  ['form-field-placeholder-color', 'form-field-background'],
  ...TONES.flatMap((tone): [string, string][] => [
    [`status-${tone}-color`, `status-${tone}-background`],
    ['text-color', `status-${tone}-background`],
    ['primary-color', `status-${tone}-background`],
  ]),
]

/** WCAG AA: 3:1 for the parts of a control and for graphics (1.4.11). */
const GRAPHIC_PAIRS: [string, string][] = [
  ['form-field-border-color', 'form-field-background'],
  ['form-field-invalid-border-color', 'form-field-background'],
  ...SURFACES.flatMap((bg) =>
    TONES.map((tone): [string, string] => [`status-${tone}-border-color`, bg]),
  ),
]

describe.each(['light', 'dark'] as const)('the %s colours', (scheme) => {
  it('give text at least 4.5:1', () => {
    const low = TEXT_PAIRS.map(([fg, bg]) => [`${fg} on ${bg}`, contrast(fg, bg, scheme)] as const)
      .filter(([, ratio]) => ratio < 4.5)
      .map(([pair, ratio]) => `${pair}: ${ratio.toFixed(2)}`)
    expect(low).toEqual([])
  })

  it('give borders and marks at least 3:1', () => {
    const low = GRAPHIC_PAIRS.map(
      ([fg, bg]) => [`${fg} on ${bg}`, contrast(fg, bg, scheme)] as const,
    )
      .filter(([, ratio]) => ratio < 3)
      .map(([pair, ratio]) => `${pair}: ${ratio.toFixed(2)}`)
    expect(low).toEqual([])
  })
})
