<script setup lang="ts">
import { ArrowRight, FolderCog, LoaderCircle, RefreshCw, Undo2, Wrench } from '@lucide/vue'
import Button from 'primevue/button'
import ProgressBar from 'primevue/progressbar'
import { computed, nextTick, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import type { Schemas, ValidationIssue } from '@/api/types'
import KeyValue from '@/components/base/KeyValue.vue'
import StatusDot from '@/components/base/StatusDot.vue'
import RefusalList from '@/components/settings/RefusalList.vue'
import ToolBuildPicker from '@/components/settings/ToolBuildPicker.vue'
import { resetOps, setByEnvironment, TOOL_NAMES, toolTone } from '@/components/settings/tools'
import { useBundledTools } from '@/components/settings/useBundledTools'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

import { useFirstRun } from './firstRun'
import { focusWorkspace } from './focus'
import FocusSafeButton from './FocusSafeButton'
import { formatList } from './format'

type ToolInfo = Schemas['ToolInfo']

const { t, locale } = useI18n()
const router = useRouter()
const system = useSystemStore()
const settings = useSettingsStore()
const { finish } = useFirstRun()
const { canDownload, fetching, fetchTask, use } = useBundledTools()

const checking = ref(false)
/** When the last *Check again* found the tools as they were: it says so, else nothing changes. */
const unchangedAt = ref<string | null>(null)
const bundledIssues = shallowRef<ValidationIssue[]>([])

/** FFmpeg works: only the desktop app's first start shows the screen. */
const welcome = computed(() => system.ffmpegProblem === null)
const tools = computed<ToolInfo[]>(() => {
  const set = system.info?.tools
  if (!set) return []
  return TOOL_NAMES.map((name) => set[name])
})

const failing = computed(() => tools.value.filter((tool) => tool.status !== 'found'))
/** The environment sets a tool that fails: it outranks Settings and a bundled build. */
const setByEnv = computed(() => failing.value.filter(setByEnvironment))
/** The server refuses tool paths from a browser; only the desktop app can choose one. */
const desktop = computed(() => system.info?.mode === 'desktop')
/** The offered builds, for a missing FFmpeg and every repair an override does not block. */
const showBuilds = computed(() => !welcome.value && setByEnv.value.length === 0)
/** A bundled build is there and works once the Settings paths that win over it are gone. */
const canBundle = computed(
  () =>
    showBuilds.value &&
    !canDownload.value &&
    resetOps(TOOL_NAMES, settings.settings?.tools).length > 0,
)
/** A failed start-up download (`REFRAME_FFMPEG_BUILD`). */
const serverProblems = computed(() =>
  system.warnings.filter((warning) => warning.code.startsWith('tools.')),
)
const canChoosePath = computed(() => desktop.value && setByEnv.value.length === 0)
const variables = computed(() =>
  formatList(
    (setByEnv.value.length > 0 ? setByEnv.value : failing.value)
      .map((tool) => tool.env_var)
      .filter((name): name is string => Boolean(name)),
    locale.value,
    'and',
  ),
)
const note = computed(() => {
  if (welcome.value) return null
  if (setByEnv.value.length > 0) return t('shell.firstRun.envNote', { variables: variables.value })
  if (!desktop.value) return t('shell.firstRun.webNote', { variables: variables.value })
  return null
})

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

function reasonText(tool: ToolInfo): string | null {
  const reason = tool.reason ?? null
  return reason === system.ffmpegProblem ? null : reason
}

async function useBundled(): Promise<void> {
  unchangedAt.value = null
  bundledIssues.value = []
  bundledIssues.value = await use('ffmpeg')
}

function snapshot(): string {
  return JSON.stringify(tools.value)
}

async function checkAgain(): Promise<void> {
  checking.value = true
  unchangedAt.value = null
  const before = snapshot()
  try {
    await system.rescanTools()
    if (snapshot() === before) {
      unchangedAt.value = new Intl.DateTimeFormat(locale.value, { timeStyle: 'medium' }).format(
        new Date(),
      )
    }
  } catch (error) {
    // The API client has shown it as a toast; the screen stays as it is.
    if (!(error instanceof ApiError)) throw error
  } finally {
    checking.value = false
  }
}

async function choosePath(): Promise<void> {
  await router.push({ name: 'settings', hash: '#tools' })
}

/** The workspace replaces this screen, and its *Continue* button with it. */
async function continueToWorkspace(): Promise<void> {
  finish()
  await nextTick()
  focusWorkspace()
}
</script>

<template>
  <section class="first-run" aria-labelledby="first-run-title" data-screen="first-run">
    <header class="first-run__header">
      <Wrench
        class="first-run__icon"
        :class="{ 'first-run__icon--ok': welcome }"
        :size="32"
        aria-hidden="true"
      />
      <h1 id="first-run-title" class="first-run__title">
        {{ welcome ? t('shell.firstRun.welcomeTitle') : t('shell.firstRun.title') }}
      </h1>
    </header>
    <p v-if="!welcome" class="first-run__reason" role="alert">{{ system.ffmpegProblem }}</p>
    <section
      v-if="!welcome && serverProblems.length > 0"
      class="first-run__problems"
      :aria-label="t('shell.firstRun.problems')"
      data-field="server-problems"
    >
      <p v-for="(problem, index) in serverProblems" :key="index" class="first-run__problem">
        {{ problem.message }}<template v-if="problem.detail">: {{ problem.detail }}</template>
      </p>
    </section>
    <p class="first-run__intro">
      {{ welcome ? t('shell.firstRun.welcomeIntro') : t('shell.firstRun.intro') }}
    </p>

    <h2 class="first-run__subtitle">{{ t('shell.firstRun.tools') }}</h2>
    <dl class="rf-kv-list first-run__tools">
      <KeyValue v-for="tool in tools" :key="tool.name" :label="tool.name">
        <span class="first-run__tool" :data-tool="tool.name">
          <StatusDot :tone="toolTone(tool)" :label="statusLabel(tool)" show-label />
          <span class="first-run__origin" data-field="origin">{{ originLabel(tool) }}</span>
          <code v-if="tool.path" class="first-run__path" data-field="path">{{ tool.path }}</code>
          <span v-else class="first-run__path first-run__path--none">
            {{ t('shell.firstRun.notFound') }}
          </span>
          <span v-if="reasonText(tool)" class="first-run__tool-reason" data-field="reason">{{
            reasonText(tool)
          }}</span>
          <span v-if="tool.version" class="first-run__version">
            {{ t('shell.firstRun.version', { version: tool.version }) }}
          </span>
        </span>
      </KeyValue>
    </dl>

    <template v-if="showBuilds">
      <h2 class="first-run__subtitle">{{ t('shell.firstRun.builds') }}</h2>
      <p class="first-run__intro">{{ t('shell.firstRun.buildsIntro') }}</p>
      <ToolBuildPicker />
    </template>

    <p v-if="note" class="first-run__note" data-field="note">{{ note }}</p>
    <RefusalList :issues="bundledIssues" />
    <div class="first-run__actions">
      <Button
        v-if="welcome"
        class="first-run__continue"
        :label="t('shell.firstRun.continue')"
        @click="continueToWorkspace"
      >
        <template #icon>
          <ArrowRight :size="18" aria-hidden="true" />
        </template>
      </Button>
      <FocusSafeButton
        v-if="canBundle"
        class="first-run__bundled"
        :label="t('shell.firstRun.useBundled')"
        :disabled="fetching"
        @click="useBundled"
      >
        <template #icon>
          <Undo2 :size="18" aria-hidden="true" />
        </template>
      </FocusSafeButton>
      <Button
        v-if="canChoosePath"
        class="first-run__choose"
        :label="welcome ? t('shell.firstRun.openSettings') : t('shell.firstRun.choosePath')"
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

.first-run__icon--ok {
  color: var(--p-status-ok-color);
}

.first-run__title {
  margin: 0;
  font-size: var(--rf-font-size-2xl);
}

.first-run__subtitle {
  margin: 0;
  font-size: var(--rf-font-size-lg);
}

.first-run__problems {
  display: grid;
  gap: var(--rf-space-1);
  padding: var(--rf-space-3) var(--rf-space-4);
  border: 1px solid var(--p-status-warn-border-color);
  border-radius: var(--rf-radius-md);
  background: var(--p-status-warn-background);
}

.first-run__problem {
  margin: 0;
  overflow-wrap: anywhere;
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
