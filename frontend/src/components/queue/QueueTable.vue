<script setup lang="ts">
import {
  ArrowDown,
  ArrowUp,
  Copy,
  FilePenLine,
  FolderOpen,
  ListVideo,
  LoaderCircle,
  Pause,
  Pencil,
  Play,
  RotateCcw,
  ScrollText,
  Square,
  Trash2,
} from '@lucide/vue'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable, { type DataTableRowReorderEvent } from 'primevue/datatable'
import ProgressBar from 'primevue/progressbar'
import vTooltip from 'primevue/tooltip'
import { computed, nextTick, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import type { QueueJob } from '@/api/types'
import { SEVERITY_ICON, useSeverityLabel } from '@/components/base/severity'
import StatusDot from '@/components/base/StatusDot.vue'
import FocusSafeButton from '@/components/shell/FocusSafeButton'
import { focusLost, focusWorkspace } from '@/components/shell/focus'
import { fileName } from '@/components/shell/format'
import { platform } from '@/platform'
import { useEditorStore } from '@/stores/editor'
import { useQueueStore } from '@/stores/queue'
import { SourceOpenError } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'
import { TaskLostError } from '@/stores/tasks'

import {
  type JobAction,
  jobActions,
  liveColumns,
  outputPath,
  sourceName,
  STATE_TONE,
  stateLabel,
} from './format'

const emit = defineEmits<{ openLog: [jobId: string, opener: HTMLElement] }>()

const { t, n } = useI18n()
const severityLabel = useSeverityLabel()
const queue = useQueueStore()
const editor = useEditorStore()
const system = useSystemStore()
const router = useRouter()
const root = useTemplateRef<HTMLElement>('root')

/** Reveal is the desktop app's; the web platform has no file manager to open. */
const canReveal = platform.kind === 'desktop'
/** The job being loaded into the editor. */
const editing = ref<string | null>(null)

const rows = computed(() =>
  queue.jobs.map((job, index) => ({
    job,
    index,
    actions: jobActions(job, canReveal),
    live: liveColumns(job, t, n),
  })),
)

/** A failed job shows its error and issues under its row. */
const expanded = computed<Record<string, boolean>>(() =>
  Object.fromEntries(
    queue.jobs
      .filter((job) => job.error || (job.state === 'failed' && (job.issues ?? []).length > 0))
      .map((job) => [job.id, true]),
  ),
)

/**
 * What the job's video does, by label: its own encoder (not the preset's), a copy, or a
 * metadata edit.
 */
function encoderName(job: QueueJob): string | null {
  if (job.settings.output?.edit_in_place) return t('queue.table.metadataEdit')
  const video = job.settings.video
  if (video === undefined) return null
  if (video.passthrough) return t('queue.table.videoCopy')
  return system.definitions?.video_encoders?.[video.encoder]?.label ?? video.encoder
}

function inPlaceTip(job: QueueJob): { value: string; id: string } {
  return {
    value: t('queue.table.inPlaceTip', { path: job.settings.source.path }),
    id: `queue-in-place-${job.id}`,
  }
}

// PrimeVue's tooltip shows on hover, or with `.focus` on focus only: this one does both.
function showTip(event: FocusEvent): void {
  event.target?.dispatchEvent(new MouseEvent('mouseenter'))
}

function hideTip(event: FocusEvent): void {
  event.target?.dispatchEvent(new MouseEvent('mouseleave'))
}

/** A failed job's issues, without the ones its error already quotes. */
function otherIssues(job: QueueJob): NonNullable<QueueJob['issues']> {
  const error = job.error ?? ''
  return (job.issues ?? []).filter((issue) => !error.includes(issue.message))
}

/** The API client has shown the problem as a toast. */
async function run(action: () => Promise<unknown>): Promise<void> {
  try {
    await action()
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
  }
}

async function edit(job: QueueJob): Promise<void> {
  if (editing.value !== null) return
  editing.value = job.id
  try {
    await editor.loadJob(job.settings)
    await router.push({ name: 'workspace' })
    await nextTick()
    focusWorkspace()
  } catch (error) {
    // The source could not be opened; the reason is a toast already.
    const shown =
      error instanceof ApiError ||
      error instanceof SourceOpenError ||
      error instanceof TaskLostError
    if (!shown) throw error
  } finally {
    editing.value = null
  }
}

function act(action: JobAction, job: QueueJob, event: Event): void {
  switch (action) {
    case 'pause':
      void run(() => queue.pause(job.id))
      return
    case 'resume':
      void run(() => queue.resume(job.id))
      return
    case 'cancel':
      void run(() => queue.cancel(job.id))
      return
    case 'retry':
      void run(() => queue.retry(job.id))
      return
    case 'duplicate':
      void run(() => queue.duplicate(job.id))
      return
    case 'remove':
      void run(() => queue.remove(job.id))
      return
    case 'edit':
      void edit(job)
      return
    case 'log':
      emit('openLog', job.id, event.currentTarget as HTMLElement)
      return
    case 'reveal': {
      const path = outputPath(job)
      if (path !== null) void platform.revealInFolder(path)
      return
    }
  }
}

function actionLabel(action: JobAction, name: string): string {
  switch (action) {
    case 'pause':
      return t('queue.actions.pause', { job: name })
    case 'resume':
      return t('queue.actions.resume', { job: name })
    case 'cancel':
      return t('queue.actions.cancel', { job: name })
    case 'retry':
      return t('queue.actions.retry', { job: name })
    case 'duplicate':
      return t('queue.actions.duplicate', { job: name })
    case 'edit':
      return t('queue.actions.edit', { job: name })
    case 'remove':
      return t('queue.actions.remove', { job: name })
    case 'log':
      return t('queue.actions.log', { job: name })
    case 'reveal':
      return t('queue.actions.reveal', { job: name })
  }
}

function actionTip(action: JobAction): string {
  switch (action) {
    case 'pause':
      return t('queue.actionTips.pause')
    case 'resume':
      return t('queue.actionTips.resume')
    case 'cancel':
      return t('queue.actionTips.cancel')
    case 'retry':
      return t('queue.actionTips.retry')
    case 'duplicate':
      return t('queue.actionTips.duplicate')
    case 'edit':
      return t('queue.actionTips.edit')
    case 'remove':
      return t('queue.actionTips.remove')
    case 'log':
      return t('queue.actionTips.log')
    case 'reveal':
      return t('queue.actionTips.reveal')
  }
}

const ICONS = {
  pause: Pause,
  resume: Play,
  cancel: Square,
  retry: RotateCcw,
  duplicate: Copy,
  edit: Pencil,
  remove: Trash2,
  log: ScrollText,
  reveal: FolderOpen,
} as const

function severity(action: JobAction): 'danger' | 'secondary' {
  return action === 'remove' || action === 'cancel' ? 'danger' : 'secondary'
}

/** The row button that had the focus before the jobs changed: its job, action and place. */
let focused: { jobId: string; name: string | null; index: number; row: number } | null = null

function rowButtons(group: Element | null | undefined): HTMLButtonElement[] {
  return [...(group?.querySelectorAll<HTMLButtonElement>('button') ?? [])]
}

function buttonName(button: Element): string | null {
  return button.getAttribute('data-action') ?? button.getAttribute('data-move')
}

function usable(button: HTMLButtonElement | undefined): button is HTMLButtonElement {
  return button !== undefined && !button.disabled
}

// A state change swaps a row's buttons (Pause for Resume) and a removal drops the row: the
// focused button goes away, and the focus goes to the button that took its place.
watch(
  rows,
  () => {
    focused = null
    const active = document.activeElement
    const group = active?.closest('[data-job]')
    const jobId = group?.getAttribute('data-job')
    if (!jobId || !group || !root.value?.contains(group)) return
    // The page still shows the rows from before the change.
    const row = [...root.value.querySelectorAll('[data-job]')].indexOf(group)
    const index = rowButtons(group).indexOf(active as HTMLButtonElement)
    focused = { jobId, name: active ? buttonName(active) : null, index, row }
  },
  { flush: 'pre' },
)

watch(
  rows,
  () => {
    const before = focused
    focused = null
    if (before === null || !focusLost()) return
    const groups = [...(root.value?.querySelectorAll('[data-job]') ?? [])]
    const same = groups.find((found) => found.getAttribute('data-job') === before.jobId)
    // A removed job's place goes to the job after it, else to the new last one.
    const group = same ?? groups[Math.min(before.row, groups.length - 1)]
    const buttons = rowButtons(group)
    const target =
      buttons.find((button) => usable(button) && buttonName(button) === before.name) ??
      // The job's new state brought its own action first (Resume for Pause, Retry for Cancel).
      (same === undefined
        ? undefined
        : buttons.find((button) => usable(button) && button.dataset.action)) ??
      buttons.slice(before.index).find(usable) ??
      buttons.slice(0, before.index).findLast(usable)
    if (target !== undefined) target.focus()
    else root.value?.querySelector<HTMLElement>('.queue-table__empty-link')?.focus()
  },
  { flush: 'post' },
)

function onReorder(event: DataTableRowReorderEvent): void {
  if (event.dragIndex === event.dropIndex) return
  const ids = (event.value as { job: QueueJob }[]).map((row) => row.job.id)
  void run(() => queue.reorder(ids))
}

/** One place up or down; the focus stays on the moved job's button. */
async function move(index: number, to: number): Promise<void> {
  const jobs = queue.jobs
  const moved = jobs[index]
  const other = jobs[to]
  if (moved === undefined || other === undefined) return
  // The two jobs swap the places they had among themselves; the others do not move.
  const ids = to < index ? [moved.id, other.id] : [other.id, moved.id]
  const done = run(() => queue.reorder(ids))
  await nextTick()
  const row = root.value?.querySelector(`[data-job="${moved.id}"]`)
  const first = to < index ? '[data-move="up"]' : '[data-move="down"]'
  const second = to < index ? '[data-move="down"]' : '[data-move="up"]'
  const target =
    row?.querySelector<HTMLElement>(`${first}:not(:disabled)`) ??
    row?.querySelector<HTMLElement>(`${second}:not(:disabled)`)
  target?.focus()
  await done
}
</script>

<template>
  <div ref="root" class="queue-table">
    <div v-if="queue.loaded && rows.length === 0" class="queue-table__empty" data-state="empty">
      <ListVideo class="queue-table__empty-icon" :size="40" aria-hidden="true" />
      <h2 class="queue-table__empty-title">{{ t('queue.empty.title') }}</h2>
      <p class="queue-table__empty-text">{{ t('queue.empty.text') }}</p>
      <RouterLink :to="{ name: 'workspace' }" class="queue-table__empty-link">
        {{ t('queue.empty.link') }}
      </RouterLink>
    </div>
    <DataTable
      v-else
      :value="rows"
      data-key="job.id"
      :expanded-rows="expanded"
      :table-props="{ 'aria-label': t('queue.table.label') }"
      scrollable
      @row-reorder="onReorder"
    >
      <Column row-reorder body-class="queue-table__handle" header-class="queue-table__handle">
        <template #header>
          <span class="rf-sr-only">{{ t('queue.columns.drag') }}</span>
        </template>
      </Column>
      <Column :header="t('queue.columns.state')" body-class="queue-table__state">
        <template #body="{ data }">
          <StatusDot
            :tone="STATE_TONE[data.job.state as QueueJob['state']]"
            :label="stateLabel(data.job.state, t)"
            show-label
          />
        </template>
      </Column>
      <Column :header="t('queue.columns.source')" body-class="queue-table__name">
        <template #body="{ data }">
          <span v-tooltip.top="data.job.settings.source.path" data-field="source" dir="ltr">
            {{ sourceName(data.job) }}
          </span>
        </template>
      </Column>
      <Column :header="t('queue.columns.output')" body-class="queue-table__name">
        <template #body="{ data }">
          <span
            v-if="data.job.settings.output?.edit_in_place"
            v-tooltip.top="inPlaceTip(data.job)"
            class="queue-table__in-place"
            tabindex="0"
            :aria-describedby="inPlaceTip(data.job).id"
            data-field="output"
            data-in-place
            @focus="showTip"
            @blur="hideTip"
          >
            <FilePenLine :size="14" aria-hidden="true" />
            {{ t('queue.table.inPlace') }}
          </span>
          <span
            v-else-if="outputPath(data.job)"
            v-tooltip.top="outputPath(data.job)"
            data-field="output"
            dir="ltr"
          >
            {{ fileName(outputPath(data.job) ?? '') }}
          </span>
        </template>
      </Column>
      <Column :header="t('queue.columns.preset')">
        <template #body="{ data }">
          <span data-field="preset">{{ data.job.settings.preset_name ?? '—' }}</span>
          <span v-if="encoderName(data.job)" class="queue-table__encoder" data-field="encoder">
            {{ encoderName(data.job) }}
          </span>
        </template>
      </Column>
      <Column :header="t('queue.columns.progress')" body-class="queue-table__progress">
        <template #body="{ data }">
          <template v-if="data.live.percent !== null">
            <ProgressBar
              :value="data.live.percent"
              :show-value="false"
              class="queue-table__bar"
              :pt="{ root: { 'aria-label': t('queue.columns.progress') } }"
            />
            <span class="queue-table__percent" data-field="percent">
              {{ data.live.percentText }}
            </span>
            <span v-if="data.live.step" class="queue-table__step" data-field="step">
              {{ data.live.step }}
            </span>
          </template>
        </template>
      </Column>
      <Column :header="t('queue.columns.fps')" body-class="queue-table__number">
        <template #body="{ data }">
          <span data-field="fps">{{ data.live.fps }}</span>
        </template>
      </Column>
      <Column :header="t('queue.columns.speed')" body-class="queue-table__number">
        <template #body="{ data }">
          <span data-field="speed">{{ data.live.speed }}</span>
        </template>
      </Column>
      <Column :header="t('queue.columns.eta')" body-class="queue-table__number">
        <template #body="{ data }">
          <span data-field="eta">{{ data.live.eta }}</span>
        </template>
      </Column>
      <Column :header="t('queue.columns.size')" body-class="queue-table__number">
        <template #body="{ data }">
          <span data-field="size">{{ data.live.size }}</span>
        </template>
      </Column>
      <Column body-class="queue-table__actions">
        <template #header>
          <span class="rf-sr-only">{{ t('queue.columns.actions') }}</span>
        </template>
        <template #body="{ data }">
          <div class="queue-table__buttons" :data-job="data.job.id" :data-state="data.job.state">
            <Button
              text
              rounded
              size="small"
              severity="secondary"
              data-move="up"
              :disabled="data.index === 0"
              :aria-label="t('queue.actions.moveUp', { job: sourceName(data.job) })"
              @click="move(data.index, data.index - 1)"
            >
              <template #icon><ArrowUp :size="18" aria-hidden="true" /></template>
            </Button>
            <Button
              text
              rounded
              size="small"
              severity="secondary"
              data-move="down"
              :disabled="data.index >= rows.length - 1"
              :aria-label="t('queue.actions.moveDown', { job: sourceName(data.job) })"
              @click="move(data.index, data.index + 1)"
            >
              <template #icon><ArrowDown :size="18" aria-hidden="true" /></template>
            </Button>
            <FocusSafeButton
              v-for="action in data.actions as JobAction[]"
              :key="action"
              v-tooltip.top="actionTip(action)"
              text
              rounded
              size="small"
              :severity="severity(action)"
              :data-action="action"
              :disabled="action === 'edit' && editing !== null"
              :aria-busy="(action === 'edit' && editing === data.job.id) || undefined"
              :aria-label="actionLabel(action, sourceName(data.job))"
              @click="act(action, data.job, $event)"
            >
              <template #icon>
                <LoaderCircle
                  v-if="action === 'edit' && editing === data.job.id"
                  class="queue-table__spin"
                  :size="18"
                  aria-hidden="true"
                />
                <component :is="ICONS[action]" v-else :size="18" aria-hidden="true" />
              </template>
            </FocusSafeButton>
          </div>
        </template>
      </Column>
      <template #expansion="{ data }">
        <div class="queue-table__problem" data-field="problem">
          <p v-if="data.job.error" class="queue-table__error" data-field="error">
            <component :is="SEVERITY_ICON.error" :size="16" aria-hidden="true" />
            <span>{{ data.job.error }}</span>
          </p>
          <ul v-if="otherIssues(data.job).length > 0" class="queue-table__issues">
            <li
              v-for="(issue, index) in otherIssues(data.job)"
              :key="`${issue.code}:${index}`"
              :class="`queue-table__issue--${issue.severity}`"
              :data-severity="issue.severity"
            >
              <component
                :is="SEVERITY_ICON[issue.severity as 'error']"
                :size="16"
                aria-hidden="true"
              />
              <span class="rf-sr-only">{{ severityLabel(issue.severity) }}: </span>
              <span>{{ issue.message }}</span>
            </li>
          </ul>
        </div>
      </template>
    </DataTable>
  </div>
</template>

<style scoped>
.queue-table {
  min-width: 0;
}

.queue-table__empty {
  display: grid;
  justify-items: center;
  gap: var(--rf-space-3);
  padding: var(--rf-space-6) var(--rf-space-4);
  color: var(--rf-color-text-muted);
  text-align: center;
}

.queue-table__empty-title {
  margin: 0;
  color: var(--rf-color-text);
  font-size: var(--rf-font-size-xl);
}

.queue-table__empty-text {
  margin: 0;
}

.queue-table__empty-link {
  color: var(--rf-color-primary);
}

.queue-table :deep(.queue-table__handle) {
  width: 2rem;
  padding-inline: var(--rf-space-1);
  cursor: grab;
}

.queue-table :deep(.queue-table__state) {
  white-space: nowrap;
}

.queue-table :deep(.queue-table__name) {
  max-width: 16rem;
  overflow-wrap: anywhere;
}

.queue-table__in-place {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
}

.queue-table__in-place svg {
  flex: none;
}

.queue-table :deep(.queue-table__progress) {
  min-width: 9rem;
}

.queue-table__bar {
  height: 0.5rem;
}

.queue-table__percent,
.queue-table__step,
.queue-table__encoder {
  display: block;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
}

.queue-table :deep(.queue-table__number) {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.queue-table__buttons {
  display: flex;
  flex-wrap: nowrap;
  justify-content: flex-end;
}

/* The table gives the last column what is left; the buttons keep their size. */
.queue-table__buttons > :deep(.p-button) {
  flex: none;
}

/* A small icon-only button's padding leaves less than the icon's width: it would shrink. */
.queue-table__buttons :deep(.p-button svg) {
  flex: none;
}

.queue-table__spin {
  animation: queue-table-spin 1s linear infinite;
}

@keyframes queue-table-spin {
  to {
    transform: rotate(360deg);
  }
}

.queue-table__problem {
  display: grid;
  gap: var(--rf-space-2);
  padding-inline-start: var(--rf-space-6);
}

.queue-table__error,
.queue-table__issues li {
  display: flex;
  align-items: flex-start;
  gap: var(--rf-space-2);
  margin: 0;
}

.queue-table__error,
.queue-table__issue--error {
  color: var(--p-status-error-color);
}

.queue-table__issue--warning {
  color: var(--p-status-warn-color);
}

.queue-table__issues {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
