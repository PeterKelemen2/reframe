import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { TaskInfo, ValidationIssue } from '@/api/types'
import { useSettingsStore } from '@/stores/settings'
import { FETCH_OFFLINE, useSystemStore } from '@/stores/system'
import { taskEnded, useTasksStore } from '@/stores/tasks'

import { bundledFfmpegDamaged, resetOps, TOOL_NAMES, type ToolName } from './tools'
import { refusalIssues } from './useSetting'

/** The API client has shown the problem as a toast. */
async function quietly<T>(action: () => Promise<T>): Promise<T | null> {
  try {
    return await action()
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
    return null
  }
}

/** What a download or a file install came to. */
export interface InstallOutcome {
  /** The build is installed and the tools were found again. */
  done: boolean
  /** The download server cannot be reached (`tools.fetch_offline`). */
  offline: boolean
  /** What the server refused when the Settings paths were removed. */
  issues: ValidationIssue[]
  /** Installed, but another ffmpeg is used: its path. */
  shadowedBy: string | null
}

/**
 * Downloads and file installs of FFmpeg builds, and *Use bundled*. Once a build is installed,
 * the Settings paths of both tools are removed: each would win over it.
 */
export function useBundledTools() {
  const { t } = useI18n()
  const system = useSystemStore()
  const settings = useSettingsStore()
  const tasks = useTasksStore()

  /** This front end's task, or one that another front end or the server's start-up runs. */
  const fetchTask = computed<TaskInfo | null>(() => {
    if (system.toolsFetch !== null) return tasks.tasks[system.toolsFetch] ?? null
    return (
      Object.values(tasks.tasks).find((task) => task.kind === 'tools_fetch' && !taskEnded(task)) ??
      null
    )
  })
  const fetching = computed(() => system.toolsFetch !== null || fetchTask.value !== null)
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

  async function removePaths(): Promise<ValidationIssue[]> {
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

  /** What the server refused, at `tools`; empty when nothing was refused. */
  async function use(name: ToolName): Promise<ValidationIssue[]> {
    const fetchFirst = !system.info?.tools[name].bundled || canDownload.value
    if (fetchFirst) {
      const task = await quietly(() => system.fetchTools())
      if (task?.state !== 'done') return []
    }
    return removePaths()
  }

  /** Downloads the offered build `build`, or installs the archive file at `path`. */
  async function install(source: { build: string } | { path: string }): Promise<InstallOutcome> {
    const task = await quietly(() =>
      'path' in source ? system.installToolsFile(source.path) : system.fetchTools(source.build),
    )
    if (task?.state !== 'done') {
      return {
        done: false,
        offline: task?.error_code === FETCH_OFFLINE,
        issues: [],
        shadowedBy: null,
      }
    }
    const issues = await removePaths()
    // The task's result is a `ToolFetchResult`, which the OpenAPI document does not describe.
    const installed = (task.result as { ffmpeg?: string } | null | undefined)?.ffmpeg
    const used = system.info?.tools.ffmpeg.path ?? null
    const shadowedBy =
      issues.length === 0 && installed && used !== null && used !== installed ? used : null
    return { done: true, offline: false, issues, shadowedBy }
  }

  return { canDownload, fetching, fetchTask, use, install }
}
