// Test data of the video components: the real server's definitions and encoder statuses for a
// few encoders (the AMD desktop with hardware tests on: NVENC and QSV unavailable, AMF and VAAPI
// available), and an editor opened on the sample job (libx265, RF 22, slow, main10, 10-bit).
import { createPinia, setActivePinia } from 'pinia'

import { configureClient } from '@/api/client'
import { FakeServer, settle } from '@/api/testing/fakes'
import type { CapabilitySnapshot, Definitions, EncoderStatus, JobSettings } from '@/api/types'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'

import type { VideoEncoderDef } from '../encoders'
import capabilities from './capabilities.json'
import definitions from './definitions.json'

// jsdom has none; PrimeVue's Select listens to the orientation with one.
globalThis.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  }) as MediaQueryList

export function encoderDefs(): Record<string, VideoEncoderDef> {
  return structuredClone(definitions.video_encoders) as unknown as Record<string, VideoEncoderDef>
}

export function snapshot(changes: Partial<CapabilitySnapshot> = {}): CapabilitySnapshot {
  return { ...(structuredClone(capabilities) as unknown as CapabilitySnapshot), ...changes }
}

export function withStatus(
  base: CapabilitySnapshot,
  id: string,
  status: Partial<EncoderStatus>,
): CapabilitySnapshot {
  const encoders = { ...base.encoders }
  encoders[id] = { ...(encoders[id] as EncoderStatus), ...status }
  return { ...base, encoders }
}

export function videoOf(job: JobSettings) {
  return job.video as NonNullable<JobSettings['video']>
}

/**
 * A fresh Pinia with the system store filled and a fake server for the editor's requests.
 * `job` is what `jobs/draft` answers.
 */
export function setUpVideo(options: { job?: JobSettings; caps?: CapabilitySnapshot } = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const job = options.job ?? sampleJob()
  const server = new FakeServer()
    .on('POST /api/jobs/draft', () => sampleDraft(structuredClone(job)))
    .on('POST /api/presets/diff', [])
    .on(`GET /api/presets/${job.preset_id}`, { ...samplePreset(), id: job.preset_id })
    .on('POST /api/jobs/validate', { issues: [] })
    .on('POST /api/jobs/geometry', { source: null, geometry: null })
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  const system = useSystemStore()
  system.definitions = { video_encoders: encoderDefs() } as Definitions
  system.capabilities = options.caps ?? snapshot()
  return { pinia, server, system, editor: useEditorStore() }
}

/** Opens the editor on the fake server's draft and lets its requests settle. */
export async function openJob(): Promise<void> {
  await useEditorStore().open('source-1')
  await settle()
}
