import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConfirmationService from 'primevue/confirmationservice'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'
import Tooltip from 'primevue/tooltip'
import { vi } from 'vitest'
import { type Component, computed, reactive } from 'vue'
import { createMemoryHistory } from 'vue-router'

import { createAppI18n } from '@/i18n'
import { createAppRouter } from '@/router'

import type {
  EventOf,
  Fix,
  JobLogChunk,
  JobSettings,
  JobState,
  QueueJob,
  WhenDone,
} from '@/api/types'

/** A queue job as the server sends it; `extra` overrides. */
export function job(
  id: string,
  state: JobState = 'waiting',
  extra: Partial<QueueJob> = {},
): QueueJob {
  return {
    id,
    position: 0,
    state,
    settings: {
      schema_version: 1,
      source: { path: `/media/${id}.mkv` },
      preset_name: 'H.265 MKV 1080p',
      output: { path: `/out/${id}.mkv` },
    } as unknown as JobSettings,
    issues: [],
    created_at: '2026-10-29T10:00:00Z',
    ...extra,
  } as QueueJob
}

/** A test double of the queue store with the members the queue screens use. */
export function queueDouble() {
  const queue = reactive({
    jobs: [] as QueueJob[],
    processing: false,
    only: null as string[] | null,
    whenDone: 'nothing' as WhenDone,
    power: null as EventOf<'power.countdown'> | null,
    logTicks: {} as Record<string, number>,
    loaded: true,
    counts: computed(() => {
      const result: Record<JobState, number> = {
        waiting: 0,
        running: 0,
        paused: 0,
        done: 0,
        failed: 0,
        cancelled: 0,
        interrupted: 0,
      }
      for (const found of queue.jobs) result[found.state] += 1
      return result
    }),
    byId: (id: string) => queue.jobs.find((found) => found.id === id),
    start: vi.fn<(ids?: string[]) => Promise<void>>(async () => {}),
    stop: vi.fn<() => Promise<void>>(async () => {}),
    pauseAll: vi.fn<() => Promise<void>>(async () => {}),
    resumeAll: vi.fn<() => Promise<void>>(async () => {}),
    cancelAll: vi.fn<() => Promise<void>>(async () => {}),
    pause: vi.fn<(id: string) => Promise<void>>(async () => {}),
    resume: vi.fn<(id: string) => Promise<void>>(async () => {}),
    cancel: vi.fn<(id: string) => Promise<void>>(async () => {}),
    retry: vi.fn<(id: string) => Promise<void>>(async () => {}),
    retryWith: vi.fn<(id: string, fix: Fix) => Promise<void>>(async () => {}),
    duplicate: vi.fn<(id: string) => Promise<void>>(async () => {}),
    remove: vi.fn<(id: string) => Promise<void>>(async () => {}),
    reorder: vi.fn<(ids: string[]) => Promise<void>>(async () => {}),
    setWhenDone: vi.fn<(value: WhenDone) => Promise<void>>(async () => {}),
    cancelPower: vi.fn<() => Promise<void>>(async () => {}),
    readLog: vi.fn<(id: string, from?: number) => Promise<JobLogChunk>>(async (_id, from) => ({
      text: '',
      next: from ?? 0,
      more: false,
    })),
  })
  return queue
}

export type QueueDouble = ReturnType<typeof queueDouble>

/** Puts the double back to an empty, stopped queue with fresh mocks. */
export function resetQueue(queue: QueueDouble): void {
  queue.jobs = []
  queue.processing = false
  queue.only = null
  queue.whenDone = 'nothing'
  queue.power = null
  queue.logTicks = {}
  queue.loaded = true
}

// jsdom has neither; PrimeVue's overlays watch sizes with one, and Select reads the other.
globalThis.ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }) as unknown as MediaQueryList

/** Mounts a queue screen with the app's i18n, router (memory history), PrimeVue and its services. */
export async function mountQueue<C extends Component>(
  component: C,
  options: { path?: string; props?: Record<string, unknown> } = {},
) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createAppRouter(createMemoryHistory())
  await router.push(options.path ?? '/queue')
  await router.isReady()
  const wrapper = mount(component, {
    props: options.props,
    attachTo: document.body,
    global: {
      plugins: [
        pinia,
        router,
        createAppI18n(),
        [PrimeVue, { theme: 'none' }],
        ToastService,
        ConfirmationService,
      ],
      directives: { tooltip: Tooltip },
      stubs: { transition: false },
    },
  } as never)
  await flushPromises()
  return { wrapper, router }
}
