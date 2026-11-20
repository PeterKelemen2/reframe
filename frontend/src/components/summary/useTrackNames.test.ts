import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope } from 'vue'

import { configureClient } from '@/api/client'
import { FakeServer } from '@/api/testing/fakes'
import type { JobSettings } from '@/api/types'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'

import { hasNameTemplate, useTrackNames } from './useTrackNames'

describe('the track names the open job writes', () => {
  let server: FakeServer
  let scope: EffectScope

  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    server = new FakeServer()
      .on('POST /api/jobs/draft', () => sampleDraft(sampleJob()))
      .on('POST /api/presets/diff', [])
      .on('GET /api/presets/h265-mkv-1080p', samplePreset())
      .on('POST /api/jobs/track-names', (request) => {
        const job = (request.body as { job: JobSettings }).job
        return {
          video: null,
          audio: (job.audio ?? []).map((track) =>
            track.metadata?.name?.includes('{')
              ? 'Japanese 5.1 AC-3'
              : (track.metadata?.name ?? null),
          ),
          subtitles: (job.subtitles ?? []).map(() => null),
        }
      })
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
    scope = effectScope()
  })

  afterEach(() => {
    scope.stop()
    vi.useRealTimers()
  })

  const asked = () => server.count('POST /api/jobs/track-names')

  async function opened() {
    const editor = useEditorStore()
    await editor.open('movie')
    const trackNames = scope.run(() => useTrackNames())!
    await vi.advanceTimersByTimeAsync(0)
    return { editor, names: trackNames.names }
  }

  it('asks nothing while no name has a brace', async () => {
    const { names } = await opened()
    expect(asked()).toBe(0)
    expect(names.value).toBeNull()
  })

  it('asks the server once a name is a template, after the edit debounce', async () => {
    const { editor, names } = await opened()
    editor.set('/audio/0/metadata/name', '{lang_name} {channels} {codec}')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(asked()).toBe(1)
    expect(names.value?.audio[0]).toBe('Japanese 5.1 AC-3')
    editor.set('/audio/0/metadata/name', 'Japanese')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(asked()).toBe(1)
    expect(names.value).toBeNull()
  })
})

describe('a name template', () => {
  it('is any name with a brace, of any track', () => {
    const job = sampleJob()
    expect(hasNameTemplate(job)).toBe(false)
    job.subtitles![0]!.metadata!.name = 'Signs }'
    expect(hasNameTemplate(job)).toBe(true)
  })
})
