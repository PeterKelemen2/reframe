import { createPinia, setActivePinia } from 'pinia'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { apiQuiet, configureClient, unwrap } from '@/api/client'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { endedTask, http } from '@/api/testing/serverHelpers'
import type { CapabilitySnapshot, Definitions, JobSettings, Schemas } from '@/api/types'
import { switchEncoderOps, type VideoEncoderDef } from '@/components/video/encoders'
import { pinnedTools } from '@/editor/testing/tools.mjs'
import { useEditorStore } from '@/stores/editor'

const PORT = 8728

let server: DevServer
let sourceId: string
let encoders: Record<string, VideoEncoderDef>
let caps: CapabilitySnapshot

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: ['--fixtures', 'hdr10', ...(tools === null ? [] : ['--tools-dir', tools])],
  })
  const loaded = await http<{ definitions: Definitions }>(server, 'GET', '/api/definitions')
  encoders = loaded.definitions.video_encoders as Record<string, VideoEncoderDef>
  caps = await http<CapabilitySnapshot>(server, 'GET', '/api/system/encoders')
  const probe = await http<{ task_id: string }>(server, 'POST', '/api/sources', {
    paths: [`${server.media}/hdr10.mkv`],
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
})

/** What the button does: the server's patch for the open job, applied as one edit. */
async function copyHdr(): Promise<string[]> {
  const editor = useEditorStore()
  const body = { job: editor.job as JobSettings }
  const ops = unwrap(await apiQuiet.POST('/api/jobs/hdr-metadata', { body }))
  editor.patch(ops)
  return ops.map((op) => op.path)
}

describe('Copy HDR metadata against the real server', () => {
  it('fills x265’s master-display and max-cll on hdr10, one undo step, into the command', async () => {
    const editor = useEditorStore()
    await editor.open(sourceId, 'h265-mkv-1080p')
    const steps = editor.canUndo
    await copyHdr()
    expect(editor.job?.video?.advanced).toEqual({
      'master-display': 'G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)',
      'max-cll': '1000,400',
    })
    const plan = await http<Schemas['EncodePlan']>(server, 'POST', '/api/jobs/plan', {
      job: editor.job,
    })
    expect(plan.display).toMatch(
      /-x265-params\S* '\S*master-display=G\(13250,34500\)B\(7500,3000\)R\(34000,16000\)WP\(15635,16450\)L\(10000000,1\):max-cll=1000,400/,
    )
    editor.undo()
    expect(editor.job?.video?.advanced).toEqual({})
    expect(editor.canUndo).toBe(steps)
  })

  it('fills SVT-AV1’s mastering-display and content-light, and nothing for NVENC', async () => {
    const editor = useEditorStore()
    await editor.open(sourceId, 'h265-mkv-1080p')
    editor.patch(switchEncoderOps(editor.job!.video!, 'libsvtav1', encoders, caps))
    await copyHdr()
    expect(editor.job?.video?.advanced).toEqual({
      'mastering-display': 'G(0.265,0.69)B(0.15,0.06)R(0.68,0.32)WP(0.3127,0.329)L(1000,0.0001)',
      'content-light': '1000,400',
    })
    editor.patch(switchEncoderOps(editor.job!.video!, 'hevc_nvenc', encoders, caps))
    expect(await copyHdr()).toEqual([])
  })
})
