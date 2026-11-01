import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { clientToken, configureClient } from '@/api/client'
import { deferred, FakeServer, problem, settle } from '@/api/testing/fakes'
import type { CapabilitySnapshot, EncoderStatus, SystemInfo, TaskInfo } from '@/api/types'

import { useSystemStore } from './system'
import { useTasksStore } from './tasks'
import { useToastStore } from './toasts'

type Tools = SystemInfo['tools']
type Tool = Tools['ffmpeg']

function tool(name: Tool['name'], extra: Partial<Tool> = {}): Tool {
  return { name, status: 'found', next_to_ffmpeg: false, path: `/usr/bin/${name}`, ...extra }
}

function tools(extra: Partial<Tools> = {}): Tools {
  return {
    ffmpeg: tool('ffmpeg'),
    ffprobe: tool('ffprobe'),
    mkvpropedit: tool('mkvpropedit'),
    mediainfo: tool('mediainfo', { status: 'missing' }),
    ...extra,
  }
}

function info(extra: Partial<SystemInfo> = {}): SystemInfo {
  return {
    mode: 'web',
    auth: 'token',
    platform: 'linux',
    tools: tools(),
    problems: [],
    settings_read_only: false,
    ...extra,
  }
}

function encoder(id: string, state: EncoderStatus['state'], checked_at = 't1'): EncoderStatus {
  return { id, state, hardware: false, checked_at }
}

function capabilities(detecting: boolean, ...encoders: EncoderStatus[]): CapabilitySnapshot {
  return {
    encoders: Object.fromEntries(encoders.map((status) => [status.id, status])),
    detecting,
    from_cache: false,
  }
}

