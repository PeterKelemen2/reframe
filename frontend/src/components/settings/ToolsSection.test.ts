import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { EncoderStatus, SystemInfo, TaskInfo } from '@/api/types'
import { platform } from '@/platform'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'
import { useTasksStore } from '@/stores/tasks'
import { useToastStore } from '@/stores/toasts'

import { mountSettings, refusal, systemInfo, toolBuilds } from './testing'
import ToolsSection from './ToolsSection.vue'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  vi.restoreAllMocks()
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

function ended(state: TaskInfo['state'], extra: Partial<TaskInfo> = {}): TaskInfo {
  return { id: 'fetch-1', kind: 'tools_fetch', state, ...extra } as TaskInfo
}

function fetchEnds(
  system: ReturnType<typeof useSystemStore>,
  state: TaskInfo['state'],
  extra: Partial<TaskInfo> = {},
) {
  system.fetchTools = vi.fn<(build?: string) => Promise<TaskInfo>>(async () => {
    const task = ended(state, extra)
    useTasksStore().tasks = { 'fetch-1': task }
    return task
  })
}

/** The download ends `done` with the server's masked result; then discovery finds `ffmpeg`. */
function installedThenFinds(
  system: ReturnType<typeof useSystemStore>,
  ffmpeg: Partial<SystemInfo['tools']['ffmpeg']>,
) {
  system.fetchTools = vi.fn<(build?: string) => Promise<TaskInfo>>(async () => {
    const info = system.info as SystemInfo
    system.info = {
      ...info,
      tools: { ...info.tools, ffmpeg: { ...info.tools.ffmpeg, ...ffmpeg } },
    }
    return ended('done', {
      result: {
        build: 'default',
        version: 'n9.0.2-17-g2a571b6068-20260930',
        install_dir: '<data>/tools/ffmpeg',
        ffmpeg: '<data>/tools/ffmpeg/bin/ffmpeg',
        ffprobe: '<data>/tools/ffmpeg/bin/ffprobe',
      },
    })
  })
}

