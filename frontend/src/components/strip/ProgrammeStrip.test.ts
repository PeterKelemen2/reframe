import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import type { MediaSource } from '@/api/types'
import { languages } from '@/components/language/testing'
import { previewServer } from '@/components/preview/testing'
import { chaptersSource } from '@/components/range/testing'
import { mountShell } from '@/components/shell/testing'
import { sampleDefinitions } from '@/components/summary/testing'
import { useEditorStore } from '@/stores/editor'
import { usePreviewStore } from '@/stores/preview'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'

import ProgrammeStrip from './ProgrammeStrip.vue'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function strip(source: MediaSource = chaptersSource(), props: Record<string, unknown> = {}) {
  previewServer()
  const { wrapper } = await mountShell(ProgrammeStrip, {
    props,
    setup() {
      useSystemStore().definitions = sampleDefinitions()
      useSystemStore().languages = languages()
      useSourcesStore().entries = [{ id: 'movie', path: '/media/chapters.mkv', source }]
    },
  })
  mounted.push(wrapper)
  const editor = useEditorStore()
  await editor.open('movie')
  await flushPromises()
  return { wrapper, editor, preview: usePreviewStore(), ui: useUiStore() }
}

/** The text a lane's `aria-describedby` points to. */
function description(element: Element): string {
  const id = element.getAttribute('aria-describedby') ?? ''
  return document.getElementById(id)?.textContent?.trim() ?? ''
}

function press(target: Element, key: string): void {
  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
}

describe('the programme strip', () => {
  it('shows the programme, its chapters and one lane per output track', async () => {
    const { wrapper } = await strip()
    expect(wrapper.get('h3').text()).toBe('Programme')
    expect(wrapper.get('[data-field="programme-facts"]').text()).toBe(
      '0:00.0–0:05.0 · 4 chapters · 4 lanes',
    )
    expect(wrapper.findAll('[data-field="chapter"]').map((chapter) => chapter.text())).toEqual([
      '1',
      '2',
      '3',
      '4',
    ])
    expect(wrapper.findAll('[data-field="lane"]').map((lane) => lane.text())).toEqual([
      'A1 ja',
      'A2 en',
      'A3 en',
      'S1 en',
    ])
    const bars = wrapper.findAll('[data-field="bar"]')
    expect(bars.map((bar) => bar.classes('is-pale'))).toEqual([false, false, true, false])
    expect(bars[0]!.attributes('style')).toContain('--lane-color: var(--rf-lang-')
    expect(wrapper.findAll('[data-field="tick"]').length).toBeGreaterThan(1)
  })

  it('tells a screen reader every lane in words', async () => {
    const { wrapper } = await strip()
    const text = wrapper.get('[data-field="programme-text"]').text()
    expect(text).toContain('Programme 0:00.0 to 0:05.0, range Whole source.')
    expect(text).toContain('4 chapters')
    expect(text).toContain('Audio 2, English, AAC Stereo, whole programme')
    expect(text).toContain('Audio 3, English, AAC Stereo, commentary, whole programme')
    const lane = wrapper.get('[data-path="subtitles[0]"]')
    expect(lane.text()).toBe('S1 en')
    expect(description(lane.element)).toBe('Subtitles 1, English, SRT, whole programme')
  })

  it('shades the range and dims the chapters outside it', async () => {
    const { wrapper, editor } = await strip()
    editor.setRange({ kind: 'chapters', start: 2, end: 3 })
    await flushPromises()
    const range = wrapper.get('[data-layer="range"]').attributes('style')
    expect(range).toMatch(/left: 19\.9\d*%/)
    expect(wrapper.findAll('[data-field="chapter"]').map((c) => c.classes('is-outside'))).toEqual([
      true,
      false,
      false,
      true,
    ])
    expect(wrapper.get('[data-field="bar"]').attributes('style')).toMatch(/left: 19\.9\d*%/)
    expect(description(wrapper.get('[data-path="audio[0]"]').element)).toContain('0:01.0 to 0:04.0')
  })

  it('focuses the track of a lane', async () => {
    const { wrapper, ui } = await strip()
    await wrapper.get('[data-path="audio[1]"]').trigger('click')
    expect(ui.activeTab).toBe('audio')
    expect(ui.revealed?.path).toBe('audio[1]')
    await wrapper.get('[data-path="subtitles[0]"]').trigger('click')
    expect(ui.activeTab).toBe('subtitles')
    expect(ui.revealed?.path).toBe('subtitles[0]')
  })

  it('is one Tab stop for the lanes, which the arrow keys move through', async () => {
    const { wrapper } = await strip()
    const lanes = () =>
      wrapper.findAll<HTMLButtonElement>('[data-field="lane"]').map((lane) => lane.element)
    expect(lanes().map((lane) => lane.tabIndex)).toEqual([0, -1, -1, -1])
    press(lanes()[0]!, 'ArrowDown')
    await flushPromises()
    expect(document.activeElement).toBe(lanes()[1])
    expect(lanes().map((lane) => lane.tabIndex)).toEqual([-1, 0, -1, -1])
    press(lanes()[1]!, 'End')
    await flushPromises()
    expect(document.activeElement).toBe(lanes()[3])
    press(lanes()[3]!, 'ArrowUp')
    await flushPromises()
    expect(document.activeElement).toBe(lanes()[2])
  })

  it('moves the preview to a sampled frame, by click and by the arrow keys', async () => {
    const { wrapper, preview } = await strip()
    const dots = () => wrapper.findAll<HTMLButtonElement>('[data-field="frame-dot"]')
    expect(dots()).toHaveLength(10)
    expect(dots()[0]!.attributes('aria-current')).toBe('true')
    await dots()[3]!.trigger('click')
    expect(preview.index).toBe(3)
    expect(dots()[3]!.classes('is-current')).toBe(true)
    expect(
      dots()
        .map((dot) => dot.element.tabIndex)
        .indexOf(0),
    ).toBe(3)
    expect(wrapper.get('[data-field="playhead"]').text()).toBe('0:01.4')

    press(dots()[3]!.element, 'ArrowRight')
    await flushPromises()
    expect(preview.index).toBe(4)
    expect(document.activeElement).toBe(dots()[4]!.element)
    press(dots()[4]!.element, 'Home')
    await flushPromises()
    expect(preview.index).toBe(0)
  })

  it('makes the lanes thinner and lets them scroll when there are many', async () => {
    const { wrapper, editor } = await strip()
    const track = editor.job!.audio![0]!
    editor.set(
      '/audio',
      Array.from({ length: 9 }, () => structuredClone(track)),
    )
    await flushPromises()
    expect(wrapper.findAll('[data-field="lane"]')).toHaveLength(10)
    expect(wrapper.classes()).toContain('programme-strip--compact')
  })

  it('says when the source gives no length, and still lists the lanes', async () => {
    const source = chaptersSource()
    source.container = { ...source.container, duration: null }
    source.video = [{ ...source.video![0]!, duration: null }]
    const { wrapper } = await strip(source)
    expect(wrapper.find('[data-state="unknown"]').exists()).toBe(true)
    expect(wrapper.find('[data-row="ruler"]').exists()).toBe(false)
    expect(wrapper.find('[data-row="chapters"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-field="lane"]')).toHaveLength(4)
    expect(wrapper.get('[data-field="bar"]').attributes('style')).toContain('width: 100%')
  })

  it('is a second-level heading when docked in the editor column', async () => {
    const { wrapper } = await strip(chaptersSource(), { docked: true })
    expect(wrapper.get('h2').text()).toBe('Programme')
    expect(wrapper.attributes('data-docked')).toBe('true')
  })
})
