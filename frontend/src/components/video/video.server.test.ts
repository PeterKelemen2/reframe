import { createPinia, setActivePinia } from 'pinia'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope, ref } from 'vue'

import { configureClient } from '@/api/client'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { endedTask, http } from '@/api/testing/serverHelpers'
import type {
  CapabilitySnapshot,
  Definitions,
  JobSettings,
  Schemas,
  ValidationIssue,
} from '@/api/types'
import { pinnedTools } from '@/editor/testing/tools.mjs'
import { useEditorStore } from '@/stores/editor'

import { tokenize } from './commandLine'
import { switchEncoderOps, type VideoEncoderDef } from './encoders'
import { useCommandPlan } from './useCommandPlan'
import { useOutputLines } from './useOutputLines'

const PORT = 8701
const SOON = { timeout: 15_000, interval: 50 }

let server: DevServer
let sourceId: string
let encoders: Record<string, VideoEncoderDef>
let caps: CapabilitySnapshot
let scope: EffectScope

async function draft(preset?: string): Promise<JobSettings> {
  const body =
    preset === undefined ? { source_id: sourceId } : { source_id: sourceId, preset_id: preset }
  return (await http<{ job: JobSettings }>(server, 'POST', '/api/jobs/draft', body)).job
}

async function issues(job: JobSettings): Promise<ValidationIssue[]> {
  return http<ValidationIssue[]>(server, 'POST', '/api/jobs/validate', { job })
}

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: ['--fixtures', 'multitrack', ...(tools === null ? [] : ['--tools-dir', tools])],
  })
  // The dev server turns hardware test encodes off; on, NVENC is unavailable on this machine.
  await http(server, 'PUT', '/api/settings', [
    { op: 'replace', path: '/encoders/hardware_tests', value: true },
  ])
  const rescan = await http<{ task_id: string }>(server, 'POST', '/api/system/encoders/rescan')
  await endedTask(server, rescan.task_id)
  caps = await http<CapabilitySnapshot>(server, 'GET', '/api/system/encoders')
  const loaded = await http<{ definitions: Definitions }>(server, 'GET', '/api/definitions')
  encoders = loaded.definitions.video_encoders as Record<string, VideoEncoderDef>
  const probe = await http<{ task_id: string }>(server, 'POST', '/api/sources', {
    paths: [`${server.media}/multitrack.mkv`],
  })
  const task = await endedTask(server, probe.task_id)
  sourceId = (task.result as { sources: { id: string }[] }).sources[0]?.id ?? ''
}, 120_000)

afterAll(async () => {
  await server.stop()
})

beforeEach(() => {
  setActivePinia(createPinia())
  configureClient({ baseUrl: server.url, token: server.token, fetch })
  scope?.stop()
  scope = effectScope()
})

describe('against the real server', () => {
  it("switches an encoder as the server's closest-match fix does", async (context) => {
    const id = ['hevc_nvenc', ...Object.keys(encoders)].find(
      (encoder) => caps.encoders?.[encoder]?.state === 'unavailable',
    )
    if (id === undefined) context.skip('every video encoder can be used here')
    const x265 = await draft()
    const jobs: JobSettings[] = [{ ...x265, video: { ...x265.video!, encoder: id as string } }]
    // The preset of 03's example: its advanced option goes through the switch too.
    if (id === 'hevc_nvenc') jobs.push(await draft('h265-nvenc-1080p'))
    const found = await Promise.all(jobs.map(issues))
    for (const [index, job] of jobs.entries()) {
      const fix = found[index]?.find((issue) => issue.code === 'encoder.unavailable')?.fixes?.[0]
      expect(fix?.label).toMatch(/closest match/)
      const target = (fix!.patch[0] as { value: string }).value
      const ours = switchEncoderOps(job.video!, target, encoders, caps).filter(
        // The picker also clears the custom parameters; the fix leaves them to their own issue.
        (op) => op.path !== '/video/custom_params',
      )
      expect(ours).toEqual(fix?.patch)
    }
  })

  it('tokenizes the real command without losing a character', async () => {
    const job = await draft()
    const plan = await http<Schemas['EncodePlan']>(server, 'POST', '/api/jobs/plan', { job })
    const tokens = tokenize(plan.display)
    expect(tokens.map((token) => token.text).join('')).toBe(plan.display)
    const kinds = new Set(tokens.map((token) => token.kind))
    expect([...kinds].toSorted()).toEqual([
      'filter',
      'operator',
      'option',
      'path',
      'program',
      'space',
      'value',
    ])
    expect(tokens.find((token) => token.kind === 'path')?.text).toBe(
      `${server.media}/multitrack.mkv`,
    )
  })

  it('reads the line of a header edit: the step, its file, tracks, fields and values', async () => {
    const { job } = await http<{ job: JobSettings }>(server, 'POST', '/api/jobs/draft-remux', {
      source_id: sourceId,
      edit_in_place: false,
    })
    job.audio![1]!.metadata!.language = 'pt-BR'
    const plan = await http<Schemas['EncodePlan']>(server, 'POST', '/api/jobs/plan', { job })
    const tokens = tokenize(plan.display)
    expect(tokens.map((token) => token.text).join('')).toBe(plan.display)
    const words = tokens.filter((token) => token.kind !== 'space')
    const start = words.findIndex((token) => token.text === 'header_edit')
    expect(words.slice(start, start + 9)).toEqual([
      { text: 'header_edit', kind: 'step' },
      { text: plan.output_tmp, kind: 'path' },
      { text: 'audio', kind: 'track' },
      { text: '2:', kind: 'track' },
      { text: 'language=', kind: 'option' },
      { text: 'por', kind: 'value' },
      { text: 'language_ietf=', kind: 'option' },
      { text: 'pt-BR', kind: 'value' },
      { text: '&&', kind: 'operator' },
    ])
  })

  it('shows the command of a job, and the errors of a job without one', async () => {
    const editor = useEditorStore()
    await editor.open(sourceId)
    const { plan, problem } = scope.run(() => useCommandPlan(ref(true)))!
    await vi.waitFor(() => expect(plan.value?.display).toContain('libx265'), SOON)
    editor.set('/video/encoder', 'hevc_nvenc')
    await vi.waitFor(() => expect(problem.value?.kind).toBe('invalid'), SOON)
    expect(plan.value).toBeNull()
    const codes =
      problem.value?.kind === 'invalid' ? problem.value.issues.map((issue) => issue.code) : []
    expect(codes).toContain('encoder.unavailable')
  })

  it("gives the short side of the job's output picture", async () => {
    const editor = useEditorStore()
    await editor.open(sourceId)
    const { lines } = scope.run(() => useOutputLines())!
    // multitrack.mkv is 320×180 and the preset does not upscale.
    await vi.waitFor(() => expect(lines.value).toBe(180), SOON)
  })
})
