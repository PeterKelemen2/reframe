import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, unwrap } from '@/api/client'
import { createMirror } from '@/api/mirror'
import { text } from '@/api/text'
import type { EventOf, TaskInfo } from '@/api/types'

type TaskEvent = EventOf<'task.progress'> | EventOf<'task.done'>

const ENDED = new Set<TaskInfo['state']>(['done', 'failed', 'cancelled'])
/** Ended tasks the copy keeps (the server keeps as many); the oldest go first. */
export const KEEP_ENDED = 200

/** The server no longer knows a task that `wait` waits for (it restarted, or forgot it). */
export class TaskLostError extends Error {
  constructor(readonly taskId: string) {
    super(text('api.taskLost', { id: taskId }))
    this.name = 'TaskLostError'
  }
}

interface Waiter {
  /** The mirror's tick when the waiter came: a read sent after it must list the task. */
  since: number
  resolve(task: TaskInfo): void
  reject(error: Error): void
}

export function taskEnded(task: TaskInfo): boolean {
  return ENDED.has(task.state)
}

async function cancel(taskId: string): Promise<void> {
  unwrap(await api.POST('/api/tasks/{task_id}/cancel', { params: { path: { task_id: taskId } } }))
}

/** Background tasks of the server (probe, rescan, frames, scans), by id. */
export const useTasksStore = defineStore('tasks', () => {
  const tasks = ref<Record<string, TaskInfo>>({})
  const waiters = new Map<string, Waiter[]>()

  function settle(task: TaskInfo): void {
    if (!taskEnded(task)) return
    const waiting = waiters.get(task.id)
    waiters.delete(task.id)
    for (const waiter of waiting ?? []) waiter.resolve(task)
  }

  function prune(): void {
    const ended = Object.values(tasks.value).filter(
      (task) => taskEnded(task) && !waiters.has(task.id),
    )
    for (const task of ended.slice(0, Math.max(ended.length - KEEP_ENDED, 0))) {
      delete tasks.value[task.id]
    }
  }

  function put(task: TaskInfo): void {
    const known = tasks.value[task.id]
    // A task never leaves its end: progress after it is older than the copy.
    if (known !== undefined && taskEnded(known) && !taskEnded(task)) return
    tasks.value[task.id] = task
    settle(task)
    if (taskEnded(task)) prune()
  }

  const mirror = createMirror<TaskInfo[], TaskEvent>({
    fetch: async () => unwrap(await api.GET('/api/tasks')),
    apply(list, sentAt) {
      tasks.value = Object.fromEntries(list.map((task) => [task.id, task]))
      for (const task of list) settle(task)
      for (const [taskId, waiting] of waiters) {
        if (taskId in tasks.value) continue
        const lost = waiting.filter((waiter) => waiter.since < sentAt)
        if (lost.length === 0) continue
        waiters.set(
          taskId,
          waiting.filter((waiter) => waiter.since >= sentAt),
        )
        if (waiters.get(taskId)?.length === 0) waiters.delete(taskId)
        for (const waiter of lost) waiter.reject(new TaskLostError(taskId))
      }
      prune()
    },
    handle(event) {
      put(event.task)
    },
  })

  /**
   * The task once it has ended (`done`, `failed` or `cancelled`; a failed task resolves, it
   * does not reject). Holds across a lost event connection: the task is read again then.
   * Rejects with `TaskLostError` when a later read no longer lists the task.
   */
  async function wait(taskId: string): Promise<TaskInfo> {
    const known = tasks.value[taskId]
    if (known !== undefined && taskEnded(known)) return known
    return new Promise<TaskInfo>((resolve, reject) => {
      const waiter: Waiter = { since: mirror.tick(), resolve, reject }
      waiters.set(taskId, [...(waiters.get(taskId) ?? []), waiter])
    })
  }

  /** Reads `GET /api/tasks` again. */
  async function resync(): Promise<void> {
    return mirror.read()
  }

  function onTaskProgress(event: EventOf<'task.progress'>): void {
    mirror.event(event)
  }

  function onTaskDone(event: EventOf<'task.done'>): void {
    mirror.event(event)
  }

  return { tasks, wait, cancel, resync, onTaskProgress, onTaskDone }
})
