import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import type { MediaSource } from '@/api/types'
import { mountShell } from '@/components/shell/testing'
import { issue } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'
import { useUiStore } from '@/stores/ui'
import { useValidationStore } from '@/stores/validation'

import RangeSelector from './RangeSelector.vue'
import { bareSource, chaptersSource, rangeGroup, rangeServer } from './testing'

const mounted: VueWrapper[] = []

beforeEach(() => {
  configureClient({ baseUrl: 'http://server', token: 't', fetch: rangeServer().fetch })
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountSelector(source: MediaSource = chaptersSource()) {
  const { wrapper } = await mountShell(RangeSelector, {
    setup() {
      useSourcesStore().entries = ['src', 'e1', 'e2'].map((id) => ({
        id,
        path: `/media/${id}.mkv`,
        source: structuredClone(source),
      }))
    },
  })
  mounted.push(wrapper)
  const editor = useEditorStore()
  await editor.open('src')
  await flushPromises()
  return { wrapper, editor }
}

async function mountInGroup() {
  const result = await mountSelector()
  useSourcesStore().grouping = { groups: [rangeGroup()], issues: [] }
  await result.editor.editGroup('g1')
  await flushPromises()
  return result
}

function el<T extends HTMLElement = HTMLElement>(selector: string): T {
  const found = document.querySelector<T>(selector)
  if (found === null) throw new Error(`no ${selector}`)
  return found
}

function button(): HTMLButtonElement {
  return el<HTMLButtonElement>('[data-field="range"]')
}

function textOf(selector: string): string {
  return el(selector).textContent?.replace(/\s+/g, ' ').trim() ?? ''
}

async function openPopover(): Promise<void> {
  button().click()
  await flushPromises()
}

async function mode(kind: string): Promise<void> {
  el<HTMLInputElement>(`[data-range-mode="${kind}"]`).click()
  await flushPromises()
}

async function type(path: string, value: string, how: 'change' | 'enter' = 'change') {
  const input = el<HTMLInputElement>(`[data-path="${path}"] input`)
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
  await flushPromises()
  if (how === 'enter') {
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  } else {
    input.dispatchEvent(new Event('change', { bubbles: true }))
  }
  await flushPromises()
}

/** Until the overlays' leave transitions (an animation frame in jsdom) and timers have run. */
async function gone(selector: string): Promise<void> {
  await vi.waitFor(() => expect(document.querySelector(selector)).toBeNull())
}

async function pick(path: string, label: string): Promise<void> {
  await gone('.p-select-option')
  el(`[data-path="${path}"] .p-select`).click()
  await flushPromises()
  const option = [...document.querySelectorAll<HTMLElement>('.p-select-option')].find(
    (found) => found.textContent?.trim() === label,
  )
  if (option === undefined) throw new Error(`no option ${label}`)
  option.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
  await flushPromises()
}

function escape(target: Element | null): void {
  target?.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }),
  )
}

function issuesIn(path: string): string[] {
  return [...document.querySelectorAll(`[data-path="${path}"] .rf-field__issue`)].map(
    (item) => item.textContent?.replace(/\s+/g, ' ').trim() ?? '',
  )
}

describe('the range button', () => {
  it('shows the range and its length, in its accessible name too', async () => {
    const { editor } = await mountSelector()
    expect(textOf('[data-field="range-label"]')).toBe('Whole source')
    expect(textOf('[data-field="range-length"]')).toBe('0:05')
    expect(button().dataset.kind).toBe('full')
    expect(button().getAttribute('aria-label')).toBe('Range: Whole source, 0:05')

    editor.setRange({ kind: 'chapters', start: 2, end: 3 })
    await flushPromises()
    expect(textOf('[data-field="range-label"]')).toBe('Chapters 2–3')
    expect(textOf('[data-field="range-length"]')).toBe('0:03')
    expect(button().dataset.kind).toBe('chapters')
    expect(button().getAttribute('aria-label')).toBe('Range: Chapters 2–3, 0:03')
  })

  it('opens a labelled dialog with the focus on the current mode', async () => {
    await mountSelector()
    expect(button().getAttribute('aria-expanded')).toBe('false')
    expect(document.querySelector('.range-popover')).toBeNull()
    await openPopover()
    const dialog = el('.range-popover')
    expect(button().getAttribute('aria-expanded')).toBe('true')
    expect(dialog.getAttribute('role')).toBe('dialog')
    const title = document.getElementById(dialog.getAttribute('aria-labelledby') ?? '')
    expect(title?.textContent).toBe('Range')
    expect(document.activeElement).toBe(el('[data-range-mode="full"]'))
    expect(
      [...dialog.querySelectorAll('[data-range-mode]')].map((input) => [
        input.getAttribute('data-range-mode'),
        document.querySelector(`label[for="${input.id}"]`)?.textContent,
      ]),
    ).toEqual([
      ['full', 'Whole source'],
      ['chapters', 'Chapters'],
      ['time', 'Seconds'],
      ['frames', 'Frames'],
    ])
  })
})

