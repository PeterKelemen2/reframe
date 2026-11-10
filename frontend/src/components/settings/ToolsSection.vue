<script setup lang="ts">
import { Download, RefreshCw } from '@lucide/vue'
import Button from 'primevue/button'
import ProgressBar from 'primevue/progressbar'
import { computed, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { JsonPatchOp, ValidationIssue } from '@/api/types'
import Section from '@/components/base/Section.vue'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'
import { useTasksStore } from '@/stores/tasks'

import RefusalList from './RefusalList.vue'
import ToolRow from './ToolRow.vue'
import {
  FFMPEG_FAMILY,
  hasBundledFfmpeg,
  setByEnvironment,
  TOOL_NAMES,
  type ToolInfo,
} from './tools'
import { refusalIssues, useSettingsLocked } from './useSetting'

const { t } = useI18n()
const system = useSystemStore()
const settings = useSettingsStore()
const tasks = useTasksStore()
const locked = useSettingsLocked()

const tools = computed<ToolInfo[]>(() => {
  const set = system.info?.tools
  return set ? TOOL_NAMES.map((name) => set[name]) : []
})
const mode = computed(() => system.info?.mode ?? 'web')

const checking = ref(false)
const fetching = computed(() => system.toolsFetch !== null)
const fetchTask = computed(() =>
  system.toolsFetch === null ? null : (tasks.tasks[system.toolsFetch] ?? null),
)
/** The environment sets both: a bundled build would not be used. */
const bundledUseless = computed(() => {
  const set = system.info?.tools
  return set !== undefined && FFMPEG_FAMILY.every((name) => setByEnvironment(set[name]))
})
const bundledIssues = shallowRef<ValidationIssue[]>([])

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

async function checkAgain(): Promise<void> {
  checking.value = true
  try {
    await quietly(() => system.rescanTools())
  } finally {
    checking.value = false
  }
}

/** Downloads the pinned FFmpeg; false when it failed (a toast says why). */
async function download(): Promise<boolean> {
  let taskId: string | null = null
  const stop = watch(
    () => system.toolsFetch,
    (id) => {
      if (id !== null) taskId = id
    },
    { flush: 'sync' },
  )
  let fetched: boolean
  try {
    fetched = await quietly(() => system.fetchTools())
  } finally {
    stop()
  }
  return fetched && taskId !== null && tasks.tasks[taskId]?.state === 'done'
}

/**
 * Downloads the pinned FFmpeg unless a bundled one is there, then removes the Settings paths of
 * ffmpeg and ffprobe, which would otherwise still win over the bundled build.
 */
async function useBundled(): Promise<void> {
  bundledIssues.value = []
  if (!hasBundledFfmpeg(system.info?.tools) && !(await download())) return
  const current = settings.settings?.tools
  const ops: JsonPatchOp[] = FFMPEG_FAMILY.filter((name) => current?.[name]).map((name) => ({
    op: 'replace',
    path: `/tools/${name}`,
    value: null,
  }))
  if (ops.length === 0) return
  try {
    await settings.update(ops)
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
    bundledIssues.value = refusalIssues(error, 'tools', t)
    return
  }
  await quietly(() => system.rescanTools())
}
</script>

<template>
  <Section :title="t('settings.tools.title')">
    <template #actions>
      <Button
        :label="t('settings.tools.useBundled')"
        severity="secondary"
        outlined
        size="small"
        :loading="fetching"
        :disabled="bundledUseless || locked"
        data-action="use-bundled"
        @click="useBundled"
      >
        <template #icon>
          <Download :size="16" aria-hidden="true" />
        </template>
      </Button>
      <Button
        :label="t('settings.tools.checkAgain')"
        severity="secondary"
        outlined
        size="small"
        :loading="checking"
        :disabled="fetching"
        data-action="check-again"
        @click="checkAgain"
      >
        <template #icon>
          <RefreshCw :size="16" aria-hidden="true" />
        </template>
      </Button>
    </template>

    <p class="tools-section__intro">{{ t('settings.tools.intro') }}</p>
    <p v-if="bundledUseless" class="tools-section__note" data-field="bundled-note">
      {{ t('settings.tools.bundledUseless') }}
    </p>
    <RefusalList :issues="bundledIssues" />
    <div v-if="fetching" class="tools-section__progress" role="status">
      <span>{{ fetchTask?.message || t('settings.tools.downloading') }}</span>
      <ProgressBar
        :value="fetchTask?.progress ?? undefined"
        :mode="typeof fetchTask?.progress === 'number' ? 'determinate' : 'indeterminate'"
        :pt="{ root: { 'aria-label': t('settings.tools.downloading') } }"
      />
    </div>

    <div class="tools-section__rows">
      <ToolRow v-for="tool in tools" :key="tool.name" :tool="tool" :mode="mode" :locked="locked" />
    </div>
  </Section>
</template>

<style scoped>
.tools-section__intro,
.tools-section__note {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.tools-section__progress {
  display: grid;
  gap: var(--rf-space-1);
}

.tools-section__rows {
  display: grid;
}
</style>
