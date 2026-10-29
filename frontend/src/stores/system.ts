// oxlint-disable unicorn/consistent-function-scoping -- stub actions; they use the store once built
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type {
  AuthStatus,
  CapabilitySnapshot,
  Definitions,
  EncoderStatus,
  EventOf,
  Language,
  SystemInfo,
} from '@/api/types'
import { notBuilt } from '@/notBuilt'

/** `login`: the server wants credentials. `offline`: the server cannot be reached. */
export type AppPhase = 'booting' | 'login' | 'ready' | 'offline'
export type ConnectionState = 'connecting' | 'open' | 'reconnecting' | 'unauthorized' | 'closed'
export type AppWarning = EventOf<'app.warning'>

/** The server's state: auth, tools, encoders, definitions, languages, the event connection. */
export const useSystemStore = defineStore('system', () => {
  const phase = ref<AppPhase>('booting')
  const auth = ref<AuthStatus | null>(null)
  const connection = ref<ConnectionState>('closed')
  /** The server run's `instance` from the last `hello`. */
  const instance = ref<string | null>(null)
  const info = ref<SystemInfo | null>(null)
  const capabilities = ref<CapabilitySnapshot | null>(null)
  const definitions = ref<Definitions | null>(null)
  const languages = ref<Language[]>([])
  /** `GET /api/system` problems and `app.warning` events, oldest first. */
  const warnings = ref<AppWarning[]>([])

  /** Why FFmpeg or FFprobe cannot be used (the first-run screen); `null` when both can. */
  const ffmpegProblem = computed<string | null>(() => null)

  function encoderStatus(id: string): EncoderStatus | undefined {
    return capabilities.value?.encoders?.[id]
  }

  /** Password mode. `false` for a wrong password (the problem is not toasted). */
  async function login(password: string): Promise<boolean> {
    return notBuilt('system.login', password)
  }

  /** Token mode: keeps the token for this tab when the server accepts it. */
  async function loginWithToken(token: string): Promise<boolean> {
    return notBuilt('system.loginWithToken', token)
  }

  async function logout(): Promise<void> {
    return notBuilt('system.logout')
  }

  /** Reads `GET /api/system` and `GET /api/system/encoders` again. */
  async function resync(): Promise<void> {
    return notBuilt('system.resync')
  }

  /** Encoder detection again (a task); statuses come as `capabilities.changed`. */
  async function rescanEncoders(): Promise<void> {
    return notBuilt('system.rescanEncoders')
  }

  /** Tool discovery again (*Check again*); the result comes as `tools.changed`. */
  async function rescanTools(): Promise<void> {
    return notBuilt('system.rescanTools')
  }

  /** Downloads the pinned FFmpeg build (*Use bundled FFmpeg*; a task). */
  async function fetchTools(): Promise<void> {
    return notBuilt('system.fetchTools')
  }

  function onCapabilitiesChanged(event: EventOf<'capabilities.changed'>): void {
    notBuilt('system.onCapabilitiesChanged', event)
  }

  function onToolsChanged(event: EventOf<'tools.changed'>): void {
    notBuilt('system.onToolsChanged', event)
  }

  function onAppWarning(event: AppWarning): void {
    notBuilt('system.onAppWarning', event)
  }

  return {
    phase,
    auth,
    connection,
    instance,
    info,
    capabilities,
    definitions,
    languages,
    warnings,
    ffmpegProblem,
    encoderStatus,
    login,
    loginWithToken,
    logout,
    resync,
    rescanEncoders,
    rescanTools,
    fetchTools,
    onCapabilitiesChanged,
    onToolsChanged,
    onAppWarning,
  }
})