describe('the system store', () => {
  let server: FakeServer
  let system: SystemInfo
  let encoders: CapabilitySnapshot

  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    system = info()
    encoders = capabilities(false, encoder('libx264', 'available'))
    server = new FakeServer()
      .on('GET /api/system', () => structuredClone(system))
      .on('GET /api/system/encoders', () => structuredClone(encoders))
    configureClient({ baseUrl: 'http://server', token: null, fetch: server.fetch })
  })

  it('names no FFmpeg problem while ffmpeg and ffprobe are found', async () => {
    const store = useSystemStore()
    expect(store.ffmpegProblem).toBeNull()
    await store.resync()
    expect(store.ffmpegProblem).toBeNull()
  })

  it('names why ffmpeg or ffprobe cannot be used', async () => {
    system = info({
      tools: tools({
        ffprobe: tool('ffprobe', { status: 'too_old', reason: 'ffprobe 4.4 is too old.' }),
      }),
    })
    const store = useSystemStore()
    await store.resync()
    expect(store.ffmpegProblem).toBe('ffprobe 4.4 is too old.')

    store.onToolsChanged({
      type: 'tools.changed',
      tools: tools({ ffmpeg: tool('ffmpeg', { status: 'missing', reason: null, path: null }) }),
    })
    expect(store.ffmpegProblem).toBe('ffmpeg was not found.')
  })

  it('merges changed encoder statuses into the snapshot', async () => {
    encoders = capabilities(
      false,
      encoder('libx264', 'available'),
      encoder('h264_nvenc', 'checking'),
    )
    const store = useSystemStore()
    await store.resync()
    const reads = server.count('GET /api/system/encoders')
    store.onCapabilitiesChanged({
      type: 'capabilities.changed',
      encoders: [encoder('h264_nvenc', 'unavailable', 't2')],
    })
    expect(store.encoderStatus('h264_nvenc')?.state).toBe('unavailable')
    expect(store.encoderStatus('libx264')?.state).toBe('available')
    await settle()
    expect(server.count('GET /api/system/encoders')).toBe(reads)
  })

  it('reads the encoders again after a change while a detection runs', async () => {
    encoders = capabilities(true, encoder('libx264', 'checking'))
    const store = useSystemStore()
    await store.resync()
    encoders = capabilities(false, encoder('libx264', 'available', 't2'))
    store.onCapabilitiesChanged({
      type: 'capabilities.changed',
      encoders: [encoder('libx264', 'available', 't2')],
    })
    await settle()
    expect(store.capabilities?.detecting).toBe(false)
  })

  it('lists the start-up problems first, then the warnings that came as events', async () => {
    const startup = {
      type: 'app.warning',
      code: 'settings.corrupt',
      message: 'Settings were reset',
    } as const
    system = info({ problems: [startup] })
    const store = useSystemStore()
    const later = {
      type: 'app.warning',
      code: 'power.inhibit',
      message: 'No sleep inhibit',
    } as const
    store.onAppWarning(later)
    await store.resync()
    expect(store.warnings.map((w) => w.code)).toEqual(['settings.corrupt', 'power.inhibit'])
  })

  describe('login', () => {
    it('answers false for a wrong password and shows no toast', async () => {
      server.on('POST /api/auth/login', () => problem(401, 'auth.invalid', 'Wrong password'))
      const store = useSystemStore()
      expect(await store.login('nope')).toBe(false)
      expect(store.auth).toBeNull()
      expect(useToastStore().items).toEqual([])
    })

    it('keeps the status of a right password and drops a token from the address', async () => {
      server.on('POST /api/auth/login', { mode: 'password', authenticated: true })
      configureClient({ token: 'stale' })
      const store = useSystemStore()
      expect(await store.login('right')).toBe(true)
      expect(store.auth).toEqual({ mode: 'password', authenticated: true })
      expect(clientToken()).toBeNull()
      expect(server.requests[0]?.body).toEqual({ password: 'right' })
    })

    it('rejects with the problem when the server refuses for another reason', async () => {
      server.on('POST /api/auth/login', () => problem(429, 'auth.rate_limited', 'Too many tries'))
      await expect(useSystemStore().login('x')).rejects.toMatchObject({ status: 429 })
      expect(useToastStore().items).toEqual([])
    })

    it('keeps a token the server takes for this tab, and sends it from then on', async () => {
      server.on('GET /api/auth/status', ({ headers }) => ({
        mode: 'token',
        authenticated: headers.get('Authorization') === 'Bearer good',
      }))
      const store = useSystemStore()
      expect(await store.loginWithToken('bad')).toBe(false)
      expect(clientToken()).toBeNull()
      expect(sessionStorage.getItem('reframe.token')).toBeNull()

      expect(await store.loginWithToken('good')).toBe(true)
      expect(store.auth).toEqual({ mode: 'token', authenticated: true })
      expect(sessionStorage.getItem('reframe.token')).toBe('good')
      await store.resync()
      expect(server.requests.at(-1)?.headers.get('Authorization')).toBe('Bearer good')
    })

    it('logs out: the cookie session ends and the token is forgotten', async () => {
      server.on('POST /api/auth/logout', { mode: 'token', authenticated: true })
      configureClient({ token: 'tab' })
      sessionStorage.setItem('reframe.token', 'tab')
      const store = useSystemStore()
      await store.logout()
      expect(store.auth).toEqual({ mode: 'token', authenticated: false })
      expect(clientToken()).toBeNull()
      expect(sessionStorage.getItem('reframe.token')).toBeNull()
    })

    it('stays logged in after a logout in a mode without login', async () => {
      server.on('POST /api/auth/logout', { mode: 'none', authenticated: true })
      const store = useSystemStore()
      await store.logout()
      expect(store.auth).toEqual({ mode: 'none', authenticated: true })
    })
  })

  it('takes the tools of a rescan, and a tools.changed that came during it on top', async () => {
    const store = useSystemStore()
    await store.resync()
    const answer = deferred<Tools>()
    server.on('POST /api/system/tools/rescan', () => answer.promise)
    const rescan = store.rescanTools()
    await settle()
    const newer = tools({ ffmpeg: tool('ffmpeg', { version: 'n9.1' }) })
    store.onToolsChanged({ type: 'tools.changed', tools: newer })
    answer.resolve(tools({ ffmpeg: tool('ffmpeg', { version: 'n9.0' }) }))
    await rescan
    expect(store.info?.tools.ffmpeg.version).toBe('n9.1')
  })

  it('waits for an encoder rescan task, then reads the encoders; a failed task is a toast', async () => {
    const store = useSystemStore()
    const tasks = useTasksStore()
    server.on(
      'POST /api/system/encoders/rescan',
      () => new Response(JSON.stringify({ task_id: 'r1' }), { status: 202 }),
    )
    const rescan = store.rescanEncoders()
    await settle()
    expect(store.capabilities).toBeNull()
    const failed: TaskInfo = {
      id: 'r1',
      kind: 'encoders_rescan',
      state: 'failed',
      error: 'ffmpeg crashed',
    }
    tasks.onTaskDone({ type: 'task.done', task: failed })
    await rescan
    expect(store.encoderStatus('libx264')?.state).toBe('available')
    expect(useToastStore().items).toEqual([
      expect.objectContaining({ severity: 'error', detail: 'ffmpeg crashed' }),
    ])
  })

  it('names the running FFmpeg download while it runs', async () => {
    const store = useSystemStore()
    const tasks = useTasksStore()
    server.on(
      'POST /api/system/tools/fetch',
      () => new Response(JSON.stringify({ task_id: 'f1' }), { status: 202 }),
    )
    const fetching = store.fetchTools()
    await settle()
    expect(store.toolsFetch).toBe('f1')
    tasks.onTaskDone({ type: 'task.done', task: { id: 'f1', kind: 'tools_fetch', state: 'done' } })
    await fetching
    expect(store.toolsFetch).toBeNull()
    expect(store.info?.tools.ffmpeg.status).toBe('found')
  })

  it('reads the definitions, the naming variables and the languages', async () => {
    server.on('GET /api/definitions', {
      definitions: { containers: {} },
      naming_variables: [{ name: 'title' }],
    })
    server.on('GET /api/languages', { languages: [{ code: 'hun', name: 'Hungarian' }] })
    const store = useSystemStore()
    await store.loadDefinitions()
    expect(store.definitions).toEqual({ containers: {} })
    expect(store.namingVariables).toEqual([{ name: 'title' }])
    expect(store.languages).toEqual([{ code: 'hun', name: 'Hungarian' }])
  })
})
