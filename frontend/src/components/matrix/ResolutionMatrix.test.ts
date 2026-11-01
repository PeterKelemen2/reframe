import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import type { BatchResolution, Fix, JsonPatchOp, SourceEntry } from '@/api/types'
import { createAppI18n } from '@/i18n'
import type { EditorTarget } from '@/stores/editor'

import ResolutionMatrix from './ResolutionMatrix.vue'
import {
  animeResolution,
  animeSources,
  fixedE11,
  pickedE05,
  pickedOverrides,
  sourceIdOf,
  withRow,
} from './testing'

// Test doubles of the editor and sources stores: the members their contracts give.
const editor = reactive({
  target: null as EditorTarget | null,
  pickTrack: vi.fn<(id: string, kind: string, rule: number, stream: number | null) => void>(),
  resetTrack: vi.fn<(id: string, kind: string, rule: number) => void>(),
  setNameField: vi.fn<(id: string, field: string, value: string | null) => void>(),
  applyRowFix: vi.fn<(id: string, fix: Fix) => Promise<void>>(async () => {}),
})
const sources = reactive({ entries: [] as SourceEntry[] })
vi.mock('@/stores/editor', () => ({ useEditorStore: () => editor }))
vi.mock('@/stores/sources', () => ({ useSourcesStore: () => sources }))

function group(overrides: Record<string, JsonPatchOp[]> = {}): EditorTarget {
  return {
    kind: 'group',
    groupId: 'g',
    sourceId: sourceIdOf(1),
    job: {} as never,
    template: {} as never,
    presetId: null,
    overrides,
    scope: 'group',
  }
}

const mounted: { unmount(): void }[] = []

/** Past the virtual scroller's first layout, which comes after the mount. */
async function settle(): Promise<void> {
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 20))
  await flushPromises()
}

async function mountMatrix(
  resolution: BatchResolution = animeResolution(),
  props: { problemsOnly?: boolean; focus?: string | null } = {},
) {
  const wrapper = mount(ResolutionMatrix, {
    props: { resolution, problemsOnly: false, focus: null, ...props },
    attachTo: document.body,
    global: {
      plugins: [createPinia(), createAppI18n(), [PrimeVue, { theme: 'none' }]],
      // The popover says it is shown from its enter transition.
      stubs: { transition: false },
    },
  })
  mounted.push(wrapper)
  await settle()
  return wrapper
}

/** Each shown row's mark and label: `⚠ E05`. */
function rowLabels(): string[] {
  return [...document.querySelectorAll('[data-row-mark]')].map((el) =>
    [...el.querySelectorAll('span')].map((span) => span.textContent?.trim()).join(' '),
  )
}

/** The text of the cell of `episode` in the column `kind:rule`. */
function cell(episode: number, which: string): HTMLButtonElement {
  const mark = document.querySelector(`[data-row-mark="${sourceIdOf(episode)}"]`)
  const button = mark?.closest('tr')?.querySelector<HTMLButtonElement>(`[data-cell="${which}"]`)
  if (!button) throw new Error(`no cell ${which} of E${episode}`)
  return button
}

/** The element's texts, one space between two elements' texts (the template has none). */
function text(element: Element | null | undefined): string {
  if (!element) return ''
  const parts: string[] = []
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
  while (walker.nextNode()) parts.push(walker.currentNode.textContent?.trim() ?? '')
  return parts.filter(Boolean).join(' ').replaceAll(/\s+/g, ' ')
}

async function open(button: HTMLElement): Promise<HTMLElement> {
  button.click()
  await flushPromises()
  const panel = document.querySelector<HTMLElement>('.matrix-popover')
  if (!panel) throw new Error('no popover')
  return panel
}

// jsdom has no layout: the virtual scroller sees a window this tall, and scrolling does nothing.
let windowHeight = 720
Element.prototype.scrollTo ??= () => {}

