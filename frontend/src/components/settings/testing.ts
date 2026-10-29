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
    tools: { ffmpeg: null, ffprobe: null, mkvpropedit: null, mediainfo: null },
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
      default_container: 'mkv',
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
    ...extra,
  } as ToolInfo
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
    tools: {
      ffmpeg: tool('ffmpeg', tools.ffmpeg),
      ffprobe: tool('ffprobe', tools.ffprobe),
      mkvpropedit: tool('mkvpropedit', tools.mkvpropedit),
      mediainfo: tool('mediainfo', tools.mediainfo),
    },
    ...extra,
  } as SystemInfo
}

/**
 * A settings route that applies each patch like the server; `refuse` answers instead when it
 * returns a `Response` for the ops.
 */
export class SettingsServer extends FakeServer {
  document = defaultSettings()
  refuse: (ops: JsonPatchOp[]) => Response | undefined = () => undefined

  constructor() {
    super()
    this.on('GET /api/settings', () => structuredClone(this.document))
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
