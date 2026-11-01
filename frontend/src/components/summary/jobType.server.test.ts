import { createPinia, setActivePinia } from 'pinia'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope } from 'vue'

import { boot, shutdown } from '@/api/boot'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { http } from '@/api/testing/serverHelpers'
import type { JobSettings, MediaSource, QueueJob, SourceEntry, ValidationIssue } from '@/api/types'
import { pinnedTools } from '@/editor/testing/tools.mjs'
import { useEditorStore } from '@/stores/editor'
import { useQueueStore } from '@/stores/queue'
import { useSourcesStore } from '@/stores/sources'

import { useInPlaceReload } from './useInPlaceReload'
import { useJobType } from './useJobType'

const PORT = 8774
const TOKEN = 'job-type-d-test-token'
const SOON = { timeout: 30_000, interval: 50 }

let server: DevServer
let scope: EffectScope

beforeAll(async () => {
  const tools = pinnedTools()
  // The server may write only the output root's copy; the media root is read-only for it.
  server = await startServer({
    port: PORT,
    args: [
      '--token',
      TOKEN,
      '--fixtures',
      'multitrack',
      '--output-fixtures',
      'multitrack',
      ...(tools === null ? [] : ['--tools-dir', tools]),
    ],
  })
}, 120_000)

afterAll(async () => {
  await server.stop()
})

beforeEach(async () => {
  setActivePinia(createPinia())
  await boot({ backend: async () => ({ baseUrl: server.url }), token: TOKEN })
  scope = effectScope()
})

afterEach(() => {
  scope.stop()
  shutdown()
})

async function opened(path: string): Promise<SourceEntry> {
  const [entry] = await useSourcesStore().open([path])
  if (entry?.source === null || entry === undefined) throw new Error(`${path} did not open`)
  await useEditorStore().open(entry.id)
  return entry
}

function sourceOf(id: string): MediaSource {
  const source = useSourcesStore().entries.find((entry) => entry.id === id)?.source
  if (source === null || source === undefined) throw new Error(`no source ${id}`)
  return source
}

describe('the job type and in-place edits against a real server', () => {
  it('names encode, remux and metadata edit with their reasons, and why an edit cannot be in place', async () => {
    await opened(`${server.output}/multitrack.mkv`)
    const editor = useEditorStore()
    const jobType = scope.run(() => useJobType())!
    const settled = async () =>
      vi.waitFor(() => {
        expect(jobType.pending.value).toBe(false)
        expect(jobType.answer.value).not.toBeNull()
      }, SOON)

    await settled()
    expect(jobType.answer.value).toEqual({
      job_type: 'encode',
      reason: 'Encode: the video is encoded with x265.',
      in_place_blockers: ['the video is encoded', 'audio track 1 (AC-3) is encoded'],
    })

    await editor.applyRemuxDraft({ editInPlace: true })
    expect(editor.get('/output/path')).toBe(`${server.output}/multitrack.mkv`)
    await settled()
    expect(jobType.answer.value?.job_type).toBe('metadata_edit')

    editor.set('/audio/0/metadata/default', false)
    editor.set('/audio/1/metadata/default', true)
    await settled()
    expect(jobType.answer.value).toEqual({
      job_type: 'metadata_edit',
      reason:
        'Metadata edit: only the track metadata changes, so mkvpropedit edits multitrack.mkv in place, in seconds.',
      in_place_blockers: [],
    })

    editor.patch([{ op: 'remove', path: '/audio/2' }])
    await settled()
    expect(jobType.answer.value).toEqual({
      job_type: 'remux',
      reason:
        'Remux: the video and every audio and subtitle track are copied without re-encoding. ' +
        "It cannot be edited in place: the audio tracks are not the source's audio tracks in source order.",
      in_place_blockers: ["the audio tracks are not the source's audio tracks in source order"],
    })
    const issues = await http<ValidationIssue[]>(server, 'POST', '/api/jobs/validate', {
      job: editor.job,
    })
    expect(issues.find((issue) => issue.code === 'inplace.not_possible')?.fixes?.[0]?.label).toBe(
      'Write a new file (multitrack (1).mkv)',
    )
  })

  it('says that a source in a folder the server may only read cannot be edited in place', async () => {
    await opened(`${server.media}/multitrack.mkv`)
    const editor = useEditorStore()
    const jobType = scope.run(() => useJobType())!
    await editor.applyRemuxDraft({ editInPlace: true })
    await vi.waitFor(() => expect(jobType.answer.value?.job_type).toBe('remux'), SOON)
    expect(jobType.answer.value?.in_place_blockers).toEqual([
      'multitrack.mkv is in a folder that this server may only read',
    ])
    const issues = await http<ValidationIssue[]>(server, 'POST', '/api/jobs/validate', {
      job: editor.job,
    })
    expect(issues.map((issue) => [issue.code, issue.fixes?.map((fix) => fix.label)])).toEqual([
      ['inplace.not_allowed', [`Write a new file in ${server.output}`]],
    ])
  })

  it('edits the flags in place in under a second, and the open source is read again', async () => {
    const path = `${server.output}/multitrack.mkv`
    // Only the server's own temporary copy is ever edited.
    expect(path.startsWith(`${server.home}/`)).toBe(true)
    const { id } = await opened(path)
    scope.run(() => useInPlaceReload())
    const editor = useEditorStore()
    const queue = useQueueStore()
    await vi.waitFor(() => expect(queue.loaded).toBe(true), SOON)
    const before = sourceOf(id)
    expect(before.audio?.map((track) => track.disposition?.default ?? false)).toEqual([
      true,
      false,
      false,
    ])
    expect(before.subtitles?.map((track) => track.disposition?.forced ?? false)).toEqual([
      false,
      false,
      true,
    ])

    await editor.applyRemuxDraft({ editInPlace: true })
    editor.set('/audio/0/metadata/default', false)
    editor.set('/audio/1/metadata/default', true)
    editor.set('/subtitles/1/metadata/forced', true)
    expect(editor.get('/output/path')).toBe(path)
    const [added] = await queue.add([editor.job as JobSettings])
    await queue.start()
    await vi.waitFor(() => expect(queue.byId(added!.id)?.state).toBe('done'), SOON)

    await vi.waitFor(() => {
      const after = sourceOf(id)
      expect(after.audio?.map((track) => track.disposition?.default ?? false)).toEqual([
        false,
        true,
        false,
      ])
      expect(after.subtitles?.map((track) => track.disposition?.forced ?? false)).toEqual([
        false,
        true,
        true,
      ])
    }, SOON)
    const { jobs } = await http<{ jobs: QueueJob[] }>(server, 'GET', '/api/queue')
    const done = jobs.find((job) => job.id === added!.id)!
    expect(done.plan?.job_type).toBe('metadata_edit')
    expect(done.output_path).toBe(path)
    const seconds = (Date.parse(done.finished_at!) - Date.parse(done.started_at!)) / 1000
    expect(seconds).toBeLessThan(1)
  })
})
