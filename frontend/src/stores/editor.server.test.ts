import { createPinia, setActivePinia } from 'pinia'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope } from 'vue'

import { configureClient } from '@/api/client'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { endedTask, http } from '@/api/testing/serverHelpers'
import type {
  CapabilitySnapshot,
  Definitions,
  FieldChange,
  Fix,
  JobSettings,
  Preset,
} from '@/api/types'
import { useValidation } from '@/composables/useValidation'
import { pinnedTools } from '@/editor/testing/tools.mjs'

import { useEditorStore } from './editor'
import { useValidationStore } from './validation'

const PORT = 8750
/** Validation and diffs take milliseconds; this leaves room for a loaded machine. */
const SOON = { timeout: 15_000, interval: 50 }

let server: DevServer
let sourceId: string
/** A video encoder this machine cannot use, and why. */
let unavailable: { id: string; reason: string }
let scope: EffectScope

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: ['--fixtures', 'multitrack', ...(tools === null ? [] : ['--tools-dir', tools])],
  })
  // The dev server turns the hardware test encodes off: on, they find what this machine lacks.
  await http(server, 'PUT', '/api/settings', [
    { op: 'replace', path: '/encoders/hardware_tests', value: true },
  ])
  const rescan = await http<{ task_id: string }>(server, 'POST', '/api/system/encoders/rescan')
  await endedTask(server, rescan.task_id)
  const { encoders } = await http<CapabilitySnapshot>(server, 'GET', '/api/system/encoders')
  const { definitions } = await http<{ definitions: Definitions }>(
    server,
    'GET',
    '/api/definitions',
  )
  const candidates = ['hevc_nvenc', ...Object.keys(definitions.video_encoders ?? {})]
  const id = candidates.find((encoder) => encoders?.[encoder]?.state === 'unavailable')
  if (id === undefined) throw new Error('every video encoder can be used here: nothing to test')
  unavailable = { id, reason: encoders?.[id]?.reason ?? '' }

  const probe = await http<{ task_id: string }>(server, 'POST', '/api/sources', {
    paths: [`${server.media}/multitrack.mkv`],
  })
  const task = await endedTask(server, probe.task_id)
  sourceId = (task.result as { sources: { id: string }[] }).sources[0]?.id ?? ''
}, 120_000)

afterAll(async () => {
  await server.stop()
})

/** Answered `presets/diff` requests: an edit made after one is diffed on its own. */
let diffs: number

async function countingFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const response = await fetch(input, init)
  const url = input instanceof Request ? input.url : String(input)
  if (new URL(url).pathname === '/api/presets/diff') diffs += 1
  return response
}

beforeEach(() => {
  setActivePinia(createPinia())
  diffs = 0
  configureClient({ baseUrl: server.url, token: server.token, fetch: countingFetch })
  scope = effectScope()
  scope.run(() => useValidation())
})

afterEach(() => {
  scope.stop()
  useEditorStore().close()
})

async function inTurn<T>(items: readonly T[], each: (item: T) => Promise<void>): Promise<void> {
  const [first, ...rest] = items
  if (first === undefined) return
  await each(first)
  await inTurn(rest, each)
}

function codes(path: string): string[] {
  return useValidationStore()
    .issuesFor(path)
    .map((issue) => issue.code)
}

