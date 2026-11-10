import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { SystemInfo, TaskInfo } from '@/api/types'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'
import { useTasksStore } from '@/stores/tasks'

import { mountSettings, refusal, systemInfo } from './testing'
import ToolsSection from './ToolsSection.vue'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountTools(info: SystemInfo, overrides: Record<string, string> = {}) {
  const result = await mountSettings(ToolsSection, { info })
  mounted.push(result.wrapper)
  const settings = useSettingsStore()
  if (settings.settings?.tools) Object.assign(settings.settings.tools, overrides)
  Object.assign(result.server.document.tools ?? {}, overrides)
  await flushPromises()
  const system = useSystemStore()
  /** The tools the next re-scan finds. */
  let next: SystemInfo['tools'] = info.tools
  system.rescanTools = vi.fn<() => Promise<void>>(async () => {
    system.info = { ...(system.info as SystemInfo), tools: next }
  })
  return {
    ...result,
    system,
    row: (name: string) => result.wrapper.find(`[data-tool="${name}"]`),
    findsNext(tools: SystemInfo['tools']) {
      next = tools
    },
  }
}

function fetchEnds(system: ReturnType<typeof useSystemStore>, state: TaskInfo['state']) {
  system.fetchTools = vi.fn<() => Promise<void>>(async () => {
    system.toolsFetch = 'fetch-1'
    useTasksStore().tasks = {
      'fetch-1': { id: 'fetch-1', kind: 'tools.fetch', state } as TaskInfo,
    }
    system.toolsFetch = null
  })
}