describe('the modes', () => {
  it('disables chapters and frames, with the reason, for a source that cannot use them', async () => {
    await mountSelector(bareSource())
    await openPopover()
    for (const kind of ['chapters', 'frames']) {
      const input = el<HTMLInputElement>(`[data-range-mode="${kind}"]`)
      expect(input.disabled).toBe(true)
      expect(input.getAttribute('aria-disabled')).toBe('true')
      const reason = el(`[data-range-reason="${kind}"]`)
      expect(input.getAttribute('aria-describedby')).toBe(reason.id)
    }
    expect(textOf('[data-range-reason="chapters"]')).toBe('The source has no chapters.')
    expect(textOf('[data-range-reason="frames"]')).toBe('The video does not say its frame rate.')
    expect(el<HTMLInputElement>('[data-range-mode="time"]').disabled).toBe(false)
  })

  it('says a source without video cannot take frames', async () => {
    const audio = chaptersSource()
    audio.video = []
    await mountSelector(audio)
    await openPopover()
    expect(el<HTMLInputElement>('[data-range-mode="frames"]').disabled).toBe(true)
    expect(textOf('[data-range-reason="frames"]')).toBe('The source has no video.')
    expect(document.querySelector('[data-range-reason="chapters"]')).toBeNull()
  })

  it('keeps the span from chapters to seconds to frames, one undo step each', async () => {
    const { editor } = await mountSelector()
    await openPopover()
    await mode('chapters')
    expect(editor.job?.range).toEqual({ kind: 'chapters', start: 1, end: 4 })
    await pick('range.start', '2 · Part One · 0:00:01')
    await pick('range.end', '3 · Part Two · 0:00:02.500')
    expect(editor.job?.range).toEqual({ kind: 'chapters', start: 2, end: 3 })
    await mode('time')
    expect(editor.job?.range).toEqual({ kind: 'time', start: 1, end: 4 })
    expect(el<HTMLInputElement>('[data-path="range.start"] input').value).toBe('0:00:01.000')
    expect(el<HTMLInputElement>('[data-path="range.end"] input').value).toBe('0:00:04.000')
    await mode('frames')
    expect(editor.job?.range).toEqual({ kind: 'frames', start: 25, end: 100 })
    await mode('full')
    expect(editor.job?.range).toEqual({ kind: 'full' })

    const back = [
      { kind: 'frames', start: 25, end: 100 },
      { kind: 'time', start: 1, end: 4 },
      { kind: 'chapters', start: 2, end: 3 },
      { kind: 'chapters', start: 2, end: 4 },
      { kind: 'chapters', start: 1, end: 4 },
      { kind: 'full' },
    ]
    for (const range of back) {
      editor.undo()
      expect(editor.job?.range).toEqual(range)
    }
    expect(editor.canUndo).toBe(false)
  })
})

