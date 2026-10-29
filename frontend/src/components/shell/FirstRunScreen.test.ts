import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { deferred } from '@/api/testing/fakes'
import type { Schemas, SystemInfo, TaskInfo } from '@/api/types'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'
import { useTasksStore } from '@/stores/tasks'

import FirstRunScreen from './FirstRunScreen.vue'
import { mountShell } from './testing'

type ToolInfo = Schemas['ToolInfo']

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

function tool(name: ToolInfo['name'], extra: Partial<ToolInfo>): ToolInfo {
  return { name, status: 'found', ...extra } as ToolInfo
}

function info(
  ffmpeg: Partial<ToolInfo>,
  ffprobe: Partial<ToolInfo>,
  mode: 'web' | 'desktop' = 'desktop',
): SystemInfo {
  return {
    mode,
    tools: {
      ffmpeg: tool('ffmpeg', ffmpeg),
      ffprobe: tool('ffprobe', ffprobe),
      mkvpropedit: tool('mkvpropedit', {}),
      mediainfo: tool('mediainfo', {}),
    },
  } as SystemInfo
}

async function mountFirstRun(systemInfo: SystemInfo) {
  const result = await mountShell(FirstRunScreen, {
    setup: () => {
      useSystemStore().info = systemInfo
    },
  })
  mounted.push(result.wrapper)
  return { ...result, system: useSystemStore() }
}

function toolRow(name: string) {
  return document.querySelector(`[data-tool="${name}"]`)
}