describe('the Tools section', () => {
  it('shows each tool with its status, version and where it comes from', async () => {
    const { row } = await mountTools(
      systemInfo({}, { mediainfo: { status: 'missing', origin: null, path: null, version: null } }),
    )
    expect(row('ffmpeg').text()).toContain('Found')
    expect(row('ffmpeg').text()).toContain('9.0.2')
    expect(row('ffmpeg').find('[data-field="origin"]').text()).toBe('System PATH')
    expect(row('mediainfo').text()).toContain('Missing')
    expect(row('mediainfo').find('[data-field="origin"]').text()).toBe('Not found anywhere')
  })

  it('shows an environment override read-only, says which variable to change, and keeps Use bundled off', async () => {
    const env = { origin: 'env' as const, path: '/opt/ff/ffmpeg' }
    const { row, wrapper } = await mountTools(
      systemInfo(
        { mode: 'desktop' },
        { ffmpeg: env, ffprobe: { ...env, path: '/opt/ff/ffprobe' } },
      ),
    )
    const field = row('ffmpeg').find('[data-field="override"]')
    expect(field.attributes('readonly')).toBeDefined()
    expect((field.element as HTMLInputElement).value).toBe('/opt/ff/ffmpeg')
    expect(row('ffmpeg').find('[data-field="note"]').text()).toContain('REFRAME_FFMPEG')
    expect(row('ffmpeg').find('[data-field="origin"]').text()).toContain('REFRAME_FFMPEG')
    expect(row('ffmpeg').find('[data-action="remove"]').exists()).toBe(false)
    expect(wrapper.find('[data-action="use-bundled"]').attributes('disabled')).toBeDefined()
    expect(
      row('mkvpropedit').find('[data-field="override"]').attributes('readonly'),
    ).toBeUndefined()
  })

  it('keeps an ffprobe found next to an overridden ffmpeg editable', async () => {
    const { row } = await mountTools(
      systemInfo(
        { mode: 'desktop' },
        { ffmpeg: { origin: 'env' }, ffprobe: { origin: 'env', next_to_ffmpeg: true } },
      ),
    )
    expect(row('ffprobe').find('[data-field="override"]').attributes('readonly')).toBeUndefined()
  })

  it('in web mode shows the path read-only and Test only checks the tools again', async () => {
    const { row, server, system } = await mountTools(systemInfo({ mode: 'web' }))
    expect(row('ffmpeg').find('[data-field="override"]').attributes('readonly')).toBeDefined()
    expect(row('ffmpeg').find('[data-field="note"]').text()).toContain('REFRAME_FFMPEG')
    await row('ffmpeg').find('[data-action="test"]').trigger('click')
    await flushPromises()
    expect(system.rescanTools).toHaveBeenCalledTimes(1)
    expect(server.patches).toEqual([])
    expect(row('ffmpeg').find('[data-field="outcome"]').text()).toBe('Works: version 9.0.2')
  })

  it('removes a Settings path in web mode and checks the tools again', async () => {
    const { row, server, system } = await mountTools(systemInfo({ mode: 'web' }), {
      mediainfo: '/opt/mediainfo',
    })
    await row('mediainfo').find('[data-action="remove"]').trigger('click')
    await flushPromises()
    expect(server.patches).toEqual([[{ op: 'replace', path: '/tools/mediainfo', value: null }]])
    expect(system.rescanTools).toHaveBeenCalledTimes(1)
  })

  it('tests a new path: saves it, checks the tools, and offers to put back the old one when it fails', async () => {
    const { row, server, system, findsNext } = await mountTools(systemInfo({ mode: 'desktop' }), {
      ffmpeg: '/opt/old/ffmpeg',
    })
    findsNext(
      systemInfo(
        {},
        {
          ffmpeg: {
            status: 'missing',
            origin: 'settings',
            path: '/wrong/ffmpeg',
            reason: 'the file does not exist',
          },
        },
      ).tools,
    )
    await row('ffmpeg').find('[data-field="override"]').setValue('/wrong/ffmpeg')
    await row('ffmpeg').find('[data-action="test"]').trigger('click')
    await flushPromises()

    expect(server.patches).toEqual([
      [{ op: 'replace', path: '/tools/ffmpeg', value: '/wrong/ffmpeg' }],
    ])
    expect(system.rescanTools).toHaveBeenCalledTimes(1)
    const outcome = row('ffmpeg').find('[data-field="outcome"]')
    expect(outcome.text()).toContain('Does not work: the file does not exist')
    const putBack = row('ffmpeg').find('[data-action="put-back"]')
    expect(putBack.text()).toBe('Put back /opt/old/ffmpeg')

    findsNext(systemInfo().tools)
    await putBack.trigger('click')
    await flushPromises()
    expect(server.patches.at(-1)).toEqual([
      { op: 'replace', path: '/tools/ffmpeg', value: '/opt/old/ffmpeg' },
    ])
    expect(system.rescanTools).toHaveBeenCalledTimes(2)
    expect((row('ffmpeg').find('[data-field="override"]').element as HTMLInputElement).value).toBe(
      '/opt/old/ffmpeg',
    )
    expect(row('ffmpeg').find('[data-action="put-back"]').exists()).toBe(false)
  })

  it('offers automatic discovery back when a first path fails', async () => {
    const { row, findsNext } = await mountTools(systemInfo({ mode: 'desktop' }))
    findsNext(systemInfo({}, { ffmpeg: { status: 'broken', reason: 'not a program' } }).tools)
    await row('ffmpeg').find('[data-field="override"]').setValue('/tmp/x')
    await row('ffmpeg').find('[data-action="test"]').trigger('click')
    await flushPromises()
    expect(row('ffmpeg').find('[data-action="put-back"]').text()).toBe('Put back automatic')
  })

  it('tests an unchanged path without saving, and a working new path offers nothing to put back', async () => {
    const { row, server, system } = await mountTools(systemInfo({ mode: 'desktop' }))
    await row('ffmpeg').find('[data-action="test"]').trigger('click')
    await flushPromises()
    expect(server.patches).toEqual([])
    expect(system.rescanTools).toHaveBeenCalledTimes(1)

    await row('ffmpeg').find('[data-field="override"]').setValue('/opt/good/ffmpeg')
    await row('ffmpeg').find('[data-action="test"]').trigger('click')
    await flushPromises()
    expect(server.patches).toHaveLength(1)
    expect(row('ffmpeg').find('[data-field="outcome"]').text()).toContain('Works')
    expect(row('ffmpeg').find('[data-action="put-back"]').exists()).toBe(false)
  })

  it('shows a refused path at its field and does not check the tools', async () => {
    const { row, server, system } = await mountTools(systemInfo({ mode: 'desktop' }))
    server.refuse = () =>
      refusal(403, 'settings.tools_forbidden', 'A web client cannot choose the programs', 'Set it.')
    await row('ffmpeg').find('[data-field="override"]').setValue('/opt/x')
    await row('ffmpeg').find('[data-action="test"]').trigger('click')
    await flushPromises()
    expect(row('ffmpeg').find('.rf-field__issue').text()).toContain(
      'A web client cannot choose the programs. Set it.',
    )
    expect(system.rescanTools).not.toHaveBeenCalled()
    expect(row('ffmpeg').find('[data-field="outcome"]').exists()).toBe(false)
  })

  describe('Use bundled FFmpeg', () => {
    it('downloads FFmpeg, then removes the Settings paths that would still win', async () => {
      const { wrapper, server, system } = await mountTools(systemInfo({ mode: 'desktop' }), {
        ffmpeg: '/opt/ff/ffmpeg',
        mkvpropedit: '/opt/mkvpropedit',
      })
      fetchEnds(system, 'done')
      await wrapper.find('[data-action="use-bundled"]').trigger('click')
      await flushPromises()
      expect(system.fetchTools).toHaveBeenCalledTimes(1)
      expect(server.patches).toEqual([[{ op: 'replace', path: '/tools/ffmpeg', value: null }]])
      expect(system.rescanTools).toHaveBeenCalledTimes(1)
    })

    it('removes the Settings paths without a download when the app ships FFmpeg', async () => {
      const shipped = { bundled_dir: '/opt/Reframe/tools/ffmpeg' }
      const { wrapper, server, system } = await mountTools(
        systemInfo({ mode: 'desktop' }, { ffmpeg: shipped, ffprobe: shipped }),
        { ffmpeg: '/opt/ff/ffmpeg' },
      )
      fetchEnds(system, 'done')
      await wrapper.find('[data-action="use-bundled"]').trigger('click')
      await flushPromises()
      expect(system.fetchTools).not.toHaveBeenCalled()
      expect(server.patches).toEqual([[{ op: 'replace', path: '/tools/ffmpeg', value: null }]])
      expect(system.rescanTools).toHaveBeenCalledTimes(1)
    })

    it('keeps the paths when the download fails', async () => {
      const { wrapper, server, system } = await mountTools(systemInfo({ mode: 'desktop' }), {
        ffmpeg: '/opt/ff/ffmpeg',
      })
      fetchEnds(system, 'failed')
      await wrapper.find('[data-action="use-bundled"]').trigger('click')
      await flushPromises()
      expect(server.patches).toEqual([])
    })

    it('shows the download progress of its task', async () => {
      const { wrapper, system } = await mountTools(systemInfo())
      system.toolsFetch = 'fetch-2'
      useTasksStore().tasks = {
        'fetch-2': {
          id: 'fetch-2',
          kind: 'tools.fetch',
          state: 'running',
          progress: 37,
        } as TaskInfo,
      }
      await flushPromises()
      expect(wrapper.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('37')
    })
  })
})