describe('the chapter selects', () => {
  it('list each chapter’s number, name and start', async () => {
    await mountSelector()
    await openPopover()
    await mode('chapters')
    el('[data-path="range.start"] .p-select').click()
    await flushPromises()
    expect(
      [...document.querySelectorAll('.p-select-option')].map((option) => option.textContent),
    ).toEqual([
      '1 · Opening · 0:00:00',
      '2 · Part One · 0:00:01',
      '3 · Part Two · 0:00:02.500',
      '4 · Credits · 0:00:04',
    ])
  })

  it('leave the name out of a chapter without one', async () => {
    const source = chaptersSource()
    source.chapters![1]!.title = null
    await mountSelector(source)
    await openPopover()
    await mode('chapters')
    el('[data-path="range.start"] .p-select').click()
    await flushPromises()
    expect(document.querySelectorAll('.p-select-option')[1]?.textContent).toBe('2 · 0:00:01')
  })

  it('move To with a From after it, and From with a To before it', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'chapters', start: 2, end: 3 })
    await openPopover()
    await pick('range.start', '4 · Credits · 0:00:04')
    expect(editor.job?.range).toEqual({ kind: 'chapters', start: 4, end: 4 })
    await pick('range.end', '1 · Opening · 0:00:00')
    expect(editor.job?.range).toEqual({ kind: 'chapters', start: 1, end: 1 })
    await pick('range.end', '3 · Part Two · 0:00:02.500')
    expect(editor.job?.range).toEqual({ kind: 'chapters', start: 1, end: 3 })
  })
})

describe('the seconds fields', () => {
  it('take the three forms on change or Enter, and show H:MM:SS.mmm after', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'time', start: 0, end: null })
    await openPopover()
    await type('range.start', '1:30')
    expect(editor.job?.range).toEqual({ kind: 'time', start: 90, end: null })
    expect(el<HTMLInputElement>('[data-path="range.start"] input').value).toBe('0:01:30.000')
    await type('range.end', '0:45:00.250', 'enter')
    expect(editor.job?.range).toEqual({ kind: 'time', start: 90, end: 2700.25 })
    await type('range.start', '90.0')
    expect(el<HTMLInputElement>('[data-path="range.start"] input').value).toBe('0:01:30.000')
    await type('range.end', '')
    expect(editor.job?.range).toEqual({ kind: 'time', start: 90, end: null })
    expect(el<HTMLInputElement>('[data-path="range.end"] input').placeholder).toBe('To the end')
    editor.undo()
    await flushPromises()
    expect(editor.job?.range).toEqual({ kind: 'time', start: 90, end: 2700.25 })
    expect(el<HTMLInputElement>('[data-path="range.end"] input').value).toBe('0:45:00.250')
  })

  it('keep text that does not parse, with an error, and change nothing', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'time', start: 1, end: 4 })
    await openPopover()
    await type('range.end', '4 min')
    expect(editor.job?.range).toEqual({ kind: 'time', start: 1, end: 4 })
    expect(el<HTMLInputElement>('[data-path="range.end"] input').value).toBe('4 min')
    expect(issuesIn('range.end')).toEqual([
      'Error: This is not a time: type H:MM:SS.mmm, MM:SS or seconds.',
    ])
    expect(issuesIn('range.start')).toEqual([])
    await type('range.end', '3')
    expect(editor.job?.range).toEqual({ kind: 'time', start: 1, end: 3 })
    expect(issuesIn('range.end')).toEqual([])
  })

  it('keep text that does not parse while the other field changes the range', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'time', start: 1, end: 4 })
    await openPopover()
    await type('range.start', 'abc', 'enter')
    await type('range.end', '3', 'enter')
    expect(editor.job?.range).toEqual({ kind: 'time', start: 1, end: 3 })
    expect(el<HTMLInputElement>('[data-path="range.start"] input').value).toBe('abc')
    expect(issuesIn('range.start')).toEqual([
      'Error: This is not a time: type H:MM:SS.mmm, MM:SS or seconds.',
    ])
  })

  it('start at 0 with an empty Start', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'time', start: 2, end: 4 })
    await openPopover()
    await type('range.start', '')
    expect(editor.job?.range).toEqual({ kind: 'time', start: 0, end: 4 })
    expect(el<HTMLInputElement>('[data-path="range.start"] input').value).toBe('0:00:00.000')
  })

  it('keep a converted time that the field shows rounded when it is committed unchanged', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'time', start: 1.0004, end: 4 })
    await openPopover()
    await type('range.start', '0:00:01.000', 'enter')
    expect(editor.job?.range).toEqual({ kind: 'time', start: 1.0004, end: 4 })
    expect(editor.canUndo).toBe(true)
    editor.undo()
    expect(editor.canUndo).toBe(false)
  })
})

