<script setup lang="ts">
import { Download, FolderCog, LoaderCircle, RefreshCw, Wrench } from '@lucide/vue'
import Button from 'primevue/button'
import ProgressBar from 'primevue/progressbar'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import type { JsonPatchOp, Schemas } from '@/api/types'
import KeyValue from '@/components/base/KeyValue.vue'
import StatusDot from '@/components/base/StatusDot.vue'
import type { StatusTone } from '@/components/base/types'
import { FFMPEG_FAMILY, setByEnvironment } from '@/components/settings/tools'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'
import { useTasksStore } from '@/stores/tasks'

import FocusSafeButton from './FocusSafeButton'

type ToolInfo = Schemas['ToolInfo']

const { t, locale } = useI18n()
const router = useRouter()
const system = useSystemStore()
const settings = useSettingsStore()
const tasks = useTasksStore()

const checking = ref(false)
/** When the last *Check again* found the tools as they were: it says so, else nothing changes. */
const unchangedAt = ref<string | null>(null)

const tools = computed<ToolInfo[]>(() => {
  const set = system.info?.tools
  return set ? [set.ffmpeg, set.ffprobe] : []
})
const fetchTask = computed(() =>
  system.toolsFetch === null ? null : (tasks.tasks[system.toolsFetch] ?? null),
)
const fetching = computed(() => system.toolsFetch !== null)

const failing = computed(() => tools.value.filter((tool) => tool.status !== 'found'))
/** The environment sets a tool that fails: it outranks Settings and a bundled build. */
const setByEnv = computed(() => failing.value.filter(setByEnvironment))
/** The server refuses tool paths from a browser; only the desktop app can choose one. */
const desktop = computed(() => system.info?.mode === 'desktop')
const canBundle = computed(() => setByEnv.value.length === 0)
const canChoosePath = computed(() => desktop.value && setByEnv.value.length === 0)
const variables = computed(() =>
  (setByEnv.value.length > 0 ? setByEnv.value : failing.value)
    .map((tool) => tool.env_var)
    .filter((name): name is string => Boolean(name))
    .join(', '),
)
const note = computed(() => {
  if (!canBundle.value) return t('shell.firstRun.envNote', { variables: variables.value })
  if (!desktop.value) return t('shell.firstRun.webNote', { variables: variables.value })
  return null
})

function statusTone(tool: ToolInfo): StatusTone {
  return tool.status === 'found' ? 'ok' : 'error'
}

function statusLabel(tool: ToolInfo): string {
  switch (tool.status) {
    case 'found':
      return t('shell.firstRun.status.found')
    case 'missing':
      return t('shell.firstRun.status.missing')
    case 'too_old':
      return t('shell.firstRun.status.too_old')
    case 'broken':
      return t('shell.firstRun.status.broken')
  }
}

function originLabel(tool: ToolInfo): string {
  switch (tool.origin) {
    case 'env':
      return t('shell.firstRun.origin.env')
    case 'settings':
      return t('shell.firstRun.origin.settings')
    case 'bundled':
      return t('shell.firstRun.origin.bundled')
    case 'path':
      return t('shell.firstRun.origin.path')
    default:
      return t('shell.firstRun.origin.none')
  }
}

/** The API client has shown the problem as a toast; the screen stays as it is. */
async function quietly(action: () => Promise<void>): Promise<void> {
  try {
    await action()
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
  }
}

/**
 * Downloads the pinned FFmpeg, then removes the Settings paths of ffmpeg and ffprobe, which would
 * still win over the bundled build.
 */
async function useBundled(): Promise<void> {
  unchangedAt.value = null
  let taskId: string | null = null
  const stop = watch(
    () => system.toolsFetch,
    (id) => {
      if (id !== null) taskId = id
    },
    { flush: 'sync' },
  )
  try {
    await quietly(() => system.fetchTools())
  } finally {
    stop()
  }
  if (taskId === null || tasks.tasks[taskId]?.state !== 'done') return
  const paths = settings.settings?.tools
  const ops: JsonPatchOp[] = FFMPEG_FAMILY.filter((name) => paths?.[name]).map((name) => ({
    op: 'replace',
    path: `/tools/${name}`,
    value: null,
  }))
  if (ops.length === 0) return
  await quietly(async () => {
    await settings.update(ops)
    await system.rescanTools()
  })
}

function snapshot(): string {
  return JSON.stringify(tools.value)
}

async function checkAgain(): Promise<void> {
  checking.value = true
  unchangedAt.value = null
  const before = snapshot()
  try {
    await quietly(() => system.rescanTools())
    if (snapshot() === before) {
      unchangedAt.value = new Intl.DateTimeFormat(locale.value, { timeStyle: 'medium' }).format(
        new Date(),
      )
    }
  } finally {
    checking.value = false
  }
}

async function choosePath(): Promise<void> {
  await router.push({ name: 'settings', hash: '#tools' })
}
</script>

