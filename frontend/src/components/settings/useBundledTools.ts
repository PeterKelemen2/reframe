import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { ValidationIssue } from '@/api/types'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'
import { useTasksStore } from '@/stores/tasks'

import { bundledFfmpegDamaged, resetOps, TOOL_NAMES, type ToolName } from './tools'
import { refusalIssues } from './useSetting'

/** The API client has shown the problem as a toast. */
async function quietly(action: () => Promise<void>): Promise<boolean> {
  try {
    await action()
    return true
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
    return false
  }
}

/**
 * *Use bundled*: removes the Settings paths of both tools that win over the bundled
 * build, then finds the tools again. Without a bundled FFmpeg it first downloads the pinned
 * build, which then counts as bundled.
 */
export function useBundledTools() {
  const { t } = useI18n()
  const system = useSystemStore()
  const settings = useSettingsStore()
  const tasks = useTasksStore()

  const fetching = computed(() => system.toolsFetch !== null)
  const fetchTask = computed(() =>
    system.toolsFetch === null ? null : (tasks.tasks[system.toolsFetch] ?? null),
  )
  /**
   * Downloading the pinned FFmpeg changes what is found: there is no bundled build, or a web
   * server's damaged one is the download itself. The desktop app's own folder comes first.
   */
  const canDownload = computed(() => {
    const set = system.info?.tools
    if (set === undefined) return false
    if (!TOOL_NAMES.some((name) => set[name].bundled)) return true
    return system.info?.mode === 'web' && bundledFfmpegDamaged(set)
  })

  /** `true` when the download task ended `done`; a failure is a toast already. */
  async function download(): Promise<boolean> {
    let taskId: string | null = null
    const stop = watch(
      () => system.toolsFetch,
      (id) => {
        if (id !== null) taskId = id
      },
      { flush: 'sync' },
    )
    try {
      if (!(await quietly(() => system.fetchTools()))) return false
    } finally {
      stop()
    }
    return taskId !== null && tasks.tasks[taskId]?.state === 'done'
  }

  /** What the server refused, at `tools`; empty when nothing was refused. */
  async function use(name: ToolName): Promise<ValidationIssue[]> {
    const fetchFirst = !system.info?.tools[name].bundled || canDownload.value
    if (fetchFirst && !(await download())) return []
    const ops = resetOps(TOOL_NAMES, settings.settings?.tools)
    if (ops.length === 0) return []
    try {
      await settings.update(ops)
    } catch (error) {
      if (!(error instanceof ApiError)) throw error
      return refusalIssues(error, 'tools', t)
    }
    await quietly(() => system.rescanTools())
    return []
  }

  return { canDownload, fetching, fetchTask, use }
}
