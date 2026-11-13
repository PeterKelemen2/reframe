import Button from 'primevue/button'
import PrimeVue from 'primevue/config'
import InputText from 'primevue/inputtext'
import Listbox from 'primevue/listbox'
import Message from 'primevue/message'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import Slider from 'primevue/slider'
import Tag from 'primevue/tag'
import Toast from 'primevue/toast'
import ToggleSwitch from 'primevue/toggleswitch'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { type App, type Component, createApp, h } from 'vue'

import { DARK_MODE_CLASS, ReframePreset } from './theme'

type Scheme = 'light' | 'dark'
interface Rgba {
  r: number
  g: number
  b: number
  a: number
}

/** PrimeVue writes a component's `--p-<component>-*` variables when the component first mounts. */
const COMPONENTS: [Component, Record<string, unknown>?][] = [
  [InputText],
  [Button],
  [Toast],
  [Message],
  [Tag],
  // Its options are toggle buttons, which have variables of their own.
  [SelectButton, { options: ['a', 'b'] }],
  [ToggleSwitch],
  [Slider],
  [Select],
  [Listbox],
]

let app: App | undefined
const variables: Record<Scheme, Map<string, string>> = { light: new Map(), dark: new Map() }

/** The `--p-*` declarations PrimeVue writes for our preset: `:root` (light) and the dark class. */
beforeAll(() => {
  app = createApp({ render: () => COMPONENTS.map(([component, props]) => h(component, props)) })
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

/** A colour value as PrimeVue writes it: hex, `rgba()`, or a colour mixed with `transparent`. */
function parse(value: string, scheme: Scheme): Rgba {
  const reference = /^var\((--p-[\w-]+)\)$/.exec(value)
  if (reference?.[1]) return parse(resolve(reference[1], scheme), scheme)
  const hex = /^#([\da-f]{6})$/i.exec(value)?.[1]
  if (hex) {
    const [r = 0, g = 0, b = 0] = [0, 2, 4].map((i) => Number.parseInt(hex.slice(i, i + 2), 16))
    return { r, g, b, a: 1 }
  }
  const rgba = /^rgba?\(([^)]+)\)$/.exec(value)?.[1]
  if (rgba) {
    const [r = 0, g = 0, b = 0, a = 1] = rgba.split(/[\s,/]+/).map(Number)
    return { r, g, b, a }
  }
  const mix = /^color-mix\(in srgb,\s*(.+?),\s*transparent (\d+)%\)$/.exec(value)
  if (mix?.[1] && mix[2]) {
    const color = parse(mix[1].trim(), scheme)
    return { ...color, a: color.a * (1 - Number(mix[2]) / 100) }
  }
  if (value === 'transparent') return { r: 0, g: 0, b: 0, a: 0 }
  throw new Error(`not a colour: ${value}`)
}

function over(top: Rgba, bottom: Rgba): Rgba {
  const mixed = (x: number, y: number) => x * top.a + y * (1 - top.a)
  return { r: mixed(top.r, bottom.r), g: mixed(top.g, bottom.g), b: mixed(top.b, bottom.b), a: 1 }
}

function luminance({ r, g, b }: Rgba): number {
  const [lr = 0, lg = 0, lb = 0] = [r, g, b].map((channel) => {
    const c = channel / 255
    return c <= 0.040_45 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb
}

/** A see-through `background` (a hover tint) lies on the content background. */
function contrast(foreground: string, background: string, scheme: Scheme): number {
  const page = parse(resolve('--p-content-background', scheme), scheme)
  const back = over(parse(resolve(`--p-${background}`, scheme), scheme), page)
  const front = over(parse(resolve(`--p-${foreground}`, scheme), scheme), back)
  const [a, b] = [luminance(front), luminance(back)]
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

const SURFACES = ['content-background', 'app-background']
const TONES = ['error', 'warn', 'info', 'ok', 'busy', 'off']
/** The tones of an issue: IssueList puts links and outlined fix buttons on their background. */
const ISSUE_TONES = ['error', 'warn', 'info']
const BUTTONS = ['primary', 'secondary', 'info', 'success', 'warn', 'help', 'danger', 'contrast']
const PLAIN_BUTTONS = [...BUTTONS, 'plain']
const TOASTS = ['info', 'success', 'warn', 'error', 'secondary', 'contrast']
const TAGS = ['primary', 'secondary', 'success', 'info', 'warn', 'danger', 'contrast']

type Pair = [foreground: string, background: string]

/** WCAG AA: 4.5:1 for text. */
const TEXT_PAIRS: Pair[] = [
  ...SURFACES.flatMap((bg): Pair[] => [
    ['text-color', bg],
    ['text-muted-color', bg],
    ['primary-color', bg],
    ...TONES.map((tone): Pair => [`status-${tone}-color`, bg]),
  ]),
  ['primary-contrast-color', 'primary-color'],
  ['form-field-color', 'form-field-background'],
  ['form-field-placeholder-color', 'form-field-background'],
  ...TONES.flatMap((tone): Pair[] => [
    [`status-${tone}-color`, `status-${tone}-background`],
    ['text-color', `status-${tone}-background`],
    ['primary-color', `status-${tone}-background`],
  ]),
  // Solid buttons, at rest, under the pointer and pressed.
  ...BUTTONS.flatMap((kind) =>
    ['', 'hover-', 'active-'].map((state): Pair => [
      `button-${kind}-${state}color`,
      `button-${kind}-${state}background`,
    ]),
  ),
  // Outlined and text buttons: on the surfaces, under the pointer and pressed.
  ...['outlined', 'text'].flatMap((style) =>
    PLAIN_BUTTONS.flatMap((kind) =>
      [
        ...SURFACES,
        `button-${style}-${kind}-hover-background`,
        `button-${style}-${kind}-active-background`,
      ].map((bg): Pair => [`button-${style}-${kind}-color`, bg]),
    ),
  ),
  ...[
    'button-link-color',
    'button-outlined-secondary-color',
    'button-text-secondary-color',
  ].flatMap((fg) => ISSUE_TONES.map((tone): Pair => [fg, `status-${tone}-background`])),
  ...TOASTS.flatMap((kind): Pair[] => [
    [`toast-${kind}-color`, `toast-${kind}-background`],
    [`toast-${kind}-detail-color`, `toast-${kind}-background`],
  ]),
  ...TOASTS.flatMap((kind): Pair[] => [
    [`message-${kind}-color`, `message-${kind}-background`],
    ...SURFACES.flatMap((bg): Pair[] => [
      [`message-${kind}-outlined-color`, bg],
      [`message-${kind}-simple-color`, bg],
    ]),
  ]),
  ...TAGS.map((kind): Pair => [`tag-${kind}-color`, `tag-${kind}-background`]),
  // SelectButton: its options are toggle buttons in a group.
  ['togglebutton-color', 'togglebutton-background'],
  ['togglebutton-hover-color', 'togglebutton-hover-background'],
  ['togglebutton-checked-color', 'togglebutton-content-checked-background'],
  ['togglebutton-icon-color', 'togglebutton-background'],
  ['togglebutton-icon-checked-color', 'togglebutton-content-checked-background'],
  // The options of Select and Listbox.
  ['list-option-color', 'overlay-select-background'],
  ['list-option-focus-color', 'list-option-focus-background'],
  ['list-option-selected-color', 'list-option-selected-background'],
  ['list-option-selected-focus-color', 'list-option-selected-focus-background'],
]

/** WCAG AA: 3:1 for the parts of a control and for graphics (1.4.11). */
const GRAPHIC_PAIRS: Pair[] = [
  ['form-field-border-color', 'form-field-background'],
  ['form-field-invalid-border-color', 'form-field-background'],
  // A focused field's ring lies on the field and on the surface around it.
  ['form-field-focus-ring-color', 'form-field-background'],
  ...SURFACES.map((bg): Pair => ['form-field-focus-ring-color', bg]),
  ...SURFACES.flatMap((bg) => TONES.map((tone): Pair => [`status-${tone}-border-color`, bg])),
  // An outlined button's border is its only edge; a button's focus ring lies on the surface.
  ...SURFACES.flatMap((bg) =>
    PLAIN_BUTTONS.map((kind): Pair => [`button-outlined-${kind}-border-color`, bg]),
  ),
  ...SURFACES.flatMap((bg) => BUTTONS.map((kind): Pair => [`button-${kind}-focus-ring-color`, bg])),
  ...ISSUE_TONES.map((tone): Pair => [
    'button-outlined-secondary-border-color',
    `status-${tone}-background`,
  ]),
  // A switch: the track, off and on, against the surface; the handle against its track.
  ...SURFACES.flatMap((bg): Pair[] => [
    ['toggleswitch-background', bg],
    ['toggleswitch-hover-background', bg],
    ['toggleswitch-checked-background', bg],
  ]),
  ['toggleswitch-handle-background', 'toggleswitch-background'],
  ['toggleswitch-handle-hover-background', 'toggleswitch-hover-background'],
  ['toggleswitch-handle-checked-background', 'toggleswitch-checked-background'],
  // A slider: its track and the ring of its handle against the surface.
  ...SURFACES.flatMap((bg): Pair[] => [
    ['slider-track-background', bg],
    ['slider-handle-background', bg],
    ['slider-range-background', bg],
  ]),
  // SelectButton: the checked option against its group is what shows the choice.
  ['togglebutton-content-checked-background', 'togglebutton-checked-background'],
]

/** Each pair below the ratio, with its ratio, or with the reason it cannot be measured. */
function below(pairs: Pair[], ratio: number, scheme: Scheme): string[] {
  return pairs.flatMap(([fg, bg]) => {
    try {
      const value = contrast(fg, bg, scheme)
      return value < ratio ? [`${fg} on ${bg}: ${value.toFixed(2)}`] : []
    } catch (error) {
      return [`${fg} on ${bg}: ${(error as Error).message}`]
    }
  })
}

describe.each(['light', 'dark'] as const)('the %s colours', (scheme) => {
  it('give text at least 4.5:1', () => {
    expect(below(TEXT_PAIRS, 4.5, scheme)).toEqual([])
  })

  it('give borders and marks at least 3:1', () => {
    expect(below(GRAPHIC_PAIRS, 3, scheme)).toEqual([])
  })

  // WCAG asks nothing of a disabled control; 3:1 keeps its label readable. main.css paints a
  // disabled coloured button in these greys.
  it('show a disabled button in a readable grey unlike any enabled fill', () => {
    const pairs: Pair[] = [
      ['form-field-disabled-color', 'form-field-disabled-background'],
      ...['primary', 'info', 'success', 'warn', 'help', 'danger'].map((kind): Pair => [
        'form-field-disabled-background',
        `button-${kind}-background`,
      ]),
    ]
    expect(below(pairs, 3, scheme)).toEqual([])
  })

  it('draw a ring round a focused form field, not only a border colour', () => {
    expect(resolve('--p-form-field-focus-ring-style', scheme)).toBe('solid')
    expect(Number.parseFloat(resolve('--p-form-field-focus-ring-width', scheme))).toBeGreaterThanOrEqual(2)
  })

  it('give toasts a background the page does not show through', () => {
    const seeThrough = TOASTS.map((kind) => `toast-${kind}-background`).filter(
      (bg) => parse(resolve(`--p-${bg}`, scheme), scheme).a < 1,
    )
    expect(seeThrough).toEqual([])
  })
})