<template>
  <section class="first-run" aria-labelledby="first-run-title" data-screen="first-run">
    <header class="first-run__header">
      <Wrench class="first-run__icon" :size="32" aria-hidden="true" />
      <h1 id="first-run-title" class="first-run__title">{{ t('shell.firstRun.title') }}</h1>
    </header>
    <p class="first-run__reason" role="alert">{{ system.ffmpegProblem }}</p>
    <p class="first-run__intro">{{ t('shell.firstRun.intro') }}</p>

    <h2 class="first-run__subtitle">{{ t('shell.firstRun.tools') }}</h2>
    <dl class="rf-kv-list first-run__tools">
      <KeyValue v-for="tool in tools" :key="tool.name" :label="tool.name">
        <span class="first-run__tool" :data-tool="tool.name">
          <StatusDot :tone="statusTone(tool)" :label="statusLabel(tool)" show-label />
          <span class="first-run__origin" data-field="origin">{{ originLabel(tool) }}</span>
          <code v-if="tool.path" class="first-run__path" data-field="path">{{ tool.path }}</code>
          <span v-else class="first-run__path first-run__path--none">
            {{ t('shell.firstRun.notFound') }}
          </span>
          <span
            v-if="tool.reason && tool.reason !== system.ffmpegProblem"
            class="first-run__tool-reason"
            >{{ tool.reason }}</span
          >
          <span v-if="tool.version" class="first-run__version">
            {{ t('shell.firstRun.version', { version: tool.version }) }}
          </span>
        </span>
      </KeyValue>
    </dl>

    <p v-if="note" class="first-run__note" data-field="note">{{ note }}</p>
    <div class="first-run__actions">
      <FocusSafeButton
        v-if="canBundle"
        class="first-run__bundled"
        :label="t('shell.firstRun.useBundled')"
        :disabled="fetching"
        @click="useBundled"
      >
        <template #icon>
          <LoaderCircle v-if="fetching" class="first-run__spin" :size="18" aria-hidden="true" />
          <Download v-else :size="18" aria-hidden="true" />
        </template>
      </FocusSafeButton>
      <Button
        v-if="canChoosePath"
        class="first-run__choose"
        :label="t('shell.firstRun.choosePath')"
        severity="secondary"
        outlined
        @click="choosePath"
      >
        <template #icon>
          <FolderCog :size="18" aria-hidden="true" />
        </template>
      </Button>
      <FocusSafeButton
        class="first-run__check"
        :label="t('shell.firstRun.checkAgain')"
        severity="secondary"
        outlined
        :disabled="checking || fetching"
        @click="checkAgain"
      >
        <template #icon>
          <LoaderCircle v-if="checking" class="first-run__spin" :size="18" aria-hidden="true" />
          <RefreshCw v-else :size="18" aria-hidden="true" />
        </template>
      </FocusSafeButton>
      <span class="first-run__checked" role="status" data-field="checked">
        {{ unchangedAt ? t('shell.firstRun.unchanged', { time: unchangedAt }) : '' }}
      </span>
    </div>

    <div v-if="fetching" class="first-run__progress" role="status">
      <span>{{ fetchTask?.message || t('shell.firstRun.downloading') }}</span>
      <ProgressBar
        :value="fetchTask?.progress ?? undefined"
        :mode="typeof fetchTask?.progress === 'number' ? 'determinate' : 'indeterminate'"
        :pt="{ root: { 'aria-label': t('shell.firstRun.downloading') } }"
      />
    </div>
  </section>
</template>

<style scoped>
.first-run {
  display: grid;
  align-content: start;
  gap: var(--rf-space-4);
  max-width: 48rem;
  margin: 0 auto;
  padding: var(--rf-space-6) var(--rf-space-4);
}

.first-run__header {
  display: flex;
  align-items: center;
  gap: var(--rf-space-3);
}

.first-run__icon {
  color: var(--p-status-error-color);
}

.first-run__title {
  margin: 0;
  font-size: var(--rf-font-size-2xl);
}

.first-run__subtitle {
  margin: 0;
  font-size: var(--rf-font-size-lg);
}

.first-run__reason {
  margin: 0;
  padding: var(--rf-space-3) var(--rf-space-4);
  border: 1px solid var(--p-status-error-border-color);
  border-radius: var(--rf-radius-md);
  background: var(--p-status-error-background);
  color: var(--rf-color-text);
  overflow-wrap: anywhere;
}

.first-run__intro,
.first-run__note,
.first-run__checked {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.first-run__checked {
  align-self: center;
}

.first-run__tool {
  display: grid;
  gap: var(--rf-space-1);
}

.first-run__origin,
.first-run__version,
.first-run__tool-reason {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.first-run__path {
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-sm);
  overflow-wrap: anywhere;
}

.first-run__path--none {
  font-family: inherit;
  color: var(--rf-color-text-muted);
}

.first-run__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
}

.first-run__spin {
  animation: first-run-spin 1s linear infinite;
}

@keyframes first-run-spin {
  to {
    transform: rotate(360deg);
  }
}

.first-run__progress {
  display: grid;
  gap: var(--rf-space-2);
}
</style>
