import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import { api, apiQuiet, configureClient, unwrap } from '@/api/client'
import { storeToken } from '@/api/credentials'
import type { ConnectionState } from '@/api/events'
import { createMirror } from '@/api/mirror'
import { text } from '@/api/text'
import type {
  AuthStatus,
  CapabilitySnapshot,
  Definitions,
  EncoderStatus,
  EventOf,
  Language,
  Schemas,
  SystemInfo,
  TaskInfo,
} from '@/api/types'

import { useTasksStore } from './tasks'
import { useToastStore } from './toasts'

export type { ConnectionState } from '@/api/events'

/** `login`: the server wants credentials. `offline`: the server cannot be reached. */
export type AppPhase = 'booting' | 'login' | 'ready' | 'offline'
export type AppWarning = EventOf<'app.warning'>
export type NamingVariable = Schemas['NamingVariable']
export type ToolBuilds = Schemas['ToolBuilds']

/** The `error_code` of a download that cannot reach the download server. */
export const FETCH_OFFLINE = 'tools.fetch_offline'

export interface ToolsTaskOptions {
  /** The caller shows a `tools.fetch_offline` failure itself, so it is no toast. */
  showsOffline?: boolean
}

/** The server's state: auth, tools, encoders, definitions, languages, the event connection. */
export const useSystemStore = defineStore('system', () => {
  const tasksStore = useTasksStore()

  const phase = ref<AppPhase>('booting')
  const auth = ref<AuthStatus | null>(null)
  const connection = ref<ConnectionState>('closed')
  /** The server run's `instance` from the last `hello`. */
  const instance = ref<string | null>(null)
  const info = shallowRef<SystemInfo | null>(null)
  const capabilities = shallowRef<CapabilitySnapshot | null>(null)
  const definitions = shallowRef<Definitions | null>(null)
  /** The variables of output name templates (`GET /api/definitions`). */
  const namingVariables = shallowRef<NamingVariable[]>([])
  const languages = shallowRef<Language[]>([])
  /** `GET /api/system` problems and `app.warning` events, oldest first. */
  const warnings = ref<AppWarning[]>([])
  /** The task of a running FFmpeg download or file install (its progress is in the tasks store). */
  const toolsFetch = ref<string | null>(null)
  /** The offered FFmpeg builds and the installed one (`GET /api/system/tools/builds`). */
  const builds = shallowRef<ToolBuilds | null>(null)

  const eventWarnings: AppWarning[] = []

  function showWarnings(): void {
    warnings.value = [...(info.value?.problems ?? []), ...eventWarnings]
  }

  /** Why FFmpeg or FFprobe cannot be used (the first-run screen); `null` when both can. */
  const ffmpegProblem = computed<string | null>(() => {
    const tools = info.value?.tools
    if (tools === undefined) return null
    for (const tool of [tools.ffmpeg, tools.ffprobe]) {
      if (tool.status !== 'found') {
        return tool.reason ?? text(`api.tool.${tool.status}`, { tool: tool.name })
      }
    }
    return null
  })

  function encoderStatus(id: string): EncoderStatus | undefined {
    return capabilities.value?.encoders?.[id]
  }

  const infoMirror = createMirror<SystemInfo, EventOf<'tools.changed'>>({
    fetch: async () => unwrap(await api.GET('/api/system')),
    apply(snapshot) {
      info.value = snapshot
      showWarnings()
    },
    handle(event) {
      if (info.value !== null) info.value = { ...info.value, tools: event.tools }
    },
  })

  const encoderMirror = createMirror<CapabilitySnapshot, EventOf<'capabilities.changed'>>({
    fetch: async () => unwrap(await api.GET('/api/system/encoders')),
    apply(snapshot) {
      capabilities.value = snapshot
    },
    handle(event) {
      const current = capabilities.value
      if (current === null) return
      const encoders = { ...current.encoders }
      for (const status of event.encoders) encoders[status.id] = status
      capabilities.value = { ...current, encoders }
      // `detecting` and `checked_at` come only with a read: while a detection runs, read on.
      if (current.detecting) encoderMirror.need()
    },
  })

  /** Password mode. `false` for a wrong password (the problem is not toasted). */
  async function login(password: string): Promise<boolean> {
    const result = await apiQuiet.POST('/api/auth/login', { body: { password } })
    if (result.response.status === 401) return false
    const status = unwrap(result)
    // The session cookie is the credential now; a token left from the address is not needed.
    configureClient({ token: null })
    storeToken(null)
    auth.value = status
    return true
  }

  /** Token mode: keeps the token for this tab when the server accepts it. */
  async function loginWithToken(token: string): Promise<boolean> {
    const status = unwrap(
      await apiQuiet.GET('/api/auth/status', { headers: { Authorization: `Bearer ${token}` } }),
    )
    if (!status.authenticated) return false
    configureClient({ token })
    storeToken(token)
    auth.value = status
    return true
  }

  /** Ends the session cookie and forgets the tab's token. */
  async function logout(): Promise<void> {
    const status = unwrap(await apiQuiet.POST('/api/auth/logout'))
    configureClient({ token: null })
    storeToken(null)
    auth.value = { mode: status.mode, authenticated: status.mode === 'none' }
  }

  /** Reads `GET /api/system` and `GET /api/system/encoders` again. */
  async function resync(): Promise<void> {
    await Promise.all([infoMirror.read(), encoderMirror.read()])
  }

  /** Reads the definitions, the naming variables and the languages (they change only with the server). */
  async function loadDefinitions(): Promise<void> {
    const [document, list] = await Promise.all([
      api.GET('/api/definitions'),
      api.GET('/api/languages'),
    ])
    const loaded = unwrap(document)
    // openapi-fetch's answer type widens the tuples of the schema (`[min, max]` to `number[]`).
    definitions.value = loaded.definitions as Definitions
    namingVariables.value = loaded.naming_variables
    languages.value = unwrap(list).languages
  }

  /** A failed task is a toast, except an offline download whose caller `showsOffline` itself. */
  async function ended(
    taskId: string,
    { showsOffline = false }: ToolsTaskOptions = {},
  ): Promise<TaskInfo> {
    const task = await tasksStore.wait(taskId)
    if (task.state === 'failed' && !(showsOffline && task.error_code === FETCH_OFFLINE)) {
      useToastStore().push({
        severity: 'error',
        summary: text('api.taskFailed', { kind: task.kind }),
        detail: task.error ?? undefined,
      })
    }
    return task
  }

  /** Encoder detection again (a task); statuses come as `capabilities.changed`. */
  async function rescanEncoders(): Promise<void> {
    const { task_id } = unwrap(await api.POST('/api/system/encoders/rescan'))
    await ended(task_id)
    await encoderMirror.read()
  }

  /** Tool discovery again (*Check again*); the result comes as `tools.changed`. */
  async function rescanTools(): Promise<void> {
    await infoMirror.track(
      async () => unwrap(await api.POST('/api/system/tools/rescan')),
      (tools, since) => {
        if (info.value !== null) info.value = { ...info.value, tools }
        infoMirror.replay(since)
      },
    )
  }

  async function loadBuilds(): Promise<void> {
    builds.value = unwrap(await api.GET('/api/system/tools/builds'))
  }

  async function toolsTask(
    start: () => Promise<string>,
    options: ToolsTaskOptions,
  ): Promise<TaskInfo> {
    const taskId = await start()
    toolsFetch.value = taskId
    let task: TaskInfo
    try {
      task = await ended(taskId, options)
    } finally {
      if (toolsFetch.value === taskId) toolsFetch.value = null
    }
    await Promise.all([infoMirror.read(), loadBuilds()])
    return task
  }

  /** Downloads an offered FFmpeg build (the server's default without `build`); the ended task. */
  async function fetchTools(build?: string, options: ToolsTaskOptions = {}): Promise<TaskInfo> {
    return toolsTask(async () => {
      const body = build === undefined ? null : { build }
      return unwrap(await api.POST('/api/system/tools/fetch', { body })).task_id
    }, options)
  }

  /** Installs an FFmpeg archive file on the server's disk; the ended task. */
  async function installToolsFile(
    path: string,
    build?: string,
    options: ToolsTaskOptions = {},
  ): Promise<TaskInfo> {
    return toolsTask(async () => {
      const body = build === undefined ? { path } : { path, build }
      return unwrap(await api.POST('/api/system/tools/install-file', { body })).task_id
    }, options)
  }

  function onCapabilitiesChanged(event: EventOf<'capabilities.changed'>): void {
    encoderMirror.event(event)
  }

  function onToolsChanged(event: EventOf<'tools.changed'>): void {
    infoMirror.event(event)
  }

  function onAppWarning(event: AppWarning): void {
    eventWarnings.push(event)
    showWarnings()
  }

  return {
    phase,
    auth,
    connection,
    instance,
    info,
    capabilities,
    definitions,
    namingVariables,
    languages,
    warnings,
    toolsFetch,
    builds,
    ffmpegProblem,
    encoderStatus,
    login,
    loginWithToken,
    logout,
    resync,
    loadDefinitions,
    rescanEncoders,
    rescanTools,
    loadBuilds,
    fetchTools,
    installToolsFile,
    onCapabilitiesChanged,
    onToolsChanged,
    onAppWarning,
  }
})
