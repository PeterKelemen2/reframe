import { flushPromises, type VueWrapper } from '@vue/test-utils'
import InputNumber from 'primevue/inputnumber'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import { deferred, problem } from '@/api/testing/fakes'
import type { ExternalSubtitle, JobSettings, SubtitleFileInfo } from '@/api/types'
import SubtitlesTab from '@/components/editor/tabs/SubtitlesTab.vue'
import { platform } from '@/platform'
import type { useEditorStore } from '@/stores/editor'

import { mountEditor, prepareDom, unmountAll } from './editorTesting'

beforeAll(prepareDom)
afterEach(() => {
  unmountAll()
  vi.restoreAllMocks()
})

const FILES: Record<string, SubtitleFileInfo> = {
  '/media/Film.hu.srt': {
    path: '/media/Film.hu.srt',
    format: 'subrip',
    bitmap: false,
    charset: 'UTF-8',
    events: 120,
    issues: [],
  },
  '/media/Film.cp1250.srt': {
    path: '/media/Film.cp1250.srt',
    format: 'subrip',
    bitmap: false,
    charset: null,
    events: 2,
    issues: [
      {
        severity: 'warning',
        code: 'subtitle.charset_unknown',
        path: 'charset',
        message: 'The character encoding of Film.cp1250.srt was not detected',
        fixes: [],
      },
    ],
  },
  '/media/Film.utf16.srt': {
    path: '/media/Film.utf16.srt',
    format: 'subrip',
    bitmap: false,
    charset: 'UTF-16LE',
    events: 2,
    issues: [
      {
        severity: 'warning',
        code: 'subtitle.utf16',
        path: 'charset',
        message: 'Film.utf16.srt is UTF-16, which FFmpeg reads wrongly',
        fixes: [],
      },
    ],
  },
  '/media/Film.en.sup': {
    path: '/media/Film.en.sup',
    format: 'hdmv_pgs_subtitle',
    bitmap: true,
    charset: null,
    events: 12,
    issues: [],
  },
}

function inspectRoute(server: { on(route: string, handler: unknown): unknown }): void {
  server.on('POST /api/subtitles/inspect', (request: { body: unknown }) => {
    const { path } = request.body as { path: string }
    return FILES[path] ?? problem(422, 'subtitles.unsupported', 'Not a subtitle file')
  })
}

function external(path: string, overrides: Partial<ExternalSubtitle> = {}) {
  return (job: JobSettings) => {
    job.subtitles = [
      {
        action: 'copy',
        convert_to: null,
        forced_only: false,
        source: { path, language: null, name: null, offset_ms: 0, charset: null, ...overrides },
        metadata: {
          default: false,
          forced: false,
          commentary: false,
          hearing_impaired: false,
          visual_impaired: false,
          original: false,
          language: null,
          name: null,
        },
      },
    ]
  }
}

const sources = (editor: ReturnType<typeof useEditorStore>) =>
  editor.job?.subtitles?.map((track) => track.source)

function field(wrapper: VueWrapper, path: string) {
  return wrapper.find(`.rf-field[data-path="${path}"]`)
}

describe('Add external subtitle…', () => {
  it('asks for subtitle files, reads each, and adds them as one undo step', async () => {
    const pick = vi
      .spyOn(platform, 'pickFiles')
      .mockResolvedValue(['/media/Film.hu.srt', '/media/Film.utf16.srt', '/media/notes.txt'])
    const { wrapper, editor, server } = await mountEditor(SubtitlesTab, { server: inspectRoute })
    await wrapper.find('[data-action="add-external"]').trigger('click')
    await flushPromises()
    expect(pick).toHaveBeenCalledWith({
      multiple: true,
      filters: ['.srt', '.ass', '.ssa', '.vtt', '.sup'],
    })
    expect(server.count('POST /api/subtitles/inspect')).toBe(3)
    const added = sources(editor)?.slice(1)
    // The refused file is left out; UTF-8 and UTF-16 name no encoding.
    expect(added).toEqual([
      expect.objectContaining({ path: '/media/Film.hu.srt', language: 'hu', charset: null }),
      expect.objectContaining({ path: '/media/Film.utf16.srt', charset: null }),
    ])
    expect(editor.job?.subtitles?.[1]?.metadata).toMatchObject({ language: 'hu', default: false })
    editor.undo()
    expect(sources(editor)).toEqual([4])
  })

  it('drops the files when another job was opened while they were picked', async () => {
    const picked = deferred<string[]>()
    vi.spyOn(platform, 'pickFiles').mockReturnValue(picked.promise)
    const { wrapper, editor } = await mountEditor(SubtitlesTab, { server: inspectRoute })
    await wrapper.find('[data-action="add-external"]').trigger('click')
    await editor.open('src')
    picked.resolve(['/media/Film.hu.srt'])
    await flushPromises()
    expect(sources(editor)).toEqual([4])
  })
})

