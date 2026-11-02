<script setup lang="ts">
import { Check, LoaderCircle, Minus } from '@lucide/vue'
import { computed, ref, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type {
  AudioStream,
  MediaSource,
  SubtitleStream,
  TrackDecision,
  TrackDraft,
} from '@/api/types'
import { bySeverity, SEVERITY_ICON } from '@/components/base/severity'
import ScanControl from '@/components/media/ScanControl.vue'
import { streamLabel, trackNumber } from '@/components/media/streams'
import { useDefaultsStore } from '@/stores/defaults'
import { useScansStore } from '@/stores/scans'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'

import IssueLines from './IssueLines.vue'
import { shownAtField } from './model'
import { outputLines } from './preview'

/**
 * One row per source track: what the edited defaults take or drop, and why; in a group, one
 * table per file. Only the newest answer is shown.
 */
const { t } = useI18n()
const defaults = useDefaultsStore()
const scans = useScansStore()
const sources = useSourcesStore()
const system = useSystemStore()
const id = useId()
const root = useTemplateRef<HTMLElement>('root')

/** One file's answer; `label` names the file in a group. */
interface FileTable {
  sourceId: string | null
  label: string | null
  source: MediaSource | null
  draft: TrackDraft
}

const audio = computed(() => defaults.kind === 'audio')
const group = computed(() => defaults.target?.kind === 'group')
const tables = computed<FileTable[]>(() => {
  if (group.value) {
    return defaults.previews.map((file) => ({
      sourceId: file.id,
      label: file.label,
      source: sources.entries.find((entry) => entry.id === file.id)?.source ?? null,
      draft: file.draft,
    }))
  }
  const draft = defaults.preview
  return draft === null
    ? []
    : [{ sourceId: defaults.sourceId, label: null, source: defaults.source, draft }]
})
const fileName = computed(() =>
  group.value ? null : (defaults.source?.ref?.path?.split(/[\\/]/).at(-1) ?? null),
)
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

function decisionsOf(table: FileTable): TrackDecision[] {
  return (audio.value ? table.draft.decisions : table.draft.subtitle_decisions) ?? []
}

function streamOf(table: FileTable, decision: TrackDecision) {
  const streams: (AudioStream | SubtitleStream)[] =
    (audio.value ? table.source?.audio : table.source?.subtitles) ?? []
  return streams.find((stream) => stream.index === decision.source_stream)
}

function sourceText(table: FileTable, decision: TrackDecision): string {
  const stream = streamOf(table, decision)
  return stream ? streamLabel(stream) : t('defaults.preview.unknownStream')
}

function outputs(table: FileTable, decision: TrackDecision): string[] {
  const stream = streamOf(table, decision)
  return outputLines(decision, stream?.kind === 'audio' ? stream : undefined, system.definitions, t)
}

function measureRun(table: FileTable, decision: TrackDecision) {
  const sourceId = table.sourceId
  return sourceId === null ? undefined : scans.running(sourceId, 'bitrate', decision.source_stream)
}

function number(table: FileTable, decision: TrackDecision): number {
  const stream = streamOf(table, decision)
  return stream ? trackNumber(stream) : decision.source_stream
}

function measure(table: FileTable, decision: TrackDecision): void {
  const sourceId = table.sourceId
  // The scans store shows a failure as a toast, so nothing is shown here.
  if (sourceId !== null)
    void scans.measureBitrate(sourceId, decision.source_stream).catch(() => undefined)
}

const announcement = ref('')

/**
 * The reason replaced the Measure button, which had the focus: the row header takes it, so the
 * focus stays in the dialog. The new answer must already be shown for the announcement.
 */
function measured(index: number, stream: number): void {
  root.value
    ?.querySelector<HTMLElement>(`[data-table="${index}"] tr[data-stream="${stream}"] th`)
    ?.focus()
  const table = tables.value[index]
  const decision = table && decisionsOf(table).find((each) => each.source_stream === stream)
  if (table && decision && !decision.measure) {
    announcement.value = t('defaults.preview.measured', {
      n: number(table, decision),
      reason: decision.reason,
    })
  }
}
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
      <div
        v-for="(table, index) in tables"
        :key="table.sourceId ?? index"
        class="defaults-preview__one-file"
        :data-table="index"
        :data-source="table.sourceId"
      >
        <h3
          v-if="table.label !== null"
          :id="`${id}-file-${index}`"
          class="defaults-preview__subtitle"
        >
          {{ table.label }}
        </h3>
        <p
          v-if="decisionsOf(table).length === 0"
          class="defaults-preview__empty"
          data-state="no-tracks"
        >
          {{ audio ? t('defaults.preview.noAudio') : t('defaults.preview.noSubtitles') }}
        </p>
        <div v-else class="defaults-preview__scroll">
          <table
            class="defaults-preview__table"
            :aria-labelledby="
              table.label === null ? `${id}-title` : `${id}-title ${id}-file-${index}`
            "
          >
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
                v-for="decision in decisionsOf(table)"
                :key="decision.source_stream"
                :data-stream="decision.source_stream"
                :data-selected="decision.selected"
              >
                <th scope="row" class="defaults-preview__source" tabindex="-1">
                  <span>{{ sourceText(table, decision) }}</span
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
                      decision.selected
                        ? t('defaults.preview.taken')
                        : t('defaults.preview.dropped')
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
                  <template v-if="outputs(table, decision).length > 0">
                    <span
                      v-for="(line, lineIndex) in outputs(table, decision)"
                      :key="lineIndex"
                      class="defaults-preview__output"
                      :class="{ 'defaults-preview__muted': lineIndex > 0 }"
                    >
                      {{ lineIndex > 0 ? t('defaults.preview.extra', { output: line }) : line }}
                    </span>
                  </template>
                  <span v-else>—</span>
                </td>
                <td data-column="reason">
                  <span class="defaults-preview__reason">{{ decision.reason }}</span>
                  <ul v-if="(decision.notes ?? []).length > 0" class="defaults-preview__notes">
                    <li v-for="(note, noteIndex) in decision.notes" :key="noteIndex">
                      {{ note }}
                    </li>
                  </ul>
                  <ScanControl
                    v-if="decision.measure && audio"
                    class="defaults-preview__measure"
                    :run="measureRun(table, decision)"
                    :label="t('media.scan.measure')"
                    :start-label="t('media.scan.measureBitrate', { n: number(table, decision) })"
                    :progress-label="
                      t('media.scan.measuringBitrate', { n: number(table, decision) })
                    "
                    :cancel-label="t('media.scan.cancelBitrate', { n: number(table, decision) })"
                    :help="t('defaults.preview.measureHelp')"
                    @start="measure(table, decision)"
                    @cancel="scans.cancel($event)"
                    @leave="measured(index, decision.source_stream)"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
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

.defaults-preview__one-file,
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
