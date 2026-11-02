import { createPinia, setActivePinia } from 'pinia'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope, nextTick } from 'vue'

import { configureClient } from '@/api/client'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { endedTask, http } from '@/api/testing/serverHelpers'
import { pinnedTools } from '@/editor/testing/tools.mjs'
import { useEditorStore } from '@/stores/editor'

import { useParamsCheck } from './useParamsCheck'

const PORT = 8727
const SOON = { timeout: 30_000, interval: 50 }

let server: DevServer
let sourceId: string
let scope: EffectScope

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: ['--fixtures', 'hdr10', ...(tools === null ? [] : ['--tools-dir', tools])],
  })
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
  scope?.stop()
  scope = effectScope()
})

describe('the custom parameters check against the real server', () => {
  it('gives x265’s refusal of an unknown parameter, the file rule, and nothing for psy-rd', async () => {
    const editor = useEditorStore()
    await editor.open(sourceId, 'h265-mkv-1080p')
    expect(editor.job?.video?.encoder).toBe('libx265')
    const check = scope.run(() => useParamsCheck())!
    const issuesOf = async (text: string) => {
      editor.set('/video/custom_params', text)
      await nextTick()
      return vi.waitFor(() => {
        const current = check.value
        if (current?.state !== 'done') throw new Error(`still ${current?.state}`)
        return current.issues.map(({ severity, code, path, message }) => ({
          severity,
          code,
          path,
          message,
        }))
      }, SOON)
    }

    expect(await issuesOf('nosuchparam=1')).toEqual([
      {
        severity: 'error',
        code: 'encoder.custom_param_rejected',
        path: 'video.custom_params',
        message: "FFmpeg refused 'nosuchparam': Unknown option: nosuchparam.",
      },
    ])
    expect(await issuesOf('psy-rd=2.0')).toEqual([])
    expect(await issuesOf('csv=out.csv')).toEqual([
      expect.objectContaining({ code: 'encoder.custom_param_file', path: 'video.custom_params' }),
    ])
  })
})
