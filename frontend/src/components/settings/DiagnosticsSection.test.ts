import { flushPromises, type VueWrapper } from '@vue/test-utils'
import Select from 'primevue/select'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { deferred, problem } from '@/api/testing/fakes'
import type { SystemInfo } from '@/api/types'
import { mountShell } from '@/components/shell/testing'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

import DiagnosticsSection from './DiagnosticsSection.vue'
import { comboboxName, SettingsServer, systemInfo } from './testing'

globalThis.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }) as unknown as MediaQueryList

const LOGS = '~/.local/share/reframe/logs'
const writeText = vi.fn<(text: string) => Promise<void>>(async () => {})
const mounted: VueWrapper[] = []

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

/** A server whose report says how many times it was read, so a stale copy shows. */
async function mountDiagnostics(info: SystemInfo = systemInfo()) {
  const server = new SettingsServer()
  server.document.diagnostics = { log_level: 'info' }
  let reads = 0
  server.on('GET /api/diagnostics', () => {
    reads += 1
    return { text: `Reframe report ${reads}\n`, logs_dir: LOGS }
  })
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  const result = await mountShell(DiagnosticsSection, {
    setup: () => {
      useSystemStore().info = info
      useSettingsStore().settings = structuredClone(server.document)
      useSettingsStore().loaded = true
    },
  })
  mounted.push(result.wrapper)
  const level = () => result.wrapper.findComponent(Select)
  const copyButton = () => result.wrapper.get('[data-action="copy-diagnostics"]')
  const status = () => result.wrapper.get('[data-field="copy-status"]')
  const report = () => result.wrapper.find<HTMLTextAreaElement>('textarea[data-field="report"]')
  async function copy(): Promise<void> {
    await copyButton().trigger('click')
    await flushPromises()
  }
  return { ...result, server, level, copyButton, status, report, copy }
}