beforeEach(() => {
  editor.target = group()
  sources.entries = animeSources()
  windowHeight = 720
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(() => windowHeight)
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(() => 1200)
  vi.spyOn(HTMLElement.prototype, 'offsetParent', 'get').mockImplementation(() => document.body)
  vi.clearAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

describe('the matrix', () => {
  it('shows one row per file and one column per output track plus V and the output name', async () => {
    await mountMatrix()
    expect(rowLabels()).toEqual([
      '✓ E01',
      '✓ E02',
      '✓ E03',
      '✓ E04',
      '⚠ E05',
      '✓ E06',
      '✓ E07',
      '✓ E08',
      '✓ E09',
      '✓ E10',
      '✗ E11',
      '✓ E12',
    ])
    const headers = [...document.querySelectorAll('th')].map((th) => text(th))
    expect(headers).toEqual([
      'File',
      'V',
      'A1 jpn TrueHD→Opus 5.1',
      'A2 eng DTS-HD MA→AAC 2.0',
      'S1 eng Signs & Songs',
      'S2 eng Full',
      'Output name',
    ])
  })

  it("shows E11's cells as 04's matrix, tracks by absolute stream index, with their messages", async () => {
    await mountMatrix()
    expect(text(cell(1, 'audio:1'))).toBe('✓ #2')
    expect(text(cell(5, 'subtitle:0'))).toBe('✓ #4')
    expect(text(cell(11, 'audio:1'))).toBe('✗ none no track matches')
    expect(cell(11, 'audio:1').dataset.status).toBe('missing')
    expect(text(cell(11, 'subtitle:0'))).toBe('≈ #2 matched without title')
    expect(cell(11, 'subtitle:0').getAttribute('aria-label')).toContain('Matched after relaxing')
  })

  it("shows a skipped rule after E11's fix", async () => {
    await mountMatrix(withRow(animeResolution(), fixedE11()))
    expect(text(cell(11, 'audio:1'))).toBe(
      '– none no track matches: skipped (the rule is optional)',
    )
    expect(rowLabels()[10]).toBe('⚠ E11')
  })

  it('shows E05 and E11 alone with problems only', async () => {
    await mountMatrix(animeResolution(), { problemsOnly: true })
    expect(rowLabels()).toEqual(['⚠ E05', '✗ E11'])
  })

  it("sorts by a column's status from its header", async () => {
    await mountMatrix()
    const header = [...document.querySelectorAll('th')].find((th) => text(th).startsWith('S1'))
    header?.click()
    await flushPromises()
    expect(rowLabels()[0]).toBe('✗ E11')
    header?.click()
    await flushPromises()
    expect(rowLabels().at(-1)).toBe('✗ E11')
  })

  it('shows a row without a job (a file that could not be read) with its error', async () => {
    const resolution = animeResolution()
    const row = resolution.rows?.[2]
    if (row === undefined) throw new Error('no row')
    row.job = null
    row.matches = []
    row.status = 'error'
    row.issues = [
      { severity: 'error', code: 'source.probe_failed', path: 'source', message: 'Unreadable' },
    ]
    await mountMatrix(resolution)
    const tr = document.querySelector(`[data-row-mark="${sourceIdOf(3)}"]`)?.closest('tr')
    expect(text(tr)).toBe('✗ E03 Unreadable')
  })
})

describe('the candidate picker', () => {
  it('lists every track of the kind and picks one, or no track, in that file only', async () => {
    await mountMatrix()
    const panel = await open(cell(5, 'audio:1'))
    const options = [...panel.querySelectorAll<HTMLButtonElement>('[data-stream]')]
    expect(options.map((option) => text(option))).toEqual([
      '#1 · jpn · TrueHD 5.1 · Japanese',
      '#2 · eng · DTS-HD MA 5.1 · English Dub taken matches the rule',
      '#3 · eng · AC-3 2.0 · Commentary',
      'No track',
    ])
    expect(panel.querySelector('[data-role="reset"]')).toBeNull()
    options[2]?.click()
    expect(editor.pickTrack).toHaveBeenCalledExactlyOnceWith(sourceIdOf(5), 'audio', 1, 3)

    const again = await open(cell(5, 'audio:1'))
    again.querySelector<HTMLButtonElement>('[data-stream="none"]')?.click()
    expect(editor.pickTrack).toHaveBeenLastCalledWith(sourceIdOf(5), 'audio', 1, null)
    expect(editor.pickTrack).toHaveBeenCalledTimes(2)
  })

  it("marks a picked cell and offers the way back to the group's rule", async () => {
    editor.target = group(pickedOverrides())
    await mountMatrix(withRow(animeResolution(), pickedE05()))
    expect(cell(5, 'audio:1').querySelector('[data-role="picked"]')).not.toBeNull()
    expect(cell(5, 'audio:0').querySelector('[data-role="picked"]')).toBeNull()
    expect(cell(4, 'audio:1').querySelector('[data-role="picked"]')).toBeNull()
    const panel = await open(cell(5, 'audio:1'))
    panel.querySelector<HTMLButtonElement>('[data-role="reset"]')?.click()
    expect(editor.resetTrack).toHaveBeenCalledExactlyOnceWith(sourceIdOf(5), 'audio', 1)
  })

  it('says why a column compiled from the defaults has no picker', async () => {
    const resolution = animeResolution()
    for (const row of resolution.rows ?? []) {
      for (const match of row.matches ?? []) if (match.kind === 'audio') match.defaults = true
    }
    await mountMatrix(resolution)
    const panel = await open(cell(5, 'audio:1'))
    expect(panel.querySelector('[data-role="defaults"]')).not.toBeNull()
    expect(panel.querySelector('[data-stream]')).toBeNull()
  })
})

describe("a row's issues", () => {
  it("applies a fix from the row's issues, the notes folded", async () => {
    await mountMatrix()
    const panel = await open(
      document.querySelector<HTMLElement>(`[data-row-mark="${sourceIdOf(11)}"]`) as HTMLElement,
    )
    expect(
      [...panel.querySelectorAll('.row-issues__issue')].map((issue) =>
        issue.getAttribute('data-code'),
      ),
    ).toEqual(['batch.track_missing', 'batch.near_match', 'batch.track_relaxed'])
    expect(panel.querySelector('details')).not.toBeNull()
    panel.querySelector<HTMLButtonElement>('[data-role="fix"]')?.click()
    await settle()
    const fix = animeResolution().rows?.[10]?.issues?.find((i) => i.code === 'batch.track_missing')
      ?.fixes?.[0]
    expect(editor.applyRowFix).toHaveBeenCalledExactlyOnceWith(sourceIdOf(11), fix)
    // The popover's row changes under it: it closes, and the focus goes back to the row.
    expect(document.querySelector('.matrix-popover')).toBeNull()
    expect(document.activeElement?.getAttribute('data-row-mark')).toBe(sourceIdOf(11))
  })
})

describe('focus across resolutions', () => {
  it('moves the focus into an opened popover, and Escape on the cell closes only it', async () => {
    await mountMatrix()
    const panel = await open(cell(5, 'audio:1'))
    expect(panel.contains(document.activeElement)).toBe(true)
    cell(5, 'audio:1').focus()
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    cell(5, 'audio:1').dispatchEvent(escape)
    await settle()
    expect(escape.defaultPrevented).toBe(true)
    expect(document.querySelector('.matrix-popover')).toBeNull()
  })

  it('shows another cell in the open popover, with the focus in it', async () => {
    await mountMatrix()
    await open(cell(5, 'audio:1'))
    const panel = await open(cell(11, 'subtitle:0'))
    await settle()
    expect(panel.querySelector('.candidate-picker')?.getAttribute('data-column')).toBe(
      'S1 eng Signs & Songs',
    )
    expect(panel.contains(document.activeElement)).toBe(true)
  })

  it('keeps the focus on its cell when a new resolution renders the cells anew', async () => {
    const wrapper = await mountMatrix()
    const before = cell(5, 'audio:1')
    before.focus()
    await wrapper.setProps({ resolution: withRow(animeResolution(), pickedE05()) })
    await settle()
    expect(cell(5, 'audio:1')).not.toBe(before)
    expect(document.activeElement).toBe(cell(5, 'audio:1'))
  })
})

function nameCell(episode: number): HTMLElement {
  const mark = document.querySelector(`[data-row-mark="${sourceIdOf(episode)}"]`)
  const name = mark?.closest('tr')?.querySelector<HTMLElement>('.matrix__name')
  if (!name) throw new Error('no name cell')
  return name
}

describe('the naming column', () => {
  it("shows each file's output name, name source and parsed fields", async () => {
    await mountMatrix()
    expect(text(nameCell(1))).toBe(
      'Anime.Show.S01E01.Pilot.mkv File name {name} Anime.Show {season} 1 {episode} 1 {sub_title} Pilot',
    )
    mounted.splice(0).forEach((wrapper) => wrapper.unmount())
    await mountMatrix(withRow(animeResolution(), pickedE05()))
    expect(text(nameCell(5))).toContain('Anime.Show.S01E05.Echoes Remastered.mkv')
  })

  it('edits a field of one file once; clearing a correction takes the parsed value again', async () => {
    await mountMatrix(withRow(animeResolution(), pickedE05()))
    const panel = await open(
      nameCell(5).querySelector<HTMLElement>('[data-role="edit-name"]') as HTMLElement,
    )
    const episode = panel.querySelector<HTMLInputElement>('[data-field="episode"]')
    if (!episode) throw new Error('no field')
    episode.value = '6'
    episode.dispatchEvent(new Event('input'))
    episode.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    episode.dispatchEvent(new Event('blur'))
    expect(editor.setNameField).toHaveBeenCalledExactlyOnceWith(sourceIdOf(5), 'episode', '6')

    const subTitle = panel.querySelector<HTMLInputElement>('[data-field="sub_title"]')
    if (!subTitle) throw new Error('no field')
    subTitle.value = ''
    subTitle.dispatchEvent(new Event('input'))
    subTitle.dispatchEvent(new Event('blur'))
    expect(editor.setNameField).toHaveBeenLastCalledWith(sourceIdOf(5), 'sub_title', null)

    const name = panel.querySelector<HTMLInputElement>('[data-field="name"]')
    if (!name) throw new Error('no field')
    name.value = ''
    name.dispatchEvent(new Event('input'))
    name.dispatchEvent(new Event('blur'))
    expect(editor.setNameField).toHaveBeenCalledTimes(2)
  })
})

describe('keyboard and size', () => {
  it('renders only the rows near the window', async () => {
    windowHeight = 120
    await mountMatrix()
    expect(rowLabels().length).toBeGreaterThan(0)
    expect(rowLabels().length).toBeLessThan(12)
  })

  it('makes every cell with an action a button', async () => {
    await mountMatrix()
    const tr = document.querySelector(`[data-row-mark="${sourceIdOf(11)}"]`)?.closest('tr')
    const buttons = [...(tr?.querySelectorAll('button') ?? [])]
    // The row's issues, four track cells and the name fields.
    expect(buttons).toHaveLength(6)
    expect(buttons.every((button) => button.tabIndex === 0 && !button.disabled)).toBe(true)
  })

  it('focuses the row asked for', async () => {
    await mountMatrix(animeResolution(), { focus: sourceIdOf(11) })
    await flushPromises()
    expect(document.activeElement?.getAttribute('data-row-mark')).toBe(sourceIdOf(11))
  })
})