describe('the row of an external subtitle file', () => {
  it('shows the file, its format, events and detected encoding', async () => {
    const { wrapper } = await mountEditor(SubtitlesTab, {
      job: external('/media/Film.hu.srt'),
      server: inspectRoute,
    })
    const row = wrapper.find('[data-path="subtitles[0]"]')
    expect(row.find('[data-role="file"]').text()).toBe('Film.hu.srt')
    expect(row.find('[data-role="file-info"]').text()).toBe('SRT · 120 events · UTF-8')
    const charset = field(wrapper, 'subtitles[0].source.charset').findComponent(Select)
    expect(charset.props('modelValue')).toBe('auto')
    expect((charset.props('options') as { label: string }[])[0]?.label).toBe('As detected: UTF-8')
  })

  it('asks for the encoding that was not detected, and takes the one chosen', async () => {
    const { wrapper, editor } = await mountEditor(SubtitlesTab, {
      job: external('/media/Film.cp1250.srt'),
      server: inspectRoute,
    })
    const charsetField = () => field(wrapper, 'subtitles[0].source.charset')
    expect(charsetField().text()).toContain('was not detected')
    charsetField().findComponent(Select).vm.$emit('update:modelValue', 'CP1250')
    await nextTick()
    expect(editor.job?.subtitles?.[0]?.source).toMatchObject({ charset: 'CP1250' })
    expect(charsetField().text()).not.toContain('was not detected')
    charsetField().findComponent(Select).vm.$emit('update:modelValue', 'auto')
    expect(editor.job?.subtitles?.[0]?.source).toMatchObject({ charset: null })
  })

  it('takes a typed encoding as one undo step', async () => {
    const { wrapper, editor } = await mountEditor(SubtitlesTab, {
      job: external('/media/Film.cp1250.srt'),
      server: inspectRoute,
    })
    const select = field(wrapper, 'subtitles[0].source.charset').findComponent(Select)
    select.vm.$emit('update:modelValue', 'ISO')
    select.vm.$emit('update:modelValue', 'ISO-8859-16')
    expect(editor.job?.subtitles?.[0]?.source).toMatchObject({ charset: 'ISO-8859-16' })
    editor.undo()
    expect(editor.job?.subtitles?.[0]?.source).toMatchObject({ charset: null })
  })

  it('shows the UTF-16 warning at the encoding', async () => {
    const { wrapper } = await mountEditor(SubtitlesTab, {
      job: external('/media/Film.utf16.srt'),
      server: inspectRoute,
    })
    expect(field(wrapper, 'subtitles[0].source.charset').text()).toContain(
      'UTF-16, which FFmpeg reads wrongly',
    )
  })

  it('makes a typed time offset (negative too) one undo step', async () => {
    const { wrapper, editor } = await mountEditor(SubtitlesTab, {
      job: external('/media/Film.hu.srt'),
      server: inspectRoute,
    })
    const offset = field(wrapper, 'subtitles[0].source.offset_ms').findComponent(InputNumber)
    offset.vm.$emit('update:modelValue', -5)
    offset.vm.$emit('update:modelValue', -500)
    offset.vm.$emit('blur', new FocusEvent('blur'))
    offset.vm.$emit('update:modelValue', 250)
    expect(editor.job?.subtitles?.[0]?.source).toMatchObject({ offset_ms: 250 })
    editor.undo()
    expect(editor.job?.subtitles?.[0]?.source).toMatchObject({ offset_ms: -500 })
    editor.undo()
    expect(editor.job?.subtitles?.[0]?.source).toMatchObject({ offset_ms: 0 })
  })

  it('counts display sets of a PGS file, has no encoding, and cannot be converted', async () => {
    const { wrapper } = await mountEditor(SubtitlesTab, {
      job: external('/media/Film.en.sup'),
      server: inspectRoute,
    })
    expect(wrapper.find('[data-role="file-info"]').text()).toBe('PGS · 12 display sets')
    expect(field(wrapper, 'subtitles[0].source.charset').exists()).toBe(false)
    expect(wrapper.find('[data-note="bitmap"]').exists()).toBe(true)
    const options = field(wrapper, 'subtitles[0].action').findComponent(SelectButton).props()
      .options as { value: string; disabled: boolean }[]
    expect(options.find((option) => option.value === 'convert')?.disabled).toBe(true)
  })

  it('says so when the file cannot be read', async () => {
    const { wrapper } = await mountEditor(SubtitlesTab, {
      job: external('/media/gone.srt'),
      server: inspectRoute,
    })
    expect(wrapper.find('[data-role="file-info"]').text()).toBe(
      'The file could not be read: its format and encoding are not known.',
    )
  })
})
