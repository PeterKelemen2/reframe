/** The one place that hands each server event to the stores that mirror it. */
import { platform } from '@/platform'
import { useActivityStore } from '@/stores/activity'
import { useQueueStore } from '@/stores/queue'
import { useSystemStore } from '@/stores/system'
import { useTasksStore } from '@/stores/tasks'
import { type ToastSeverity, useToastStore } from '@/stores/toasts'

import type { AnyEvent } from './events'
import type { EventOf } from './types'

const SEVERITY: Record<EventOf<'notification'>['level'], ToastSeverity> = {
  info: 'info',
  success: 'success',
  warning: 'warn',
  error: 'error',
}
const NOTIFICATION_LIFE = 8_000

/** Runs one handler; a handler that throws or rejects does not stop the others. */
export function guard(name: string, handler: () => unknown): void {
  const report = (error: unknown) => console.error(`${name} failed`, error)
  try {
    const result = handler()
    if (result instanceof Promise) result.catch(report)
  } catch (error) {
    report(error)
  }
}

/** Reads every snapshot that events keep current again. */
export function resyncAll(): void {
  guard('system.resync', () => useSystemStore().resync())
  guard('tasks.resync', () => useTasksStore().resync())
  guard('queue.resync', () => useQueueStore().resync())
}

function notify(event: EventOf<'notification'>): void {
  useToastStore().push({
    severity: SEVERITY[event.level],
    summary: event.title,
    detail: event.message || undefined,
    life: NOTIFICATION_LIFE,
  })
  // The toast is not seen in a window without the focus: WebKitGTK on Wayland does not make a
  // minimised window, or one behind others, `hidden`.
  if (typeof document !== 'undefined' && (document.hidden || !document.hasFocus())) {
    guard('platform.notify', () => platform.notify(event.title, event.message))
  }
}

export function dispatch(event: AnyEvent): void {
  guard('activity.record', () => useActivityStore().record(event))
  const system = useSystemStore()
  const tasks = useTasksStore()
  const queue = useQueueStore()
  switch (event.type) {
    case 'capabilities.changed':
      return guard(event.type, () => system.onCapabilitiesChanged(event))
    case 'tools.changed':
      return guard(event.type, () => system.onToolsChanged(event))
    case 'app.warning':
      return guard(event.type, () => system.onAppWarning(event))
    case 'task.progress':
      return guard(event.type, () => tasks.onTaskProgress(event))
    case 'task.done':
      return guard(event.type, () => tasks.onTaskDone(event))
    case 'job.state':
      return guard(event.type, () => queue.onJobState(event))
    case 'job.progress':
      return guard(event.type, () => queue.onJobProgress(event))
    case 'job.log':
      return guard(event.type, () => queue.onJobLog(event))
    case 'queue.changed':
      return guard(event.type, () => queue.onQueueChanged(event))
    case 'queue.processing':
      return guard(event.type, () => queue.onQueueProcessing(event))
    case 'power.countdown':
      return guard(event.type, () => queue.onPowerCountdown(event))
    case 'notification':
      return guard(event.type, () => notify(event))
    case 'resync':
      return resyncAll()
  }
}