describe('the frame fields', () => {
  it('map onto the model one to one, with the help line, an open end and whole numbers only', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'frames', start: 0, end: null })
    await openPopover()
    expect(textOf('[data-path="range.end"] label')).toBe('To frame (not included)')
    expect(textOf('[data-path="range.start"] label')).toBe('From frame')
    const help = el('[data-path="range.start"] input').getAttribute('aria-describedby') ?? ''
    expect(document.getElementById(help.split(' ')[0] ?? '')?.textContent).toContain(
      'The To frame is not encoded',
    )
    await type('range.start', '24')
    await type('range.end', '1440')
    expect(editor.job?.range).toEqual({ kind: 'frames', start: 24, end: 1440 })
    expect(textOf('[data-field="range-label"]')).toBe('Frames 24 – 1440')
    await type('range.end', '12.5')
    expect(editor.job?.range).toEqual({ kind: 'frames', start: 24, end: 1440 })
    expect(issuesIn('range.end')).toEqual([
      'Error: This is not a frame number: type a whole number from 0.',
    ])
  })
})

describe('the range issues', () => {
  it('show on their fields and on the button', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'chapters', start: 2, end: 9 })
    useValidationStore().issues = [
      issue('range.end_beyond', 'range.end', 'warning'),
      issue('range.outside', 'range'),
      issue('video.encoder', 'video.encoder'),
    ]
    await flushPromises()
    expect(button().classList).toContain('range-selector__trigger--error')
    const described = document.getElementById(button().getAttribute('aria-describedby') ?? '')
    expect(described?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      'Error: range.outside at range Warning: range.end_beyond at range.end',
    )
    await openPopover()
    expect(issuesIn('range')).toEqual(['Error: range.outside at range'])
    expect(issuesIn('range.end')).toEqual(['Warning: range.end_beyond at range.end'])
    expect(issuesIn('range.start')).toEqual([])
    const group = el('[role="radiogroup"]')
    const issueList = el('[data-path="range"] .rf-field__issues')
    expect(group.getAttribute('aria-describedby')?.split(' ')).toContain(issueList.id)
  })

  it('show on the chapter From', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'chapters', start: 5, end: 5 })
    useValidationStore().issues = [issue('range.outside', 'range.start')]
    await openPopover()
    expect(issuesIn('range.start')).toEqual(['Error: range.outside at range.start'])
  })
})

describe('the length', () => {
  it('shows in the popover, and says when it is not known', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'chapters', start: 2, end: 3 })
    await openPopover()
    expect(textOf('.range-popover__length')).toBe('Length: 0:03')
    editor.setRange({ kind: 'frames', start: 0, end: null })
    await flushPromises()
    expect(textOf('.range-popover__length')).toBe('Length: 0:05')
  })

  it('is left out of the button and said to be unknown without a duration', async () => {
    const source = chaptersSource()
    source.container = { ...source.container, duration: null }
    await mountSelector(source)
    expect(button().getAttribute('aria-label')).toBe('Range: Whole source')
    expect(document.querySelector('[data-field="range-length"]')).toBeNull()
    await openPopover()
    expect(textOf('.range-popover__length')).toBe('The length is not known.')
  })
})

