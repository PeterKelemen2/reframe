import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { deferred, problem } from '@/api/testing/fakes'
import type { JsonPatchOp, MediaSource } from '@/api/types'
import { mountShell } from '@/components/shell/testing'
import { hdr10Source, multitrackSource } from '@/components/summary/testing'
import { sampleJob } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'

import { openJob, setUpVideo } from '../testing'
import CopyHdrMetadata from './CopyHdrMetadata.vue'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

const MASTER_DISPLAY = 'G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)'
const X265_HDR: JsonPatchOp[] = [
  { op: 'add', path: '/video/advanced/master-display', value: MASTER_DISPLAY },
  { op: 'add', path: '/video/advanced/max-cll', value: '1000,400' },
]

const gone = () => problem(404, 'sources.not_found', 'Source not found', 'hdr10.mkv is gone')

async function mountCopy(
  options: { encoder?: string; source?: MediaSource; passthrough?: boolean; answer?: unknown } = {},
) {
  const job = sampleJob()
  job.video = { ...job.video!, encoder: options.encoder ?? 'libx265' }
  if (options.passthrough) job.video.passthrough = true
  const setup = setUpVideo({ job })
  setup.server.on('POST /api/jobs/hdr-metadata', options.answer ?? X265_HDR)
  const source = options.source ?? hdr10Source()
  useSourcesStore().entries = [{ id: 'source-1', path: source.ref.path, source }]
  await openJob()
  const { wrapper } = await mountShell(CopyHdrMetadata, { pinia: setup.pinia })
  mounted.push(wrapper)
  return { ...setup, wrapper }
}

async function copy(wrapper: VueWrapper) {
  await wrapper.find('[data-action="copy-hdr"]').trigger('click')
  await flushPromises()
}

function note(wrapper: VueWrapper): string {
  return wrapper.find('.copy-hdr-metadata__note').text()
}

describe('Copy HDR metadata from source', () => {
  it('puts the source’s HDR10 values into the job as one undo step', async () => {
    const { wrapper, server, editor } = await mountCopy()
    const before = structuredClone(editor.job)
    await copy(wrapper)
    const sent = server.requests.find((request) => request.path === '/api/jobs/hdr-metadata')
    expect(sent?.body).toEqual({ job: before })
    expect(editor.job?.video?.advanced).toEqual({
      'master-display': MASTER_DISPLAY,
      'max-cll': '1000,400',
    })
    expect(note(wrapper)).toBe('Copied master-display, max-cll.')
    editor.undo()
    expect(editor.job?.video?.advanced).toEqual({})
    expect(editor.canUndo).toBe(false)
  })

  it('says the source has no HDR metadata', async () => {
    const { wrapper, editor } = await mountCopy({ source: multitrackSource(), answer: [] })
    await copy(wrapper)
    expect(note(wrapper)).toBe(
      'Nothing to copy: the source has no HDR10 metadata (mastering display or content light level).',
    )
    expect(editor.canUndo).toBe(false)
  })

  it('says a hardware encoder takes the metadata from the frames', async () => {
    const { wrapper } = await mountCopy({ encoder: 'hevc_nvenc', answer: [] })
    await copy(wrapper)
    expect(note(wrapper)).toBe(
      'Nothing to copy: NVIDIA NVENC H.265 takes the HDR metadata from the frames, so it has no options for it.',
    )
  })

  it('says x264 cannot write the metadata', async () => {
    const { wrapper } = await mountCopy({ encoder: 'libx264', answer: [] })
    await copy(wrapper)
    expect(note(wrapper)).toBe('Nothing to copy: x264 cannot write HDR10 metadata.')
  })

  it('shows why the request failed', async () => {
    const { wrapper, editor } = await mountCopy({ answer: gone })
    await copy(wrapper)
    expect(note(wrapper)).toBe('The HDR metadata could not be copied: hdr10.mkv is gone')
    expect(wrapper.find('[data-note="failed"]').exists()).toBe(true)
    expect(editor.job?.video?.advanced).toEqual({})
  })

  it('does not copy into another job opened while it asked', async () => {
    const { wrapper, server, editor } = await mountCopy()
    const answer = deferred<JsonPatchOp[]>()
    server.on('POST /api/jobs/hdr-metadata', () => answer.promise)
    await wrapper.find('[data-action="copy-hdr"]').trigger('click')
    await useEditorStore().open('source-1')
    answer.resolve(X265_HDR)
    await flushPromises()
    expect(editor.job?.video?.advanced).toEqual({})
    expect(note(wrapper)).toBe('')
  })

  it('forgets its note when the encoder changes', async () => {
    const { wrapper, editor } = await mountCopy()
    await copy(wrapper)
    editor.set('/video/encoder', 'libsvtav1')
    await flushPromises()
    expect(note(wrapper)).toBe('')
  })

  it('cannot be used while the video is passed through', async () => {
    const { wrapper } = await mountCopy({ passthrough: true })
    expect(wrapper.find('[data-action="copy-hdr"]').attributes('disabled')).toBeDefined()
  })
})