describe('the Tools section', () => {
  it('shows FFmpeg and FFprobe with their status, version and where each comes from', async () => {
    const { row, wrapper } = await mountTools(
      systemInfo(
        {},
        {
          ffprobe: {
            status: 'missing',
            origin: null,
            path: null,
            version: null,
            reason: 'ffprobe was not found.',
          },
        },
      ),
    )
    const rows = wrapper.findAll('[data-tool]').map((found) => found.attributes('data-tool'))
    expect(rows).toEqual(['ffmpeg', 'ffprobe'])
    expect(row('ffmpeg').text()).toContain('Found')
    expect(row('ffmpeg').text()).toContain('9.0.2')
    expect(row('ffmpeg').find('[data-field="origin"]').text()).toBe('System PATH')
    expect(row('ffprobe').text()).toContain('Missing')
    expect(row('ffprobe').find('[data-tone]').attributes('data-tone')).toBe('error')
    expect(row('ffprobe').find('[data-field="origin"]').text()).toBe('Not found anywhere')
    expect(row('ffprobe').find('[data-field="reason"]').text()).toBe('ffprobe was not found.')
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
    expect(wrapper.find('[data-action="download"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-action="install-file"]').attributes('disabled')).toBeDefined()
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
      ffprobe: '/opt/ffprobe',
    })
    await row('ffprobe').find('[data-action="remove"]').trigger('click')
    await flushPromises()
    expect(server.patches).toEqual([[{ op: 'replace', path: '/tools/ffprobe', value: null }]])
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

  describe('the build picker', () => {
    it('lists the offered builds with summary, size and licence, the default chosen', async () => {
      const { wrapper } = await mountTools(systemInfo({ mode: 'desktop' }))
      const builds = wrapper.findAll('[data-build]').map((found) => found.attributes('data-build'))
      expect(builds).toEqual(['default', 'compat'])
      const first = wrapper.find('[data-build="default"]')
      expect(first.text()).toContain('Recommended')
      expect(first.text()).toContain('NVIDIA NVENC needs driver 610')
      expect(first.find('[data-field="facts"]').text()).toBe(
        'FFmpeg 9.0.2 · 65.5 MiB download · licence GPL-3.0-or-later',
      )
      expect(first.find('details a').exists()).toBe(false)
      const details = first.find('details').element as HTMLDetailsElement
      details.open = true
      details.dispatchEvent(new Event('toggle'))
      await flushPromises()
      expect(first.find('details a').attributes('href')).toContain('github.com/FFmpeg/FFmpeg')
      expect(first.find('details summary').text()).toBe('Source code and archive')
      expect(first.find('[data-field="archive-url"]').attributes('href')).toBe(
        toolBuilds().builds?.[0]?.archive_url,
      )
      expect(first.find('[data-field="archive-sha256"]').text()).toBe(
        '01a9764d0b5364b66cfeb4617557c64321b0e232e172ec73f0a701c5f7694326',
      )
      expect((first.find('input[type="radio"]').element as HTMLInputElement).checked).toBe(true)
    })

    it('downloads the chosen build, then removes the Settings paths that would still win', async () => {
      const { wrapper, server, system } = await mountTools(systemInfo({ mode: 'desktop' }), {
        ffmpeg: '/opt/ff/ffmpeg',
      })
      fetchEnds(system, 'done')
      await wrapper.find('[data-build="compat"] input[type="radio"]').setValue(true)
      await wrapper.find('[data-action="download"]').trigger('click')
      await flushPromises()
      expect(system.fetchTools).toHaveBeenCalledExactlyOnceWith('compat', { showsOffline: true })
      expect(server.patches).toEqual([[{ op: 'replace', path: '/tools/ffmpeg', value: null }]])
      expect(system.rescanTools).toHaveBeenCalledTimes(1)
    })

    it('keeps the paths when the download fails', async () => {
      const { wrapper, server, system } = await mountTools(systemInfo({ mode: 'desktop' }), {
        ffmpeg: '/opt/ff/ffmpeg',
      })
      fetchEnds(system, 'failed')
      await wrapper.find('[data-action="download"]').trigger('click')
      await flushPromises()
      expect(server.patches).toEqual([])
      expect(wrapper.find('[data-field="offline"]').exists()).toBe(false)
    })

    it('says that the download server cannot be reached and points to a file or a path', async () => {
      const { wrapper, system } = await mountTools(systemInfo({ mode: 'desktop' }))
      fetchEnds(system, 'failed', { error_code: 'tools.fetch_offline' })
      await wrapper.find('[data-build="compat"] input[type="radio"]').setValue(true)
      await wrapper.find('[data-action="download"]').trigger('click')
      await flushPromises()
      const offline = wrapper.find('[data-field="offline"]')
      expect(offline.attributes('role')).toBe('alert')
      expect(offline.text()).toContain('The download server cannot be reached')
      expect(offline.text()).toContain('archive file')
      expect(offline.text()).toContain('path')
      // The chosen build's archive, to download on a computer with a connection.
      const compat = toolBuilds().builds?.[1]
      expect(offline.find('[data-field="offline-archive"]').text()).toBe(
        'The archive of Older NVIDIA drivers (compat): ' +
          `${compat?.archive_url} · SHA-256 ${compat?.sha256}`,
      )
      expect(offline.find('[data-field="offline-archive"] a').attributes('href')).toBe(
        compat?.archive_url,
      )
    })

    it('installs an archive file that the file dialog picks as the chosen build', async () => {
      const { wrapper, system } = await mountTools(systemInfo({ mode: 'web' }))
      vi.spyOn(platform, 'pickFiles').mockResolvedValue(['/media/ffmpeg-n9.0.2-linux64.tar.xz'])
      system.installToolsFile = vi.fn<typeof system.installToolsFile>(async () => ended('done'))
      await wrapper.find('[data-build="compat"] input[type="radio"]').setValue(true)
      await wrapper.find('[data-action="install-file"]').trigger('click')
      await flushPromises()
      expect(platform.pickFiles).toHaveBeenCalledExactlyOnceWith({
        multiple: false,
        filters: ['.xz', '.zip'],
      })
      expect(system.installToolsFile).toHaveBeenCalledExactlyOnceWith(
        '/media/ffmpeg-n9.0.2-linux64.tar.xz',
        'compat',
        { showsOffline: true },
      )
    })

    it('takes the installed build as the one used when discovery finds a bundled ffmpeg of its version', async () => {
      const { wrapper, system } = await mountTools(systemInfo({ mode: 'web' }))
      installedThenFinds(system, {
        origin: 'bundled',
        bundled: true,
        path: '/srv/reframe/data/tools/ffmpeg/bin/ffmpeg',
        version: 'n9.0.2-17-g2a571b6068-20260930',
      })
      await wrapper.find('[data-action="download"]').trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-field="shadowed"]').exists()).toBe(false)
    })

    it('says which ffmpeg is used, and where it comes from, when it is not the installed build', async () => {
      const { wrapper, system } = await mountTools(systemInfo({ mode: 'web' }))
      installedThenFinds(system, { origin: 'env', path: '/opt/ff/ffmpeg', version: '7.1' })
      await wrapper.find('[data-action="download"]').trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-field="shadowed"]').text()).toBe(
        'The build is installed, but another FFmpeg comes first and is used: /opt/ff/ffmpeg ' +
          '(Environment variable REFRAME_FFMPEG)',
      )
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

  it('names each row’s field and buttons by its tool, so that no two of them share a name', async () => {
    const bundled = { bundled: true, origin: 'settings' as const }
    const { wrapper, row } = await mountTools(
      systemInfo(
        { mode: 'desktop' },
        { ffmpeg: { ...bundled, path: '/usr/bin/ffmpeg' }, ffprobe: { origin: 'settings' } },
      ),
      { ffmpeg: '/usr/bin/ffmpeg', ffprobe: '/opt/ffprobe' },
    )
    const name = (selector: string) => row('ffmpeg').find(selector).attributes('aria-label')
    expect(name('[data-field="override"]')).toBe('Path override for ffmpeg')
    expect(name('[data-action="test"]')).toBe('Test ffmpeg')
    expect(name('[data-action="use-bundled"]')).toBe('Use bundled ffmpeg')
    expect(row('ffprobe').find('[data-action="remove"]').attributes('aria-label')).toBe(
      'Remove override for ffprobe',
    )
    const names = wrapper
      .findAll('.tool-row input, .tool-row button')
      .map((control) => control.attributes('aria-label') ?? control.text())
    expect(new Set(names).size).toBe(names.length)
  })

  describe('Use bundled, with a bundled build', () => {
    const bundledFfmpeg = { bundled: true, origin: 'bundled' as const }

    it('removes the Settings paths of ffmpeg and ffprobe together, with no download', async () => {
      const { row, server, system } = await mountTools(
        systemInfo(
          { mode: 'desktop' },
          {
            ffmpeg: { ...bundledFfmpeg, origin: 'settings', path: '/usr/bin/ffmpeg' },
            ffprobe: { ...bundledFfmpeg, origin: 'settings', path: '/usr/bin/ffprobe' },
          },
        ),
        { ffmpeg: '/usr/bin/ffmpeg', ffprobe: '/usr/bin/ffprobe' },
      )
      fetchEnds(system, 'done')
      expect(row('ffmpeg').find('[data-action="remove"]').exists()).toBe(false)

      await row('ffprobe').find('[data-action="use-bundled"]').trigger('click')
      await flushPromises()
      expect(system.fetchTools).not.toHaveBeenCalled()
      expect(server.patches).toEqual([
        [
          { op: 'replace', path: '/tools/ffmpeg', value: null },
          { op: 'replace', path: '/tools/ffprobe', value: null },
        ],
      ])
      expect(system.rescanTools).toHaveBeenCalledTimes(1)
      expect(
        (row('ffmpeg').find('[data-field="override"]').element as HTMLInputElement).value,
      ).toBe('')
    })

    it('is not offered when the bundled build is in use already, or the environment sets the tool', async () => {
      const { row } = await mountTools(
        systemInfo(
          { mode: 'desktop' },
          {
            ffmpeg: bundledFfmpeg,
            ffprobe: { ...bundledFfmpeg, origin: 'env', path: '/env/ffprobe' },
          },
        ),
        { ffprobe: '/opt/ffprobe' },
      )
      expect(row('ffmpeg').find('[data-action="use-bundled"]').exists()).toBe(false)
      expect(row('ffprobe').find('[data-action="use-bundled"]').exists()).toBe(false)
    })

    it('is offered only on a row whose own tool has a Settings path', async () => {
      const { row, server } = await mountTools(
        systemInfo(
          { mode: 'desktop' },
          {
            ffmpeg: bundledFfmpeg,
            ffprobe: { ...bundledFfmpeg, origin: 'settings', path: '/opt/ff/ffprobe' },
          },
        ),
        { ffprobe: '/opt/ff/ffprobe' },
      )
      expect(row('ffmpeg').find('[data-action="use-bundled"]').exists()).toBe(false)
      expect(row('ffprobe').find('[data-field="bundled-note"]').exists()).toBe(false)

      await row('ffprobe').find('[data-action="use-bundled"]').trigger('click')
      await flushPromises()
      expect(server.patches).toEqual([[{ op: 'replace', path: '/tools/ffprobe', value: null }]])
    })

    it('says that the reset removes the other FFmpeg path too', async () => {
      const { row } = await mountTools(
        systemInfo(
          { mode: 'desktop' },
          {
            ffmpeg: { ...bundledFfmpeg, origin: 'settings' },
            ffprobe: { ...bundledFfmpeg, origin: 'settings' },
          },
        ),
        { ffmpeg: '/opt/ff/ffmpeg', ffprobe: '/opt/ff/ffprobe' },
      )
      expect(row('ffmpeg').find('[data-field="bundled-note"]').text()).toBe(
        'Use bundled also removes the path of ffprobe.',
      )
      expect(row('ffprobe').find('[data-field="bundled-note"]').text()).toBe(
        'Use bundled also removes the path of ffmpeg.',
      )
    })

    describe('a damaged bundled FFmpeg with no Settings path', () => {
      const damaged = {
        ffmpeg: bundledFfmpeg,
        ffprobe: {
          ...bundledFfmpeg,
          status: 'missing' as const,
          path: null,
          version: null,
          reason: 'The bundled FFmpeg has no ffprobe: the installation is damaged.',
        },
      }

      it('is downloaded again in web mode, where the data folder holds it', async () => {
        const { wrapper, server, system } = await mountTools(systemInfo({ mode: 'web' }, damaged))
        fetchEnds(system, 'done')
        await wrapper.find('[data-action="download"]').trigger('click')
        await flushPromises()
        expect(system.fetchTools).toHaveBeenCalledTimes(1)
        expect(server.patches).toEqual([])
      })

      it('is downloaded again before a Settings path is removed in web mode', async () => {
        const { wrapper, server, system } = await mountTools(
          systemInfo(
            { mode: 'web' },
            { ...damaged, ffmpeg: { ...bundledFfmpeg, origin: 'settings', path: '/opt/x/ffmpeg' } },
          ),
          { ffmpeg: '/opt/x/ffmpeg' },
        )
        fetchEnds(system, 'done')
        await wrapper.find('[data-action="download"]').trigger('click')
        await flushPromises()
        expect(system.fetchTools).toHaveBeenCalledTimes(1)
        expect(server.patches).toEqual([[{ op: 'replace', path: '/tools/ffmpeg', value: null }]])
      })
    })

    it('shows a refused reset at the field and does not check the tools', async () => {
      const { row, server, system } = await mountTools(
        systemInfo({ mode: 'desktop' }, { ffprobe: { bundled: true, origin: 'settings' } }),
        { ffprobe: '/opt/ffprobe' },
      )
      server.refuse = () => refusal(409, 'settings.conflict', 'The settings changed', 'Try again.')
      await row('ffprobe').find('[data-action="use-bundled"]').trigger('click')
      await flushPromises()
      expect(row('ffprobe').find('.rf-field__issue').text()).toContain(
        'The settings changed. Try again.',
      )
      expect(system.rescanTools).not.toHaveBeenCalled()
    })
  })
})

function status(id: string, extra: Partial<EncoderStatus>): EncoderStatus {
  return { id, state: 'unavailable', hardware: true, build_mismatch: false, ...extra }
}

describe('the installed build and the build mismatch', () => {
  it('names the installed build and offers the pinned one when it is outdated', async () => {
    const { wrapper, system, server } = await mountTools(systemInfo({ mode: 'desktop' }))
    server.builds = toolBuilds({
      installed: { name: 'default', version: 'n9.0.1-old', outdated: true },
    })
    await system.loadBuilds()
    await flushPromises()
    expect(wrapper.find('[data-field="installed-build"]').text()).toContain(
      'Installed build: Recommended (default), FFmpeg n9.0.1-old',
    )
    expect(wrapper.find('[data-field="outdated"]').text()).toContain(
      'This release pins another version of the build default.',
    )
    expect(wrapper.find('[data-build="default"] [data-field="installed"]').exists()).toBe(true)
    fetchEnds(system, 'done')
    await wrapper.find('[data-action="download-pinned"]').trigger('click')
    await flushPromises()
    expect(system.fetchTools).toHaveBeenCalledExactlyOnceWith('default', {})
  })

  it('toasts a download of the pinned build that cannot reach the server', async () => {
    const { wrapper, system, server } = await mountTools(systemInfo({ mode: 'desktop' }))
    server.builds = toolBuilds({
      installed: { name: 'default', version: 'n9.0.1-old', outdated: true },
    })
    server.on(
      'POST /api/system/tools/fetch',
      () => new Response(JSON.stringify({ task_id: 'o1' }), { status: 202 }),
    )
    server.on('GET /api/system', () => systemInfo({ mode: 'desktop' }))
    await system.loadBuilds()
    await flushPromises()
    await wrapper.find('[data-action="download-pinned"]').trigger('click')
    await flushPromises()
    const error = 'cannot reach the download server github.com (Connection refused)'
    useTasksStore().onTaskDone({
      type: 'task.done',
      task: {
        id: 'o1',
        kind: 'tools_fetch',
        state: 'failed',
        error,
        error_code: 'tools.fetch_offline',
      },
    })
    await flushPromises()
    expect(useToastStore().items).toEqual([
      expect.objectContaining({ severity: 'error', detail: error }),
    ])
  })

  it('names each encoder that another build can make available, with its reason', async () => {
    const { wrapper, system } = await mountTools(systemInfo({ mode: 'desktop' }))
    system.capabilities = {
      detecting: false,
      encoders: {
        hevc_nvenc: status('hevc_nvenc', {
          reason: 'NVIDIA driver too old: NVENC needs driver 610.00 or newer',
          build_mismatch: true,
        }),
        h264_qsv: status('h264_qsv', { reason: 'No Intel GPU' }),
      },
    } as never
    await flushPromises()
    const notice = wrapper.find('[data-field="mismatch-notice"]')
    expect(notice.text()).toContain('need newer system software than this FFmpeg build expects')
    expect(notice.findAll('[data-encoder]').map((item) => item.text())).toEqual([
      'hevc_nvenc: NVIDIA driver too old: NVENC needs driver 610.00 or newer',
    ])
  })

  it('shows no notice without a build mismatch', async () => {
    const { wrapper } = await mountTools(systemInfo())
    expect(wrapper.find('[data-field="mismatch-notice"]').exists()).toBe(false)
    expect(wrapper.find('[data-field="installed-build"]').exists()).toBe(false)
  })
})
