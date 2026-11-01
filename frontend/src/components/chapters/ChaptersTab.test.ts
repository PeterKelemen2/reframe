import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { FakeServer, problem } from '@/api/testing/fakes'
import type { ChapterImport, JobSettings, MediaSource, OutputChapters } from '@/api/types'
import { mountBase } from '@/components/base/testing'
import ChaptersTab from '@/components/editor/tabs/ChaptersTab.vue'
import { download } from '@/components/presets/format'
import { issue, sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { platform } from '@/platform'
import { useEditorStore } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'
import { useValidationStore } from '@/stores/validation'

import { chapter, chaptersOf } from './testing'

vi.mock(import('@/components/presets/format'), async (original) => ({
  ...(await original()),
  download: vi.fn<(blob: Blob, name: string) => void>(),
}))

const CHAPTERS = 'POST /api/jobs/chapters'
const IMPORT = 'POST /api/chapters/import'
const EXPORT = 'POST /api/jobs/chapters/export'

let server: FakeServer
const mounted: VueWrapper[] = []

function jobOf(body: unknown): JobSettings {
  return (body as { job: JobSettings }).job
}

beforeEach(() => {
  server = new FakeServer()
    .on('POST /api/jobs/draft', () => sampleDraft(sampleJob()))
    .on('POST /api/presets/diff', [])
    .on('GET /api/presets/h265-mkv-1080p', samplePreset())
    .on(CHAPTERS, (request) => chaptersOf(jobOf(request.body)))
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  vi.restoreAllMocks()
})

async function mountTab(options: { source?: Partial<MediaSource> } = {}) {
  const wrapper = mountBase(ChaptersTab)
  mounted.push(wrapper)
  if (options.source !== undefined) {
    useSourcesStore().entries = [
      { id: 'src', path: '/media/x.mkv', source: options.source as MediaSource },
    ]
  }
  const editor = useEditorStore()
  await editor.open('src')
  await vi.waitFor(() => expect(wrapper.find('[data-state="asking"]').exists()).toBe(false))
  return { wrapper, editor }
}

const names = (editor: ReturnType<typeof useEditorStore>) => editor.job?.chapters?.names ?? null
const shown = (wrapper: VueWrapper) =>
  wrapper.findAll<HTMLInputElement>('[data-field="name"]').map((input) => input.element.value)

/** Opens the menu of `action`, chooses `label`; the number of items the menu had. */
async function chooseMenuItem(wrapper: VueWrapper, action: string, label: string): Promise<number> {
  await wrapper.find(`[data-action="${action}"]`).trigger('click')
  const items = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')]
  const item = items.find((element) => element.textContent?.trim() === label)
  expect(item).toBeDefined()
  item?.querySelector<HTMLElement>('a, .p-menu-item-link, .p-menu-item-content')?.click()
  await flushPromises()
  return items.length
}

describe('the chapter table', () => {
  it("shows the output's chapters: number, start, duration, name", async () => {
    const { wrapper } = await mountTab()
    const rows = wrapper.findAll('tbody tr')
    expect(
      rows.map((row) =>
        row
          .findAll('td')
          .map((cell) => cell.text())
          .slice(0, 3),
      ),
    ).toEqual([
      ['1', '0:00:00.000', '0:00:01.000'],
      ['2', '0:00:01.000', '0:00:01.500'],
      ['3', '0:00:02.500', '0:00:01.500'],
    ])
    expect(shown(wrapper)).toEqual(['Opening', 'Part One', 'Part Two'])
  })

  it('renames a chapter as one undo step, keeping the other names', async () => {
    const { wrapper, editor } = await mountTab()
    const input = wrapper.findAll('[data-field="name"]')[1]!
    await input.setValue('Mid')
    await input.setValue('Middle')
    await input.trigger('blur')
    expect(names(editor)).toEqual(['Opening', 'Middle', 'Part Two'])
    editor.undo()
    expect(names(editor)).toBeNull()
  })

  it('keeps an emptied name in the field while it is typed in', async () => {
    const { wrapper, editor } = await mountTab()
    const input = wrapper.findAll<HTMLInputElement>('[data-field="name"]')[0]!
    await input.setValue('')
    expect(input.element.value).toBe('')
    expect(names(editor)).toEqual(['', 'Part One', 'Part Two'])
    await input.trigger('blur')
    expect(input.element.value).toBe('Opening')
  })

  it('writes the name of the source chapter a range starts at', async () => {
    server.on(CHAPTERS, {
      origin: 'source',
      reason: '',
      chapters: [chapter(1, 0, 1.5, 'Part One', 1), chapter(2, 1.5, 3, 'Part Two', 2)],
    } satisfies OutputChapters)
    const { wrapper, editor } = await mountTab()
    await wrapper.findAll('[data-field="name"]')[0]!.setValue('Start')
    expect(names(editor)).toEqual(['', 'Start', 'Part Two'])
  })

  it('shows an empty state with the reason when the output gets no chapters', async () => {
    const { wrapper, editor } = await mountTab()
    await wrapper.find('[data-field="enabled"] input').setValue(false)
    expect(editor.job?.chapters?.enabled).toBe(false)
    await vi.waitFor(() => expect(wrapper.find('[data-state="none"]').exists()).toBe(true), {
      timeout: 2000,
    })
    expect(wrapper.find('[data-field="reason"]').text()).toBe('Create chapter markers is off.')
    expect(wrapper.find('tbody').exists()).toBe(false)
  })

  it('shows the issues of the names', async () => {
    const { wrapper } = await mountTab()
    useValidationStore().issues = [issue('chapters.bad', 'chapters.names[1]')]
    await flushPromises()
    expect(wrapper.text()).toContain('chapters.bad at chapters.names[1]')
  })
})

describe('Reset names', () => {
  it('goes back to the source names', async () => {
    const { wrapper, editor } = await mountTab()
    editor.set('/chapters/names', ['A', 'B', 'C'])
    await chooseMenuItem(wrapper, 'reset', 'To the source names')
    expect(names(editor)).toBeNull()
  })

  it('numbers the chapters', async () => {
    const { wrapper, editor } = await mountTab()
    await chooseMenuItem(wrapper, 'reset', 'To Chapter 1, Chapter 2, …')
    expect(names(editor)).toEqual(['Chapter 1', 'Chapter 2', 'Chapter 3'])
  })

  it('has one choice for generated chapters, back to the default names', async () => {
    server.on(CHAPTERS, {
      origin: 'generated',
      reason: '',
      chapters: [chapter(1, 0, 300, 'Intro', null), chapter(2, 300, 600, 'Chapter 2', null)],
    } satisfies OutputChapters)
    const { wrapper, editor } = await mountTab()
    editor.set('/chapters/names', ['Intro'])
    expect(await chooseMenuItem(wrapper, 'reset', 'To Chapter 1, Chapter 2, …')).toBe(1)
    expect(names(editor)).toBeNull()
  })
})

function answer(chapters: ChapterImport['chapters'], issues: ChapterImport['issues'] = []) {
  server.on(IMPORT, { format: 'xml', chapters, issues } satisfies ChapterImport)
}

describe('Import', () => {
  it('applies the names by position as one undo step', async () => {
    const pick = vi.spyOn(platform, 'pickFiles').mockResolvedValue(['/media/chapters.xml'])
    answer([
      { start: 0, name: 'Eins' },
      { start: 1, name: 'Zwei' },
      { start: 2.5, name: 'Drei' },
    ])
    const { wrapper, editor } = await mountTab()
    await wrapper.find('[data-action="import"]').trigger('click')
    await flushPromises()
    expect(pick).toHaveBeenCalledWith({ multiple: false, filters: ['.csv', '.txt', '.xml'] })
    expect(server.requests.find((r) => `${r.method} ${r.path}` === IMPORT)?.body).toEqual({
      path: '/media/chapters.xml',
      format: null,
    })
    expect(names(editor)).toEqual(['Eins', 'Zwei', 'Drei'])
    expect(wrapper.find('[data-state="notice"]').attributes('data-severity')).toBe('success')
    editor.undo()
    expect(names(editor)).toBeNull()
  })

  it('warns when the count or a start differs from the output', async () => {
    vi.spyOn(platform, 'pickFiles').mockResolvedValue(['/media/chapters.txt'])
    answer([
      { start: 0, name: 'Eins' },
      { start: 1.4, name: 'Zwei' },
    ])
    const { wrapper, editor } = await mountTab()
    await wrapper.find('[data-action="import"]').trigger('click')
    await flushPromises()
    expect(names(editor)).toEqual(['Eins', 'Zwei', 'Part Two'])
    const notice = wrapper.find('[data-state="notice"]')
    expect(notice.attributes('data-severity')).toBe('warn')
    expect(notice.text()).toContain('The file has 2 chapters and the output has 3')
    expect(notice.text()).toContain(
      'Chapter 2 starts at 0:00:01.400 in the file and at 0:00:01.000',
    )
  })

  it("shows the server's reason when the file cannot be read, and changes nothing", async () => {
    vi.spyOn(platform, 'pickFiles').mockResolvedValue(['/media/bad.csv'])
    server.on(IMPORT, () => problem(422, 'chapters.invalid', 'Invalid', 'Line 3: no name'))
    const { wrapper, editor } = await mountTab()
    await wrapper.find('[data-action="import"]').trigger('click')
    await flushPromises()
    expect(names(editor)).toBeNull()
    expect(editor.canUndo).toBe(false)
    const notice = wrapper.find('[data-state="notice"]')
    expect(notice.attributes('data-severity')).toBe('error')
    expect(notice.text()).toContain('Line 3: no name')
  })

  it('does nothing when no file is chosen', async () => {
    vi.spyOn(platform, 'pickFiles').mockResolvedValue([])
    const { wrapper } = await mountTab()
    await wrapper.find('[data-action="import"]').trigger('click')
    await flushPromises()
    expect(server.count(IMPORT)).toBe(0)
  })

  it('drops the answer when another job opened meanwhile', async () => {
    vi.spyOn(platform, 'pickFiles').mockResolvedValue(['/media/chapters.xml'])
    answer([{ start: null, name: 'Late' }])
    const { wrapper, editor } = await mountTab()
    await wrapper.find('[data-action="import"]').trigger('click')
    await editor.open('other')
    await flushPromises()
    expect(names(editor)).toBeNull()
  })
})

describe('Export', () => {
  it.each([
    ['CSV', 'csv'],
    ['OGM text', 'ogm'],
    ['Matroska XML', 'xml'],
  ])('downloads the output’s chapters as %s', async (label, format) => {
    server.on(EXPORT, (request) => ({
      format: (request.body as { format: string }).format,
      file_name: `multitrack.${format}`,
      content: `chapters as ${format}`,
    }))
    const { wrapper, editor } = await mountTab()
    editor.set('/chapters/names', ['A', 'B', 'C'])
    await chooseMenuItem(wrapper, 'export', label)
    const body = server.requests.find((r) => `${r.method} ${r.path}` === EXPORT)?.body
    expect(body).toMatchObject({ format, job: { chapters: { names: ['A', 'B', 'C'] } } })
    const call = vi.mocked(download).mock.lastCall
    expect(call?.[1]).toBe(`multitrack.${format}`)
    expect(await call?.[0].text()).toBe(`chapters as ${format}`)
  })

  it('says why an export failed', async () => {
    server.on(EXPORT, () => problem(422, 'chapters.none', 'No chapters', 'The output has none'))
    const { wrapper } = await mountTab()
    await chooseMenuItem(wrapper, 'export', 'CSV')
    expect(wrapper.find('[data-state="notice"]').text()).toContain('The output has none')
  })
})

describe('Generate chapters', () => {
  it('is offered only for a source without chapters', async () => {
    const withChapters = await mountTab({ source: { chapters: [{ index: 0, start: 0, end: 1 }] } })
    expect(withChapters.wrapper.find('[data-field="generate"]').exists()).toBe(false)
    withChapters.wrapper.unmount()
    const without = await mountTab({ source: { chapters: [] } })
    expect(without.wrapper.find('[data-field="generate"]').exists()).toBe(true)
  })

  it('turns on with 5 minutes, keeps a changed value, and turns off', async () => {
    const { wrapper, editor } = await mountTab({ source: { chapters: [] } })
    await wrapper.find('[data-field="generate"] input').setValue(true)
    expect(editor.job?.chapters?.generate_every).toBe(5)
    editor.set('/chapters/generate_every', 10)
    await flushPromises()
    await wrapper.find('[data-field="generate"] input').setValue(false)
    expect(editor.job?.chapters?.generate_every).toBeNull()
    await wrapper.find('[data-field="generate"] input').setValue(true)
    expect(editor.job?.chapters?.generate_every).toBe(10)
  })

  it('forgets the remembered interval when another job opens', async () => {
    const { wrapper, editor } = await mountTab({ source: { chapters: [] } })
    const sources = useSourcesStore()
    sources.entries = [
      ...sources.entries,
      { id: 'other', path: '/media/y.mkv', source: { chapters: [] } as unknown as MediaSource },
    ]
    const toggle = () => wrapper.find('[data-field="generate"] input')
    await toggle().setValue(true)
    editor.set('/chapters/generate_every', 10)
    await flushPromises()
    await toggle().setValue(false)
    await editor.open('other')
    await flushPromises()
    await toggle().setValue(true)
    expect(editor.job?.chapters?.generate_every).toBe(5)
  })
})