describe('the Diagnostics section', () => {
  it('sets the log level with one setting change', async () => {
    const { level, server } = await mountDiagnostics()
    level().vm.$emit('update:modelValue', 'debug')
    await flushPromises()
    expect(server.patches).toEqual([
      [{ op: 'replace', path: '/diagnostics/log_level', value: 'debug' }],
    ])
    expect(level().props('modelValue')).toBe('debug')
  })

  it('names the level list by its label, and offers the four levels in plain words', async () => {
    const { level } = await mountDiagnostics()
    expect(comboboxName('log-level')).toBe('Log level')
    const options = level().props('options') as { value: string; label: string }[]
    expect(options.map((option) => option.value)).toEqual(['error', 'warning', 'info', 'debug'])
    expect(options.every((option) => option.label !== option.value)).toBe(true)
  })

  it('shows read-only settings with the level locked, and still copies', async () => {
    const { level, copyButton, copy } = await mountDiagnostics(
      systemInfo({ settings_read_only: true }),
    )
    expect(level().props('disabled')).toBe(true)
    expect(copyButton().attributes('disabled')).toBeUndefined()
    await copy()
    expect(writeText).toHaveBeenCalledOnce()
  })

  it('shows the logs folder in a field that can be selected, with what it holds', async () => {
    const { wrapper } = await mountDiagnostics()
    const input = wrapper.get<HTMLInputElement>('[data-field="logs-dir"]')
    expect(input.element.value).toBe(LOGS)
    expect(input.attributes('readonly')).toBeDefined()
    const described = input.attributes('aria-describedby') ?? ''
    expect(document.getElementById(described)?.textContent?.trim()).toBe(
      "On the server's computer. Holds the app log (reframe.log) and a log for each job. " +
        '~ is the home folder.',
    )
  })

  it('names the sidecar log in the desktop app, and no home folder for a path without ~', async () => {
    const server = new SettingsServer()
    server.on('GET /api/diagnostics', { text: '', logs_dir: '/var/lib/reframe/logs' })
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
    const { wrapper } = await mountShell(DiagnosticsSection, {
      setup: () => {
        useSystemStore().info = systemInfo({ mode: 'desktop' })
        useSettingsStore().settings = structuredClone(server.document)
      },
    })
    mounted.push(wrapper)
    const described = wrapper.get('[data-field="logs-dir"]').attributes('aria-describedby') ?? ''
    expect(document.getElementById(described)?.textContent?.trim()).toBe(
      'Holds the app log (reframe.log), a log for each job and sidecar.log.',
    )
  })

  it('says why the logs folder could not be read', async () => {
    const server = new SettingsServer()
    server.on('GET /api/diagnostics', () => problem(503, 'busy', 'The server is busy'))
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
    const { wrapper } = await mountShell(DiagnosticsSection, {
      setup: () => {
        useSystemStore().info = systemInfo()
        useSettingsStore().settings = structuredClone(server.document)
      },
    })
    mounted.push(wrapper)
    expect(wrapper.find('.rf-field__issue').text()).toContain('The server is busy')
  })

  it('reads the report when Copy is pressed and copies it with the client part', async () => {
    const { server, copy } = await mountDiagnostics()
    const atLoad = server.count('GET /api/diagnostics')
    await copy()
    expect(server.count('GET /api/diagnostics')).toBe(atLoad + 1)
    // The client part is one more section of the report, in the server's layout.
    expect(writeText).toHaveBeenCalledWith(
      [
        `Reframe report ${atLoad + 1}`,
        '',
        'Client',
        '  kind: web',
        `  user agent: ${navigator.userAgent}`,
        `  device pixel ratio: ${globalThis.devicePixelRatio}`,
        '',
      ].join('\n'),
    )
  })

  it('keeps Copy focusable while it reads, says so, and reads once for a second press', async () => {
    const { server, copyButton, status } = await mountDiagnostics()
    const answer = deferred<unknown>()
    server.on('GET /api/diagnostics', () => answer.promise)
    const atLoad = server.count('GET /api/diagnostics')
    await copyButton().trigger('click')
    await copyButton().trigger('click')
    await flushPromises()
    // A disabled button drops the keyboard focus to the page.
    expect(copyButton().attributes('disabled')).toBeUndefined()
    expect(status().text()).toBe('Reading the diagnostics…')
    expect(server.count('GET /api/diagnostics')).toBe(atLoad + 1)
    answer.resolve({ text: 'Reframe report\n', logs_dir: LOGS })
    await flushPromises()
    expect(writeText).toHaveBeenCalledOnce()
  })

  it('announces the copy in a live region that is there before it', async () => {
    const { status, copy, report } = await mountDiagnostics()
    expect(status().attributes('role')).toBe('status')
    expect(status().text()).toBe('')
    await copy()
    expect(status().text()).toBe('Diagnostics copied to the clipboard.')
    expect(report().exists()).toBe(false)
  })

  it.each([
    [
      'refuses the text',
      () => writeText.mockRejectedValueOnce(new DOMException('No', 'NotAllowedError')),
    ],
    [
      'is missing (plain http)',
      () => Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true }),
    ],
  ])('shows the report to select and copy when the clipboard %s', async (_case, arrange) => {
    const { status, copy, report } = await mountDiagnostics()
    arrange()
    await copy()
    expect(status().text()).toContain('Select the report below and copy it')
    expect(report().element.value).toContain('Reframe report')
    expect(report().element.value).toContain('  user agent:')
    expect(report().attributes('readonly')).toBeDefined()
    expect(document.activeElement).toBe(report().element)
  })

  it('hides the shown report again once a copy works', async () => {
    const { copy, report } = await mountDiagnostics()
    writeText.mockRejectedValueOnce(new DOMException('No', 'NotAllowedError'))
    await copy()
    expect(report().exists()).toBe(true)
    await copy()
    expect(report().exists()).toBe(false)
  })

  it('says why the report could not be read, and copies nothing', async () => {
    const { server, status, copy, report } = await mountDiagnostics()
    server.on('GET /api/diagnostics', () => problem(503, 'busy', 'The server is busy'))
    await copy()
    expect(status().text()).toBe('The diagnostics could not be read: The server is busy')
    expect(writeText).not.toHaveBeenCalled()
    expect(report().exists()).toBe(false)
  })
})
