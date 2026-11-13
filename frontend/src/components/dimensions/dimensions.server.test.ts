import { createPinia, setActivePinia } from 'pinia'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { endedTask, http } from '@/api/testing/serverHelpers'
import type { JsonPatchOp, Schemas } from '@/api/types'
import { formatters } from '@/components/summary/testing'
import { pinnedTools } from '@/editor/testing/tools.mjs'
import { useCropStore } from '@/stores/crop'
import { useEditorStore } from '@/stores/editor'
import { useTasksStore } from '@/stores/tasks'

import { headerOf } from './header'

const PORT = 8722
const SOON = { timeout: 30_000, interval: 50 }
const { t, n } = formatters()

let server: DevServer
let letterbox: string

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: ['--fixtures', 'letterbox', ...(tools === null ? [] : ['--tools-dir', tools])],
  })
  const probe = await http<{ task_id: string }>(server, 'POST', '/api/sources', {
    paths: [`${server.media}/letterbox.mkv`],
  })
  const task = await endedTask(server, probe.task_id)
  letterbox = (task.result as { sources: { id: string }[] }).sources[0]?.id ?? ''
}, 120_000)

afterAll(async () => {
  await server.stop()
})

/** Each `presets/diff` the editor asked, with the server's answer. */
let diffs: { template: unknown; changes: unknown }[] = []

beforeEach(() => {
  setActivePinia(createPinia())
  diffs = []
  configureClient({
    baseUrl: server.url,
    token: server.token,
    fetch: async (input, init) => {
      const request = new Request(input, init)
      const response = await fetch(request.clone())
      if (new URL(request.url).pathname === '/api/presets/diff' && response.ok) {
        const body = (await request.json()) as { template: unknown }
        diffs.push({ template: body.template, changes: await response.clone().json() })
      }
      return response
    },
  })
})

async function opened() {
  const crop = useCropStore()
  const editor = useEditorStore()
  await editor.open(letterbox)
  return { crop, editor }
}

/** `crop=` and `scale=` of the encode step's video filter chain, as `W×H`. */
async function filters(job: unknown): Promise<{ crop: string | null; scale: string | null }> {
  const plan = await http<Schemas['EncodePlan']>(server, 'POST', '/api/jobs/plan', { job })
  const argv = plan.steps.find((step) => step.kind === 'encode')?.argv ?? []
  const chain = argv.filter((arg): arg is string => typeof arg === 'string').join(' ')
  const size = (name: string) => {
    const found = new RegExp(`\\b${name}=(\\d+):(\\d+)`).exec(chain)
    return found ? `${found[1]}×${found[2]}` : null
  }
  return { crop: size('crop'), scale: size('scale') }
}

describe('the Dimensions tab against a real server', () => {
  it('detects letterbox.mkv and crops a job opened in automatic mode without an undo step', async () => {
    const { crop, editor } = await opened()
    const tasks = useTasksStore()
    await vi.waitFor(async () => {
      await tasks.resync()
      expect(crop.detection).not.toBeNull()
    }, SOON)
    expect(crop.detection).toMatchObject({
      auto: { top: 22, bottom: 24, left: 0, right: 0 },
      auto_frames: 5,
      conservative: { top: 0, bottom: 0, left: 0, right: 0 },
    })
    expect(crop.detection?.samples).toHaveLength(10)
    expect(crop.detection?.notes.join(' ')).toContain('The frames disagree')
    expect(editor.get('/dimensions/crop')).toEqual({
      mode: 'auto',
      rect: { top: 22, bottom: 24, left: 0, right: 0 },
    })
    expect(editor.canUndo).toBe(false)
    // The server's answer for the job as it is now, the detected crop in it.
    await vi.waitFor(() => expect(diffs.at(-1)?.template).toEqual(editor.currentTemplate), SOON)
    expect(diffs.at(-1)?.changes).toEqual([])
    expect(editor.modified).toBe(false)
  })

  it.each<[string, JsonPatchOp[]]>([
    ['a manual crop', []],
    ['a rotation', [{ op: 'replace', path: '/dimensions/rotate', value: 90 }]],
    ['a flip', [{ op: 'replace', path: '/dimensions/flip_horizontal', value: true }]],
    [
      'an exact width',
      [{ op: 'replace', path: '/dimensions/size', value: { mode: 'width', width: 200 } }],
    ],
    [
      'a turn with upscaling to an exact height',
      [
        { op: 'replace', path: '/dimensions/size', value: { mode: 'height', height: 400 } },
        { op: 'replace', path: '/dimensions/allow_upscaling', value: true },
        { op: 'replace', path: '/dimensions/rotate', value: 270 },
      ],
    ],
    [
      'a custom pixel aspect',
      [
        { op: 'replace', path: '/dimensions/pixel_aspect', value: 'custom' },
        { op: 'replace', path: '/dimensions/custom_par', value: { num: 4, den: 3 } },
      ],
    ],
  ])('gives the header the crop and the scale of the command for %s', async (_name, ops) => {
    const { crop, editor } = await opened()
    await vi.waitFor(() => expect(crop.grid).not.toBeNull(), SOON)
    // Off the grid on purpose: the client snaps as the server does, so the server keeps it.
    crop.setRect({ top: 23, bottom: 25, left: 7, right: 0 })
    if (ops.length > 0) editor.patch(ops)
    await vi.waitFor(() => {
      expect(crop.geometryPending).toBe(false)
      expect(crop.geometry?.geometry?.crop).toEqual(editor.get('/dimensions/crop/rect'))
    }, SOON)
    const header = headerOf(crop.geometry!, t, n)
    const command = await filters(editor.job)
    expect(command.crop).toBe('314×134')
    expect(header).toContain(`Crop ${command.crop} →`)
    expect(header).toContain(`Output ${command.scale} ·`)
  })
})
