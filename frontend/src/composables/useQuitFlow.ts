import { computed, onScopeDispose, ref, watch } from 'vue'

import { desktopBackend } from '@/api/boot'
import type { QueueJob } from '@/api/types'
import { platform } from '@/platform'
import { useQueueStore } from '@/stores/queue'

export type QuitAnswer = 'stop' | 'tray' | 'cancel'

export interface QuitQuestion {
  /** Running and paused jobs of every front end, now. */
  active: number
  /** *Keep running in tray* is offered. */
  tray: boolean
}

function active(jobs: readonly QueueJob[]): QueueJob[] {
  return jobs.filter((job) => job.state === 'running' || job.state === 'paused')
}

/**
 * The desktop app's side of quitting: a close of the main window asks here first when jobs
 * run, and a when-done `quit` quits. Does nothing in a browser.
 */
export function useQuitFlow() {
  const asked = ref<{ tray: boolean } | null>(null)
  const shell = platform.desktop
  const queue = useQueueStore()
  // A job that ends while the question is open is no longer counted.
  const question = computed<QuitQuestion | null>(() =>
    asked.value === null ? null : { active: active(queue.jobs).length, tray: asked.value.tray },
  )
  if (shell === null) return { question, answer: (): Promise<void> => Promise.resolve() }

  const requested = async (): Promise<void> => {
    if (active(queue.jobs).length === 0) return shell.quit()
    const { tray } = await shell.settings()
    asked.value = { tray }
  }

  const answer = async (choice: QuitAnswer): Promise<void> => {
    asked.value = null
    if (choice === 'cancel') return
    if (choice === 'tray') return shell.hideMainWindow()
    const backend = desktopBackend.value
    if (backend?.state === 'ready' && !backend.info.owned) {
      // Another front end's server runs on after the app quits: its jobs are cancelled here.
      await queue.stop()
      await Promise.all(active(queue.jobs).map((job) => queue.cancel(job.id)))
    }
    await shell.quit()
  }

  const stopListening = shell.onQuitRequested(() => {
    requested().catch((error: unknown) => console.error('quit request failed', error))
  })
  // Until the queue is read, a close would count no jobs: before `quitReady` it quits at once.
  let ready = false
  const stopWatch = watch(
    () => queue.loaded,
    (loaded) => {
      if (!loaded || ready) return
      ready = true
      shell.quitReady().catch((error: unknown) => console.error('quit_ready failed', error))
    },
    { immediate: true },
  )
  const stopActions = queue.$onAction(({ name, args }) => {
    if (name !== 'onPowerCountdown') return
    const [event] = args as Parameters<typeof queue.onPowerCountdown>
    if (event.phase === 'executing' && event.action === 'quit') {
      shell.quit().catch((error: unknown) => console.error('when-done quit failed', error))
    }
  })
  onScopeDispose(() => {
    stopListening()
    stopWatch()
    stopActions()
  })

  return { question, answer }
}
