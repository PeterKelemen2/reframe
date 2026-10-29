// oxlint-disable unicorn/consistent-function-scoping -- stub actions; they use the store once built
import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { EventOf, TaskInfo } from '@/api/types'
import { notBuilt } from '@/notBuilt'

/** Background tasks of the server (probe, rescan, frames, scans), by id. */
export const useTasksStore = defineStore('tasks', () => {
  const tasks = ref<Record<string, TaskInfo>>({})

  /**
   * The task once it has ended (`done`, `failed` or `cancelled`; a failed task resolves, it
   * does not reject). Holds across a lost event connection: the task is read again then.
   */
  async function wait(taskId: string): Promise<TaskInfo> {
    return notBuilt('tasks.wait', taskId)
  }

  async function cancel(taskId: string): Promise<void> {
    return notBuilt('tasks.cancel', taskId)
  }

  /** Reads `GET /api/tasks` again. */
  async function resync(): Promise<void> {
    return notBuilt('tasks.resync')
  }

  function onTaskProgress(event: EventOf<'task.progress'>): void {
    notBuilt('tasks.onTaskProgress', event)
  }

  function onTaskDone(event: EventOf<'task.done'>): void {
    notBuilt('tasks.onTaskDone', event)
  }

  return { tasks, wait, cancel, resync, onTaskProgress, onTaskDone }
})
