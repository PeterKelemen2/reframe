import { createPinia, setActivePinia } from 'pinia'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope, ref } from 'vue'

import { configureClient } from '@/api/client'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { endedTask, http } from '@/api/testing/serverHelpers'
import { useCommandPlan } from '@/components/video/useCommandPlan'
import { pinnedTools } from '@/editor/testing/tools.mjs'
import { useEditorStore } from '@/stores/editor'

import { optionPointer } from './options'
import { useOptionSearch } from './useOptionSearch'

const PORT = 8712
const PRESET = 'h265-mkv-1080p'
const SOON = { timeout: 15_000, interval: 50 }

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

describe('against the real server', () => {
  it('finds psy-rd and psy-rdoq first for "psy" on libx265', async () => {
    const query = ref('')
    const { matches } = scope.run(() =>
      useOptionSearch(
        () => 'libx265',
        () => query.value,
      ),
    )!
    query.value = 'psy'
    await vi.waitFor(() => expect(matches.value).not.toBeNull(), SOON)
    const keys = matches.value!.map((option) => option.key)
    expect(keys.slice(0, 2)).toEqual(['psy-rd', 'psy-rdoq'])
  })

  it("puts a changed option into the plan's command, and a reset takes it out", async () => {
    const editor = useEditorStore()
    await editor.open(sourceId, PRESET)
    const { plan } = scope.run(() => useCommandPlan(ref(true)))!
    await vi.waitFor(() => expect(plan.value?.display).toContain('-x265-params'), SOON)
    expect(plan.value?.display).not.toContain('bframes=')
    editor.set(optionPointer('bframes'), 6)
    await vi.waitFor(() => expect(plan.value?.display).toContain(':bframes=6'), SOON)
    editor.patch([{ op: 'remove', path: optionPointer('bframes') }])
    await vi.waitFor(() => expect(plan.value?.display).not.toContain('bframes='), SOON)
  })
})
