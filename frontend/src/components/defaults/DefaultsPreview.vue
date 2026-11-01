<script setup lang="ts">
import { Check, LoaderCircle, Minus } from '@lucide/vue'
import { useEventListener } from '@vueuse/core'
import { computed, ref, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { AudioStream, SubtitleStream, TrackDecision } from '@/api/types'
import { bySeverity, SEVERITY_ICON } from '@/components/base/severity'
import ScanControl from '@/components/media/ScanControl.vue'
import { streamLabel, trackNumber } from '@/components/media/streams'
import { useDefaultsStore } from '@/stores/defaults'
import { useScansStore } from '@/stores/scans'
import { useSystemStore } from '@/stores/system'

import IssueLines from './IssueLines.vue'
import { shownAtField } from './model'
import { outputLines } from './preview'

/**
 * What the edited defaults do with the source, one row per source track: taken or dropped and
 * why, the rule, the output and the reason. Only the newest answer is shown; the table is
 * marked busy while a newer one is on its way.
 */
const { t } = useI18n()
const defaults = useDefaultsStore()
const scans = useScansStore()
const system = useSystemStore()
const id = useId()
const root = useTemplateRef<HTMLElement>('root')

const audio = computed(() => defaults.kind === 'audio')
const decisions = computed<TrackDecision[]>(() => {
  const draft = defaults.preview
  if (draft === null) return []
  return (audio.value ? draft.decisions : draft.subtitle_decisions) ?? []
})
const streams = computed<(AudioStream | SubtitleStream)[]>(() =>
  audio.value ? (defaults.source?.audio ?? []) : (defaults.source?.subtitles ?? []),
)
const fileName = computed(() => defaults.source?.ref?.path?.split(/[\\/]/).at(-1) ?? null)
const member = computed(() => (audio.value ? 'audio_defaults' : 'subtitle_defaults'))
/** The issues of the defaults this dialog edits; the other kind's are not editable here. */
const own = computed(() =>
  defaults.issues.filter(({ at }) => at === '' || at.split(/[.[]/)[0] === member.value),
)
/** The rules and fields show their own issues; the rest are listed under the table. */
const unplaced = computed(() =>
  bySeverity(own.value.filter(({ at }) => !shownAtField(at)).map(({ issue }) => issue)),
)
const counts = computed(() =>
  (['error', 'warning', 'info'] as const)
    .map((severity) => ({
      severity,
      count: own.value.filter(({ issue }) => issue.severity === severity).length,
    }))
    .filter(({ count }) => count > 0),
)

function streamOf(decision: TrackDecision) {
  return streams.value.find((stream) => stream.index === decision.source_stream)
}

function sourceText(decision: TrackDecision): string {
  const stream = streamOf(decision)
  return stream ? streamLabel(stream) : t('defaults.preview.unknownStream')
}

function outputs(decision: TrackDecision): string[] {
  const stream = streamOf(decision)
  return outputLines(decision, stream?.kind === 'audio' ? stream : undefined, system.definitions, t)
}

function measureRun(decision: TrackDecision) {
  const sourceId = defaults.sourceId
  return sourceId === null ? undefined : scans.running(sourceId, 'bitrate', decision.source_stream)
}

function number(decision: TrackDecision): number {
  const stream = streamOf(decision)
  return stream ? trackNumber(stream) : decision.source_stream
}

/** The track whose Measure was started here, while the focus follows its row. */
const measuring = ref<number | null>(null)
const announcement = ref('')

function rowOf(stream: number): HTMLElement | null {
  return root.value?.querySelector<HTMLElement>(`tr[data-stream="${stream}"]`) ?? null
}

/**
 * Measure gives way to the scan's progress and that to the new reason: the focused control is
 * removed, and the focus would leave the dialog. It goes to what the row has now.
 */
function keepFocus(stream: number): void {
  const active = document.activeElement
  if (active !== null && active !== document.body && active.isConnected) return
  const row = rowOf(stream)
  const control = row?.querySelector<HTMLElement>(
    '[data-action="cancel-scan"], [data-action="start-scan"]',
  )
  ;(control ?? row?.querySelector<HTMLElement>('th'))?.focus()
}

function measure(decision: TrackDecision): void {
  const sourceId = defaults.sourceId
  if (sourceId === null) return
  measuring.value = decision.source_stream
  // A failure is the scans store's toast; the measured source comes back through the watcher.
  void scans.measureBitrate(sourceId, decision.source_stream).catch(() => undefined)
}

watch(
  () => {
    const stream = measuring.value
    const sourceId = defaults.sourceId
    if (stream === null || sourceId === null) return null
    return [defaults.preview, scans.running(sourceId, 'bitrate', stream)] as const
  },
  (now) => {
    const stream = measuring.value
    if (now === null || stream === null) return
    keepFocus(stream)
    const decision = decisions.value.find((each) => each.source_stream === stream)
    if (now[1] === undefined && decision !== undefined && !decision.measure) {
      announcement.value = t('defaults.preview.measured', {
        n: number(decision),
        reason: decision.reason,
      })
      measuring.value = null
    }
  },
  { flush: 'post' },
)

// The user went elsewhere: the focus is theirs again.
useEventListener(document, 'focusin', (event: FocusEvent) => {
  const stream = measuring.value
  if (stream === null || !(event.target instanceof Node)) return
  if (!rowOf(stream)?.contains(event.target)) measuring.value = null
})
</script>

<template>
  <section
    ref="root"
    class="defaults-preview"
    :aria-labelledby="`${id}-title`"
    :aria-busy="defaults.previewing"
    data-role="preview"
    :data-state="defaults.previewing ? 'updating' : 'ready'"
  >
    <header class="defaults-preview__header">
      <h2 :id="`${id}-title`" class="defaults-preview__title">
        {{ t('defaults.preview.title') }}
      </h2>
      <span v-if="fileName" class="defaults-preview__file">{{ fileName }}</span>
      <span
        v-if="counts.length > 0 && defaults.preview !== null"
        class="defaults-preview__counts"
        data-role="issue-counts"
      >
        <span
          v-for="{ severity, count } in counts"
          :key="severity"
          class="defaults-preview__count"
          :class="`defaults-preview__count--${severity}`"
        >
          <component :is="SEVERITY_ICON[severity]" :size="14" aria-hidden="true" />
          {{ t(`defaults.preview.count.${severity}`, count) }}
        </span>
      </span>
      <span v-if="defaults.previewing" class="defaults-preview__updating">
        <LoaderCircle class="defaults-preview__spinner" :size="14" aria-hidden="true" />
        {{ t('defaults.preview.updating') }}
      </span>
    </header>
    <p v-if="defaults.sourceId === null" class="defaults-preview__empty" data-state="no-source">
      {{ t('defaults.preview.noSource') }}
    </p>
    <p
      v-else-if="defaults.previewFailure !== null"
      class="defaults-preview__empty"
      data-state="failed"
    >
      {{ t('defaults.preview.failed', { detail: defaults.previewFailure }) }}
    </p>
    <template v-else-if="defaults.preview !== null">
      <p v-if="decisions.length === 0" class="defaults-preview__empty" data-state="no-tracks">
        {{ audio ? t('defaults.preview.noAudio') : t('defaults.preview.noSubtitles') }}
      </p>
      <div v-else class="defaults-preview__scroll">
        <table class="defaults-preview__table" :aria-labelledby="`${id}-title`">
          <thead>
            <tr>
              <th scope="col">{{ t('defaults.preview.source') }}</th>
              <th scope="col">{{ t('defaults.preview.selected') }}</th>
              <th v-if="audio" scope="col">{{ t('defaults.preview.rule') }}</th>
              <th scope="col">{{ t('defaults.preview.output') }}</th>
              <th scope="col">{{ t('defaults.preview.reason') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="decision in decisions"
              :key="decision.source_stream"
              :data-stream="decision.source_stream"
              :data-selected="decision.selected"
            >
              <th scope="row" class="defaults-preview__source" tabindex="-1">
                <span>{{ sourceText(decision) }}</span
                >{{ ' ' }}
                <span class="defaults-preview__muted">
                  {{ t('defaults.preview.stream', { index: decision.source_stream }) }}
                </span>
              </th>
              <td class="defaults-preview__selection" data-column="selected">
                <span class="defaults-preview__taken">
                  <Check v-if="decision.selected" :size="14" aria-hidden="true" />
                  <Minus v-else :size="14" aria-hidden="true" />
                  {{
                    decision.selected ? t('defaults.preview.taken') : t('defaults.preview.dropped')
                  }} </span
                >{{ ' ' }}
                <span v-if="decision.selection" class="defaults-preview__muted">
                  {{ decision.selection }}
                </span>
              </td>
              <td v-if="audio" class="defaults-preview__rule" data-column="rule">
                {{ decision.rule ?? '—' }}
              </td>
              <td data-column="output">
                <template v-if="outputs(decision).length > 0">
                  <span
                    v-for="(line, index) in outputs(decision)"
                    :key="index"
                    class="defaults-preview__output"
                    :class="{ 'defaults-preview__muted': index > 0 }"
                  >
                    {{ index > 0 ? t('defaults.preview.extra', { output: line }) : line }}
                  </span>
                </template>
                <span v-else>—</span>
              </td>
              <td data-column="reason">
                <span class="defaults-preview__reason">{{ decision.reason }}</span>
                <ul v-if="(decision.notes ?? []).length > 0" class="defaults-preview__notes">
                  <li v-for="(note, index) in decision.notes" :key="index">{{ note }}</li>
                </ul>
                <ScanControl
                  v-if="decision.measure && audio"
                  class="defaults-preview__measure"
                  :run="measureRun(decision)"
                  :label="t('media.scan.measure')"
                  :start-label="t('media.scan.measureBitrate', { n: number(decision) })"
                  :progress-label="t('media.scan.measuringBitrate', { n: number(decision) })"
                  :cancel-label="t('media.scan.cancelBitrate', { n: number(decision) })"
                  :help="t('defaults.preview.measureHelp')"
                  @start="measure(decision)"
                  @cancel="scans.cancel($event)"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="unplaced.length > 0" class="defaults-preview__issues">
        <h3 class="defaults-preview__subtitle">{{ t('defaults.preview.issues') }}</h3>
        <IssueLines :issues="unplaced" fixes />
      </div>
    </template>
    <p v-else class="defaults-preview__empty" data-state="loading">
      {{ t('defaults.preview.loading') }}
    </p>
    <span class="rf-sr-only" aria-live="polite" data-role="announcement">{{ announcement }}</span>
  </section>
</template>

<style scoped>
.defaults-preview {
  display: grid;
  gap: var(--rf-space-2);
  align-content: start;
}

.defaults-preview__header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--rf-space-1) var(--rf-space-3);
}

.defaults-preview__title {
  margin: 0;
  font-size: var(--rf-font-size-md);
  font-weight: var(--rf-font-weight-bold);
}

.defaults-preview__file,
.defaults-preview__muted,
.defaults-preview__updating,
.defaults-preview__empty {
  color: var(--rf-color-text-muted);
}

.defaults-preview__file,
.defaults-preview__muted,
.defaults-preview__notes {
  font-size: var(--rf-font-size-sm);
}

.defaults-preview__counts {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--rf-space-3);
  font-size: var(--rf-font-size-sm);
}

.defaults-preview__count {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
}

.defaults-preview__count--error svg {
  color: var(--p-status-error-color);
}

.defaults-preview__count--warning svg {
  color: var(--p-status-warn-color);
}

.defaults-preview__count--info svg {
  color: var(--p-status-info-color);
}

.defaults-preview__updating {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
  font-size: var(--rf-font-size-sm);
}

.defaults-preview__spinner {
  animation: defaults-preview-spin 1s linear infinite;
}

@media (prefers-reduced-motion: reduce) {
  .defaults-preview__spinner {
    animation: none;
  }
}

@keyframes defaults-preview-spin {
  to {
    transform: rotate(360deg);
  }
}

.defaults-preview__empty {
  margin: 0;
}

.defaults-preview__scroll {
  position: relative;
  overflow-x: auto;
}

/* Busy: a bar runs along the table's top. Fading the table would take its text below AA. */
.defaults-preview[aria-busy='true'] .defaults-preview__scroll::before {
  position: absolute;
  inset: 0 0 auto;
  height: 3px;
  background: linear-gradient(var(--rf-color-primary), var(--rf-color-primary)) no-repeat;
  background-size: 40% 100%;
  animation: defaults-preview-busy 1.2s linear infinite;
  content: '';
}

@keyframes defaults-preview-busy {
  from {
    background-position: -50% 0;
  }

  to {
    background-position: 150% 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .defaults-preview[aria-busy='true'] .defaults-preview__scroll::before {
    background-size: 100% 100%;
    animation: none;
  }
}

.defaults-preview__table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--rf-font-size-sm);
}

