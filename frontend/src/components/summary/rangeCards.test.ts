import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { chaptersSource, rangeGroup, rangeServer } from '@/components/range/testing'
import { mountShell } from '@/components/shell/testing'
import { useEditorStore } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'

import EstimateCard from './EstimateCard.vue'
import SourceCard from './SourceCard.vue'
import { sampleDefinitions } from './testing'

const mounted: VueWrapper[] = []

beforeEach(() => {
  configureClient({ baseUrl: 'http://server', token: 't', fetch: rangeServer().fetch })
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

/** The Source and Estimate cards of `src` (chapters.mkv), at 6000 kb/s. */
async function mountCards(media = chaptersSource()) {
  const { wrapper, pinia } = await mountShell(SourceCard, {
    setup() {
      useSystemStore().definitions = sampleDefinitions()
      useSourcesStore().entries = ['src', 'e1', 'e2'].map((id) => ({
        id,
        path: `/media/${id}.mkv`,
        source: structuredClone(media),
      }))
    },
  })
  const { wrapper: estimate } = await mountShell(EstimateCard, { pinia })
  mounted.push(wrapper, estimate)
  const editor = useEditorStore()
  await editor.open('src')
  editor.set('/video/rate_control', {
    mode: 'bitrate',
    kbps: 6000,
    two_pass: false,
    turbo_first_pass: false,
  })
  await flushPromises()
  return { source: wrapper, estimate, editor }
}

function text(wrapper: VueWrapper, selector: string): string {
  return wrapper.find(selector).text().replace(/\s+/g, ' ').trim()
}

describe('the Summary’s range', () => {
  it('shows in the Source and Estimate cards, and the estimate covers only the range', async () => {
    const { source, estimate, editor } = await mountCards()
    expect(text(source, '[data-field="range"]')).toBe('Whole source (0:05)')
    expect(text(estimate, '[data-field="range"]')).toBe('Range: Whole source (0:05)')
    expect(text(estimate, '[data-field="basis"]')).toContain('for 0:05')

    editor.setRange({ kind: 'chapters', start: 2, end: 3 })
    await flushPromises()
    expect(text(source, '[data-field="range"]')).toBe('Chapters 2–3 (0:03)')
    expect(text(estimate, '[data-field="range"]')).toBe('Range: Chapters 2–3 (0:03)')
    expect(text(estimate, '[data-field="basis"]')).toContain('for 0:03')
  })

  it('leaves out a length that the source does not give', async () => {
    const media = chaptersSource()
    media.chapters = []
    const { estimate, editor } = await mountCards(media)
    editor.setRange({ kind: 'chapters', start: 2, end: 3 })
    await flushPromises()
    expect(text(estimate, '[data-field="range"]')).toBe('Range: Chapters 2–3')
  })

  it('stops at the end of the source, as the encode does', async () => {
    const { source, estimate, editor } = await mountCards()
    editor.setRange({ kind: 'time', start: 4, end: 600 })
    await flushPromises()
    expect(text(source, '[data-field="range"]')).toBe('0:00:04 – 0:10:00 (0:01)')
    expect(text(estimate, '[data-field="basis"]')).toContain('for 0:01')
  })

  it('is the shown file’s own in a group, in scope group too', async () => {
    const { source, estimate, editor } = await mountCards()
    useSourcesStore().grouping = { groups: [rangeGroup()], issues: [] }
    await editor.editGroup('g1')
    await flushPromises()
    await editor.patchTemplate([
      {
        op: 'replace',
        path: '/video/rate_control',
        value: { mode: 'bitrate', kbps: 6000, two_pass: false, turbo_first_pass: false },
      },
    ])
    editor.setRange({ kind: 'chapters', start: 2, end: 3 })
    // The shown job comes back from the server with the template's bitrate.
    await vi.waitFor(() => expect(estimate.find('[data-field="basis"]').exists()).toBe(true))
    expect(editor.job?.range).toEqual({ kind: 'chapters', start: 2, end: 3 })
    expect(text(source, '[data-field="range"]')).toBe('Chapters 2–3 (0:03)')
    expect(text(estimate, '[data-field="basis"]')).toContain('for 0:03')
  })
})
