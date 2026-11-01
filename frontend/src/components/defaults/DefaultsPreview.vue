<script setup lang="ts">
import { Check, LoaderCircle, Minus } from '@lucide/vue'
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'

import type { AudioStream, SubtitleStream, TrackDecision } from '@/api/types'
import { bySeverity } from '@/components/base/severity'
import ScanControl from '@/components/media/ScanControl.vue'
import { streamLabel, trackNumber } from '@/components/media/streams'
import { useDefaultsStore } from '@/stores/defaults'
import { useScansStore } from '@/stores/scans'
import { useSystemStore } from '@/stores/system'

import IssueLines from './IssueLines.vue'
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
const issues = computed(() => bySeverity(defaults.issues.map((placed) => placed.issue)))

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

function measure(decision: TrackDecision): void {
  const sourceId = defaults.sourceId
  // A failure is the scans store's toast; the measured source comes back through the watcher.
  if (sourceId !== null)
    void scans.measureBitrate(sourceId, decision.source_stream).catch(() => undefined)
}

function number(decision: TrackDecision): number {
  const stream = streamOf(decision)
  return stream ? trackNumber(stream) : decision.source_stream
}
</script>

<template>
  <section
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
              <th scope="row" class="defaults-preview__source">
                <span>{{ sourceText(decision) }}</span>
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
                  }}
                </span>
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
      <div v-if="issues.length > 0" class="defaults-preview__issues">
        <h3 class="defaults-preview__subtitle">{{ t('defaults.preview.issues') }}</h3>
        <IssueLines :issues="issues" fixes />
      </div>
    </template>
    <p v-else class="defaults-preview__empty" data-state="loading">
      {{ t('defaults.preview.loading') }}
    </p>
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
  overflow-x: auto;
}

.defaults-preview[aria-busy='true'] .defaults-preview__table {
  opacity: 0.6;
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