.defaults-preview__table th,
.defaults-preview__table td {
  padding: var(--rf-space-1) var(--rf-space-2);
  border-bottom: 1px solid var(--rf-color-border);
  text-align: start;
  vertical-align: top;
}

.defaults-preview__table thead th {
  color: var(--rf-color-text-muted);
  font-weight: var(--rf-font-weight-medium);
  white-space: nowrap;
}

.defaults-preview__source {
  font-weight: var(--rf-font-weight-normal);
}

.defaults-preview__source,
.defaults-preview__selection,
.defaults-preview__table td[data-column='output'] {
  min-width: 10rem;
}

.defaults-preview__source > span,
.defaults-preview__selection > span,
.defaults-preview__output {
  display: block;
}

.defaults-preview__taken {
  display: inline-flex !important;
  align-items: center;
  gap: var(--rf-space-1);
  font-weight: var(--rf-font-weight-medium);
}

.defaults-preview__rule {
  font-variant-numeric: tabular-nums;
  text-align: center !important;
}

.defaults-preview__notes {
  margin: var(--rf-space-1) 0 0;
  padding-inline-start: var(--rf-space-4);
  color: var(--rf-color-text-muted);
}

.defaults-preview__measure {
  display: flex;
  width: fit-content;
  margin-top: var(--rf-space-1);
}

.defaults-preview__issues {
  display: grid;
  gap: var(--rf-space-2);
}

.defaults-preview__subtitle {
  margin: 0;
  font-size: var(--rf-font-size-sm);
  font-weight: var(--rf-font-weight-bold);
}
</style>
