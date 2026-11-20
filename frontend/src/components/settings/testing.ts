import type { Pinia } from 'pinia'
import { applyPatch } from 'rfc6902'
import type { Component } from 'vue'

import { configureClient } from '@/api/client'
import { FakeServer, problem } from '@/api/testing/fakes'
import type { AppSettings, JsonPatchOp, Schemas, SystemInfo } from '@/api/types'
import { mountShell } from '@/components/shell/testing'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

type ToolInfo = Schemas['ToolInfo']

export function defaultSettings(): AppSettings {
  return {
    schema_version: 1,
    tools: { ffmpeg: null, ffprobe: null },
    encoders: { hardware_tests: true, vaapi_device: null },
    output: {
      naming: {
        movie_template: '{main_title}',
        episode_template: '{main_title}',
        name_source: 'auto',
        word_separator: 'keep',
        title_case: false,
        replace_underscores: false,
        remove_punctuation: false,
        mp4_extension: 'mp4',
        output_folder_mode: 'fixed',
        output_folder: '/media/out',
      },
      collision: 'auto_rename',
      partial_file: 'delete',
    },
    queue: { parallel_jobs: 1, when_done: 'nothing', sleep_inhibit: true, notifications: true },
    appearance: { theme: 'system', density: 'comfortable', ui_language: 'en' },
  } as AppSettings
}

export function tool(name: ToolInfo['name'], extra: Partial<ToolInfo> = {}): ToolInfo {
  return {
    name,
    status: 'found',
    origin: 'path',
    path: `/usr/bin/${name}`,
    version: '9.0.2',
    env_var: `REFRAME_${name.toUpperCase()}`,
    next_to_ffmpeg: false,
    bundled: false,
    ...extra,
  } as ToolInfo
}

/** The offered builds as the server lists them on linux-x64, none installed. */
export function toolBuilds(extra: Partial<Schemas['ToolBuilds']> = {}): Schemas['ToolBuilds'] {
  return {
    builds: [
      {
        name: 'default',
        label: 'Recommended',
        summary: 'The build Reframe is tested with. NVIDIA NVENC needs driver 610 or newer.',
        version: 'n9.0.2-17-g2a571b6068-20260930',
        release_version: '9.0.2',
        license: 'GPL-3.0-or-later',
        source_links: ['https://github.com/FFmpeg/FFmpeg/commit/2a571b6'],
        size: 68_653_636,
        archive_url:
          'https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-30-13-08/ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-shared-9.0.tar.xz',
        sha256: '01a9764d0b5364b66cfeb4617557c64321b0e232e172ec73f0a701c5f7694326',
      },
      {
        name: 'compat',
        label: 'Older NVIDIA drivers',
        summary: 'For NVIDIA drivers 570 to 609 (a GeForce 10 series card with driver 580).',
        version: 'n8.1.3-9-g29e619e767-20260930',
        release_version: '8.1.3',
        license: 'GPL-3.0-or-later',
        source_links: ['https://github.com/FFmpeg/FFmpeg/commit/29e619e'],
        size: 66_000_000,
        archive_url:
          'https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-30-13-08/ffmpeg-n8.1.3-9-g29e619e767-linux64-gpl-shared-8.1.tar.xz',
        sha256: '5d0c5c5b2c1d8a2b3e8f0f4b3b2d7c0e9a1f6b8c4d2e0a9f8b7c6d5e4f3a2b1c',
      },
    ],
    installed: null,
    ...extra,
  }
}

export function systemInfo(
  extra: Partial<SystemInfo> = {},
  tools: Partial<Record<ToolInfo['name'], Partial<ToolInfo>>> = {},
): SystemInfo {
  return {
    mode: 'web',
    auth: 'token',
    platform: 'linux',
    problems: [],
    settings_read_only: false,
    tools: { ffmpeg: tool('ffmpeg', tools.ffmpeg), ffprobe: tool('ffprobe', tools.ffprobe) },
    ...extra,
  } as SystemInfo
}

/**
 * A settings route that applies each patch like the server; `refuse` answers instead when it
 * returns a `Response` for the ops.
 */
export class SettingsServer extends FakeServer {
  document = defaultSettings()
  builds = toolBuilds()
  refuse: (ops: JsonPatchOp[]) => Response | undefined = () => undefined

  constructor() {
    super()
    this.on('GET /api/settings', () => structuredClone(this.document))
    this.on('GET /api/system/tools/builds', () => structuredClone(this.builds))
    this.on('PUT /api/settings', ({ body }) => {
      const ops = body as JsonPatchOp[]
      const refused = this.refuse(ops)
      if (refused) return refused
      const next = structuredClone(this.document)
      applyPatch(next, ops)
      this.document = next
      return { settings: structuredClone(next), changes: [], saved: true, warnings: [] }
    })
  }

  /** The bodies of the settings patches sent so far. */
  get patches(): JsonPatchOp[][] {
    return this.requests
      .filter((request) => request.method === 'PUT' && request.path === '/api/settings')
      .map((request) => request.body as JsonPatchOp[])
  }
}

export function refusal(status: number, code: string, title: string, detail?: string): Response {
  return problem(status, code, title, detail)
}

/** Mounts a settings component with loaded settings and the given system info. */
export async function mountSettings<C extends Component>(
  component: C,
  options: { info?: SystemInfo; path?: string; pinia?: Pinia; setup?: () => void } = {},
) {
  const server = new SettingsServer()
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  const result = await mountShell(component, {
    path: options.path,
    pinia: options.pinia,
    setup: () => {
      useSystemStore().info = options.info ?? systemInfo()
      useSettingsStore().settings = defaultSettings()
      useSettingsStore().loaded = true
      options.setup?.()
    },
  })
  return { ...result, server }
}

/**
 * What a screen reader names the list whose root has `data-field="field"`: `aria-labelledby`
 * wins over `aria-label`, which PrimeVue's `Select` fills with the chosen value.
 */
export function comboboxName(field: string): string | undefined {
  const combobox = document.querySelector(`[data-field="${field}"] [role="combobox"]`)
  const ids = combobox?.getAttribute('aria-labelledby')
  if (!ids) return combobox?.getAttribute('aria-label') ?? undefined
  return ids
    .split(/\s+/)
    .map((id) => document.getElementById(id)?.textContent?.trim() ?? '')
    .join(' ')
}
