import { createPinia, setActivePinia } from 'pinia'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { boot, shutdown } from '@/api/boot'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { http } from '@/api/testing/serverHelpers'
import type { Schemas } from '@/api/types'
import { useSettingsStore } from '@/stores/settings'

const PORT = 8724
const TOKEN = 'diagnostics-u-test-token'

let server: DevServer

beforeAll(async () => {
  server = await startServer({ port: PORT, args: ['--token', TOKEN] })
}, 120_000)

afterAll(async () => {
  await server.stop()
})

beforeEach(async () => {
  setActivePinia(createPinia())
  await boot({ backend: async () => ({ baseUrl: server.url }), token: TOKEN })
})

afterEach(() => {
  shutdown()
})

describe('the Diagnostics section against a real server', () => {
  it('reads a report with text and the logs folder, without the token', async () => {
    const report = await http<Schemas['DiagnosticsReport']>(server, 'GET', '/api/diagnostics')
    expect(report.text.trim()).not.toBe('')
    expect(report.text).not.toContain(TOKEN)
    // The section shows the same folder as the report it copies.
    expect(report.logs_dir).not.toBe('')
    expect(report.text).toContain(`folder: ${report.logs_dir}\n`)
  })

  it('saves the log level with the change the section sends', async () => {
    const settings = useSettingsStore()
    await settings.load()
    await settings.set('/diagnostics/log_level', 'debug')
    const saved = await http<Schemas['AppSettings']>(server, 'GET', '/api/settings')
    expect(saved.diagnostics?.log_level).toBe('debug')
  })
})