describe('the editor against a real server', () => {
  it('shows an unavailable encoder with its fix; the fix, undo and redo move the issue', async () => {
    const editor = useEditorStore()
    const validation = useValidationStore()
    await editor.open(sourceId)
    const drafted = editor.get('/video/encoder')

    editor.set('/video/encoder', unavailable.id)
    await vi.waitFor(() => expect(codes('video.encoder')).toContain('encoder.unavailable'), SOON)
    const issue = validation
      .issuesFor('video.encoder')
      .find((found) => found.code === 'encoder.unavailable')
    expect(issue?.message).toContain(unavailable.reason)
    const fix = issue?.fixes?.find((found) => found.label.includes('closest match')) as Fix
    expect(fix.target).toBe('job')
    await vi.waitFor(
      () =>
        expect(editor.presetChanges).toContainEqual<FieldChange>({
          path: 'video.encoder',
          kind: 'changed',
          preset_value: drafted,
          value: unavailable.id,
        }),
      SOON,
    )

    await editor.applyFix(fix)
    const fixed = editor.get('/video/encoder')
    expect(fixed).not.toBe(unavailable.id)
    await vi.waitFor(() => {
      expect(validation.pending).toBe(false)
      expect(codes('video.encoder')).not.toContain('encoder.unavailable')
    }, SOON)

    editor.undo()
    expect(editor.get('/video/encoder')).toBe(unavailable.id)
    await vi.waitFor(() => expect(codes('video.encoder')).toContain('encoder.unavailable'), SOON)

    editor.redo()
    expect(editor.get('/video/encoder')).toBe(fixed)
    await vi.waitFor(() => {
      expect(validation.pending).toBe(false)
      expect(codes('video.encoder')).not.toContain('encoder.unavailable')
    }, SOON)
  })

  it('follows presets/diff after a change and after applyPreset', async () => {
    const editor = useEditorStore()
    await editor.open(sourceId)
    await vi.waitFor(() => expect(diffs).toBe(1), SOON)
    editor.set('/video/rate_control/value', 30, { coalesce: 'quality' })
    await vi.waitFor(
      () =>
        expect(editor.presetChanges.map((change) => change.path)).toEqual([
          'video.rate_control.value',
        ]),
      SOON,
    )

    await editor.applyPreset('h264-mkv-1080p')
    expect(editor.presetId).toBe('h264-mkv-1080p')
    expect(editor.get('/video/encoder')).toBe('libx264')
    await vi.waitFor(() => expect(diffs).toBe(3), SOON)
    expect(editor.modified).toBe(false)
    editor.set('/output/container', 'mp4')
    await vi.waitFor(
      () => expect(editor.presetChanges.map((change) => change.path)).toEqual(['output.container']),
      SOON,
    )

    editor.undo()
    editor.undo()
    expect(editor.presetId).not.toBe('h264-mkv-1080p')
    await vi.waitFor(
      () =>
        expect(editor.presetChanges.map((change) => change.path)).toEqual([
          'video.rate_control.value',
        ]),
      SOON,
    )
  })

  it('drafts every built-in preset into a job whose template the server finds unmodified', async () => {
    const { presets } = await http<{ presets: Preset[] }>(server, 'GET', '/api/presets')
    const editor = useEditorStore()
    const builtIn = presets.filter((found) => found.built_in)
    expect(builtIn.length).toBeGreaterThan(0)
    // One after the other: the editor holds one job at a time.
    await inTurn(builtIn, async (preset) => {
      await editor.open(sourceId, preset.id)
      await vi.waitFor(() => expect(editor.currentTemplate).not.toBeNull(), SOON)
      const changes = await http<FieldChange[]>(server, 'POST', '/api/presets/diff', {
        template: editor.currentTemplate,
        preset_id: preset.id,
      })
      expect([preset.id, changes]).toEqual([preset.id, []])
    })
  })

  it('shows a value the server cannot read as an error at its field', async () => {
    const editor = useEditorStore()
    await editor.open(sourceId)
    editor.set('/video/rate_control/value', 'fast')
    editor.set('/audio/0/bitrate', 'high')
    await vi.waitFor(() => {
      expect(codes('video.rate_control.value')).toEqual(['request.invalid'])
      expect(codes('audio[0].bitrate')).toEqual(['request.invalid'])
    }, SOON)
    editor.undo()
    editor.undo()
    await vi.waitFor(() => expect(codes('video.rate_control.value')).toEqual([]), SOON)
  })

  it('validates a queued job taken back into the editor', async () => {
    const editor = useEditorStore()
    await editor.open(sourceId)
    const job = JSON.parse(JSON.stringify(editor.job)) as JobSettings
    job.video = { ...job.video!, encoder: unavailable.id }
    // The sources store's `ensure` comes with the sources panel; the probed source stands in.
    const { useSourcesStore } = await import('./sources')
    vi.spyOn(useSourcesStore(), 'ensure').mockResolvedValue({
      id: sourceId,
      path: job.source.path,
      source: null,
    })
    await editor.loadJob(job)
    await vi.waitFor(() => expect(codes('video.encoder')).toContain('encoder.unavailable'), SOON)
  })
})
