import { flushPromises, type VueWrapper } from '@vue/test-utils'

import { configureClient } from '@/api/client'
import { FakeServer } from '@/api/testing/fakes'
import type { CapabilitySnapshot, JobSettings, Language } from '@/api/types'
import { languages } from '@/components/language/testing'
import { mountShell } from '@/components/shell/testing'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'

import { forgetInspected } from './external'
import { probedSource, trackDefinitions } from './testing'

/** Set up once per test file: jsdom has no layout and no media queries. */
export function prepareDom(): void {
  Element.prototype.scrollIntoView = () => {}
  window.matchMedia ??= (() => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia
}

const mounted: VueWrapper[] = []

export function unmountAll(): void {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  forgetInspected()
}

export const JAPANESE: Language = {
  tag: 'ja',
  iso639_1: 'ja',
  iso639_2b: 'jpn',
  iso639_2t: 'jpn',
  iso639_3: 'jpn',
  english_name: 'Japanese',
  native_name: '日本語',
  variant: false,
}

/** A component of the tracks tabs, with the editor's job of the `multitrack` source open. */
export async function mountEditor(
  component: object,
  options: {
    job?: (job: JobSettings) => void
    server?: (server: FakeServer) => void
    props?: Record<string, unknown>
  } = {},
) {
  const job = sampleJob()
  options.job?.(job)
  const server = new FakeServer()
    .on('POST /api/jobs/draft', () => sampleDraft(structuredClone(job)))
    .on('POST /api/presets/diff', [])
    .on('GET /api/presets/h265-mkv-1080p', samplePreset())
  options.server?.(server)
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  const { wrapper } = await mountShell(component, {
    props: options.props,
    setup() {
      const system = useSystemStore()
      system.definitions = trackDefinitions()
      system.languages = [...languages(), JAPANESE]
      system.capabilities = {
        encoders: { aac: { id: 'aac', state: 'available', hardware: false } },
      } as unknown as CapabilitySnapshot
      useSourcesStore().entries = [
        { id: 'src', path: '/media/x.mkv', source: probedSource('multitrack') },
      ]
    },
  })
  mounted.push(wrapper)
  const editor = useEditorStore()
  await editor.open('src')
  await flushPromises()
  return { wrapper, editor, server }
}
