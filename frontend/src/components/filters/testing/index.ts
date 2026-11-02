// Test data of the filter components: the real server's filter definitions, and the filters of
// the pinned FFmpeg build as encoder detection reports them with the hardware tests off
// (libplacebo untested).
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { configureClient } from '@/api/client'
import { FakeServer } from '@/api/testing/fakes'
import type {
  CapabilitySnapshot,
  Definitions,
  FilterSettings,
  JobSettings,
  MediaSource,
} from '@/api/types'
import { snapshot } from '@/components/video/testing'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'

import definitions from './definitions.json'

export const BUILD_FILTERS = [
  'bwdif',
  'cas',
  'deblock',
  'decimate',
  'fieldmatch',
  'hqdn3d',
  'hue',
  'idet',
  'libplacebo',
  'nlmeans',
  'tonemap',
  'unsharp',
  'yadif',
  'zscale',
]

export function filterDefinitions(): Definitions {
  return structuredClone(definitions) as unknown as Definitions
}

export function filterCaps(changes: Partial<CapabilitySnapshot> = {}): CapabilitySnapshot {
  return snapshot({
    filters: BUILD_FILTERS,
    filter_failures: {},
    untested_filters: ['libplacebo'],
    ...changes,
  })
}

/**
 * A fresh Pinia, the system store filled, a fake server for the editor's requests, and the
 * editor opened on the sample job with `filters`; `source` is the shown file's probe.
 */
export async function openFilters(
  options: {
    filters?: FilterSettings
    source?: MediaSource
    caps?: CapabilitySnapshot
    passthrough?: boolean
  } = {},
) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const job: JobSettings = sampleJob()
  job.filters = options.filters ?? {}
  if (options.passthrough) job.video = { ...job.video!, passthrough: true }
  const server = new FakeServer()
    .on('POST /api/jobs/draft', () => sampleDraft(structuredClone(job)))
    .on('POST /api/presets/diff', [])
    .on(`GET /api/presets/${job.preset_id}`, { ...samplePreset(), id: job.preset_id })
    .on('POST /api/jobs/geometry', { source: null, geometry: null })
    .on('POST /api/jobs/dry-run', [])
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  const system = useSystemStore()
  system.definitions = filterDefinitions()
  system.capabilities = options.caps ?? filterCaps()
  if (options.source) {
    useSourcesStore().entries = [
      { id: 'source-1', path: options.source.ref.path, source: options.source },
    ]
  }
  const editor = useEditorStore()
  await editor.open('source-1')
  await flushPromises()
  return { pinia, server, system, editor }
}