describe('the range in a group', () => {
  it('is the shown file’s override: the dot, Reset to group, no Apply to whole group', async () => {
    const { editor } = await mountInGroup()
    expect(button().dataset.state).toBeUndefined()
    await openPopover()
    expect(textOf('.range-popover__note')).toBe(
      'A group has no range: this range is for the shown file only.',
    )
    expect(document.querySelector('[data-action="range-reset"]')).toBeNull()
    await mode('chapters')
    expect(editor.range).toEqual({ kind: 'chapters', start: 1, end: 4 })
    expect(button().dataset.state).toBe('overridden')
    expect(document.querySelector('.range-selector__override')).not.toBeNull()
    expect(document.querySelector('[data-action="override-menu"]')).toBeNull()
    expect(textOf('.range-popover')).not.toContain('Apply to whole group')

    const reset = el('[data-action="range-reset"]')
    reset.focus()
    reset.click()
    await flushPromises()
    expect(editor.range).toEqual({ kind: 'full' })
    expect(button().dataset.state).toBeUndefined()
    expect(document.querySelector('[data-action="range-reset"]')).toBeNull()
    // The button went away with the focus on it: the focus stays in the popover.
    expect(document.activeElement).toBe(el('[data-range-mode="full"]'))
  })

  it('shows the file’s issues from its matrix row in scope group', async () => {
    const { editor } = await mountInGroup()
    editor.setRange({ kind: 'chapters', start: 2, end: 9 })
    // The matrix the change asked for comes first; the fake server gives rows without issues.
    await vi.waitFor(() => expect(editor.resolving).toBe(false))
    const shown = editor.resolution?.rows?.find((found) => found.path === '/media/e1.mkv')
    expect(shown).toBeDefined()
    editor.resolution = {
      ...editor.resolution!,
      rows: [{ ...shown!, issues: [issue('range.end_beyond', 'range.end', 'warning')] }],
    }
    await flushPromises()
    expect(button().classList).toContain('range-selector__trigger--warning')
    await openPopover()
    expect(issuesIn('range.end')).toEqual(['Warning: range.end_beyond at range.end'])
  })
})

describe('the keyboard', () => {
  it('a “show me” of a range field opens the popover on that field', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'time', start: 1, end: 60 })
    await flushPromises()
    Element.prototype.scrollIntoView = () => {}
    useUiStore().reveal('range.end')
    await vi.waitFor(() => expect(document.activeElement).toBe(el('[data-path="range.end"] input')))
    expect(button().getAttribute('aria-expanded')).toBe('true')

    // Open already, in another field.
    el<HTMLInputElement>('[data-path="range.end"] input').blur()
    useUiStore().reveal('range.start')
    await vi.waitFor(() =>
      expect(document.activeElement).toBe(el('[data-path="range.start"] input')),
    )
  })

  it('a “show me” of a chapter field focuses its select', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'chapters', start: 5, end: 5 })
    await flushPromises()
    Element.prototype.scrollIntoView = () => {}
    useUiStore().reveal('range.start')
    await vi.waitFor(() =>
      expect(document.activeElement).toBe(el('[data-path="range.start"] [role="combobox"]')),
    )
  })

  it('a “show me” of the whole range lands on the button while the popover is closed', async () => {
    await mountSelector()
    Element.prototype.scrollIntoView = () => {}
    useUiStore().reveal('range')
    await flushPromises()
    expect(document.activeElement).toBe(button())
    expect(button().getAttribute('aria-expanded')).toBe('false')
  })

  it('keeps the focus in the popover when an undo takes its field away', async () => {
    const { editor } = await mountSelector()
    await openPopover()
    await mode('chapters')
    const select = el('[data-path="range.start"] [role="combobox"]')
    select.focus()
    editor.undo()
    await flushPromises()
    expect(editor.job?.range).toEqual({ kind: 'full' })
    expect(document.activeElement).toBe(el('[data-range-mode="full"]'))
  })

  it('Escape closes the popover and gives the focus back to the button', async () => {
    await mountSelector()
    button().focus()
    await openPopover()
    escape(document.activeElement)
    await gone('.range-popover')
    expect(button().getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(button())
  })

  it('Escape on a closed chapter select closes the popover too', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'chapters', start: 2, end: 3 })
    await openPopover()
    const select = el('[data-path="range.start"] [role="combobox"]')
    select.focus()
    escape(select)
    await gone('.range-popover')
    expect(document.activeElement).toBe(button())
  })

  it('Escape in an open chapter list closes only the list', async () => {
    const { editor } = await mountSelector()
    editor.setRange({ kind: 'chapters', start: 2, end: 3 })
    await openPopover()
    el('[data-path="range.start"] .p-select').click()
    await flushPromises()
    const select = el('[data-path="range.start"] [role="combobox"]')
    expect(select.getAttribute('aria-expanded')).toBe('true')
    escape(select)
    await gone('.p-select-option')
    expect(document.querySelector('.range-popover')).not.toBeNull()
    expect(button().getAttribute('aria-expanded')).toBe('true')
  })
})