describe('the first-run screen', () => {
  it('shows the reason and where each binary came from', async () => {
    const { wrapper } = await mountFirstRun(
      info(
        {
          status: 'missing',
          origin: 'settings',
          path: '/opt/missing/ffmpeg',
          reason: '/opt/missing/ffmpeg does not exist',
        },
        { status: 'found', origin: 'path', path: '/usr/bin/ffprobe', version: '9.0.2' },
      ),
    )
    expect(wrapper.find('.first-run__reason').text()).toBe('/opt/missing/ffmpeg does not exist')
    expect(toolRow('ffmpeg')?.textContent).toContain('Missing')
    expect(toolRow('ffmpeg')?.querySelector('[data-field="origin"]')?.textContent).toBe(
      'From a path in the settings',
    )
    expect(toolRow('ffmpeg')?.querySelector('[data-field="path"]')?.textContent).toBe(
      '/opt/missing/ffmpeg',
    )
    expect(toolRow('ffprobe')?.querySelector('[data-field="origin"]')?.textContent).toBe(
      'From the system PATH',
    )
    expect(toolRow('ffprobe')?.textContent).toContain('Version 9.0.2')
  })

  it.each([
    ['env', 'From an environment variable'],
    ['bundled', 'Bundled with Reframe'],
    [null, 'Not found anywhere'],
  ] as const)('names the origin %s', async (origin, label) => {
    await mountFirstRun(info({ status: 'broken', origin, reason: 'no' }, {}))
    expect(toolRow('ffmpeg')?.querySelector('[data-field="origin"]')?.textContent).toBe(label)
  })

  it('downloads the bundled FFmpeg and shows the progress of its task', async () => {
    const { wrapper, system } = await mountFirstRun(info({ status: 'missing', reason: 'gone' }, {}))
    const download = deferred()
    system.fetchTools = vi.fn<() => Promise<void>>(() => {
      system.toolsFetch = 't1'
      useTasksStore().tasks = {
        t1: { id: 't1', kind: 'tools.fetch', state: 'running', progress: 42 } as TaskInfo,
      }
      return download.promise
    })
    await wrapper.find('.first-run__bundled').trigger('click')
    await flushPromises()

    expect(system.fetchTools).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('42')
    expect(wrapper.find('.first-run__check').attributes('disabled')).toBeDefined()
    system.toolsFetch = null
    download.resolve()
    await flushPromises()
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
  })

  it('after the download, removes the Settings paths that would win over the bundled build', async () => {
    const { wrapper, system } = await mountFirstRun(
      info({ status: 'missing', origin: 'settings', reason: 'gone' }, {}),
    )
    const settings = useSettingsStore()
    settings.settings = { tools: { ffmpeg: '/opt/gone/ffmpeg', ffprobe: null } } as never
    settings.update = vi.fn<typeof settings.update>(async () => ({}) as never)
    system.rescanTools = vi.fn<() => Promise<void>>(async () => {})
    system.fetchTools = vi.fn<() => Promise<void>>(async () => {
      system.toolsFetch = 't1'
      useTasksStore().tasks = { t1: { id: 't1', kind: 'tools_fetch', state: 'done' } as TaskInfo }
      system.toolsFetch = null
    })
    await wrapper.find('.first-run__bundled').trigger('click')
    await flushPromises()
    expect(settings.update).toHaveBeenCalledExactlyOnceWith([
      { op: 'replace', path: '/tools/ffmpeg', value: null },
    ])
    expect(system.rescanTools).toHaveBeenCalledTimes(1)
  })

  it('keeps the Settings paths when the download failed', async () => {
    const { wrapper, system } = await mountFirstRun(info({ status: 'missing', reason: 'gone' }, {}))
    const settings = useSettingsStore()
    settings.settings = { tools: { ffmpeg: '/opt/gone/ffmpeg' } } as never
    settings.update = vi.fn<typeof settings.update>(async () => ({}) as never)
    system.fetchTools = vi.fn<() => Promise<void>>(async () => {
      system.toolsFetch = 't1'
      useTasksStore().tasks = { t1: { id: 't1', kind: 'tools_fetch', state: 'failed' } as TaskInfo }
      system.toolsFetch = null
    })
    await wrapper.find('.first-run__bundled').trigger('click')
    await flushPromises()
    expect(settings.update).not.toHaveBeenCalled()
  })

  it('offers only what can fix an environment override, and says what can', async () => {
    const { wrapper } = await mountFirstRun(
      info(
        { status: 'missing', origin: 'env', env_var: 'REFRAME_FFMPEG', reason: 'gone' },
        { status: 'found', origin: 'env', env_var: 'REFRAME_FFPROBE' },
      ),
    )
    expect(wrapper.find('.first-run__bundled').exists()).toBe(false)
    expect(wrapper.find('.first-run__choose').exists()).toBe(false)
    expect(wrapper.find('.first-run__check').exists()).toBe(true)
    expect(wrapper.find('[data-field="note"]').text()).toContain('sets the path (REFRAME_FFMPEG)')
  })

  it('offers no path in a browser, where the server refuses one, and names the variables', async () => {
    const { wrapper } = await mountFirstRun(
      info({ status: 'missing', env_var: 'REFRAME_FFMPEG', reason: 'gone' }, {}, 'web'),
    )
    expect(wrapper.find('.first-run__choose').exists()).toBe(false)
    expect(wrapper.find('.first-run__bundled').exists()).toBe(true)
    expect(wrapper.find('[data-field="note"]').text()).toContain('set REFRAME_FFMPEG on the server')
  })

  it('says when Check again found nothing new, and nothing when it did', async () => {
    const before = info({ status: 'missing', reason: 'gone' }, {})
    const { wrapper, system } = await mountFirstRun(before)
    const scan = deferred()
    system.rescanTools = vi.fn<() => Promise<void>>(async () => {
      await scan.promise
      system.info = structuredClone(before)
    })
    const check = wrapper.find<HTMLButtonElement>('.first-run__check').element
    check.focus()
    check.click()
    await flushPromises()
    // Busy, and still focused: a disabled button would drop the focus to the page.
    expect(check.disabled).toBe(false)
    expect(check.getAttribute('aria-disabled')).toBe('true')
    scan.resolve()
    await flushPromises()
    expect(wrapper.find('[data-field="checked"]').text()).toMatch(
      /^Checked again at .+: nothing has changed\.$/,
    )
    expect(document.activeElement).toBe(check)

    system.rescanTools = vi.fn<() => Promise<void>>(async () => {
      system.info = info({ status: 'broken', reason: 'still bad' }, {})
    })
    check.click()
    await flushPromises()
    expect(wrapper.find('[data-field="checked"]').text()).toBe('')
  })

  it('checks the tools again, and stays when the server refuses', async () => {
    const { wrapper, system } = await mountFirstRun(info({ status: 'missing', reason: 'gone' }, {}))
    system.rescanTools = vi.fn<() => Promise<void>>(async () => {
      throw new ApiError(503, {
        type: 'about:blank',
        title: 'Busy',
        status: 503,
        code: 'busy',
      })
    })
    await wrapper.find('.first-run__check').trigger('click')
    await flushPromises()
    expect(system.rescanTools).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.first-run__check').attributes('disabled')).toBeUndefined()
  })

  it('takes Choose path to the Tools section of Settings', async () => {
    const { wrapper, router } = await mountFirstRun(info({ status: 'missing', reason: 'gone' }, {}))
    await wrapper.find('.first-run__choose').trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('settings'))
    expect(router.currentRoute.value.hash).toBe('#tools')
  })
})
