<script setup lang="ts">
import { ChevronRight } from '@lucide/vue'
import vTooltip from 'primevue/tooltip'
import { computed, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'

import type { AudioStream, Schemas, SubtitleStream } from '@/api/types'
import CodecLabel from '@/components/base/CodecLabel.vue'
import KeyValue from '@/components/base/KeyValue.vue'
import LanguageChip from '@/components/base/LanguageChip.vue'
import RoleBadge from '@/components/base/RoleBadge.vue'
import { useJobSource } from '@/components/summary/useJobSource'
import { type ScanRun, useScansStore } from '@/stores/scans'

import ScanControl from './ScanControl.vue'
import {
  channelsText,
  delayText,
  hasForcedEvents,
  kbps,
  kiloHertz,
  oneDecimal,
  preciseDuration,
  setDispositions,
  type ShownFlag,
  shownFlags,
  type SourceStream,
  streamLanguage,
  trackNumber,
} from './streams'

/**
 * The source's tracks of one kind, read only; a row expands to every detail of its track. The
 * scans (bitrate, events, loudness) run on `sourceId`, by default the editor job's source;
 * `null`: no scans.
 */
const props = defineProps<{
  kind: 'audio' | 'subtitle'
  streams: readonly SourceStream[]
  sourceId?: string | null
}>()

const { t } = useI18n()
const id = useId()
const scans = useScansStore()
const jobSource = useJobSource()

const scanSource = computed(() =>
  props.sourceId === undefined ? jobSource.sourceId.value : props.sourceId,
)

function runOf(kind: 'bitrate' | 'subtitle' | 'loudness', stream: SourceStream | null) {
  const source = scanSource.value
  return source === null ? undefined : scans.running(source, kind, stream?.index ?? null)
}

/** Every subtitle track is being counted: a track's own count would join that scan. */
const countingAll = computed(
  () => props.kind === 'subtitle' && runOf('subtitle', null) !== undefined,
)

function measureBitrate(stream: SourceStream): void {
  if (scanSource.value !== null) void scans.measureBitrate(scanSource.value, stream.index)
}

function countEvents(stream: SourceStream | null): void {
  if (scanSource.value === null) return
  void scans.scanSubtitles(scanSource.value, stream === null ? undefined : [stream.index])
}

function measureLoudness(stream: SourceStream): void {
  if (scanSource.value !== null) void scans.measureLoudness(scanSource.value, stream.index)
}

function cancel(run: ScanRun): void {
  void scans.cancel(run)
}

function loudnessOf(stream: SourceStream) {
  return scanSource.value === null
    ? undefined
    : scans.loudness[`${scanSource.value}:${stream.index}`]
}

function measured(value: number | null | undefined, key: 'lufs' | 'dbtp' | 'lu'): string {
  if (value === null || value === undefined) return '—'
  return t(`media.loudness.${key}`, { value: oneDecimal(value) })
}

const expanded = ref(new Set<number>())

function toggle(stream: SourceStream): void {
  const next = new Set(expanded.value)
  if (!next.delete(stream.index)) next.add(stream.index)
  expanded.value = next
}

const columns = computed(() => (props.kind === 'audio' ? 8 : 7))

function flagLabel(flag: ShownFlag): string {
  switch (flag) {
    case 'default':
      return t('tracks.flag.default')
    case 'original':
      return t('tracks.flag.original')
    case 'dub':
      return t('tracks.flag.dub')
    case 'forced':
      return t('tracks.flag.forced')
    case 'comment':
      return t('tracks.flag.comment')
    case 'hearing_impaired':
      return t('tracks.flag.hearingImpaired')
    case 'visual_impaired':
      return t('tracks.flag.visualImpaired')
    case 'captions':
      return t('tracks.flag.captions')
    case 'descriptions':
      return t('tracks.flag.descriptions')
    case 'lyrics':
      return t('tracks.flag.lyrics')
    case 'karaoke':
      return t('tracks.flag.karaoke')
    case 'clean_effects':
      return t('tracks.flag.cleanEffects')
    case 'non_diegetic':
      return t('tracks.flag.nonDiegetic')
  }
  return flag
}

function bitrateSource(source: Schemas['BitrateSource']): string {
  switch (source) {
    case 'stream':
      return t('tracks.source.bitrateFrom.stream')
    case 'stats_tag':
      return t('tracks.source.bitrateFrom.statsTag')
    case 'mediainfo':
      return t('tracks.source.bitrateFrom.mediainfo')
    case 'measured':
      return t('tracks.source.bitrateFrom.measured')
  }
  return t('tracks.source.bitrateFrom.unknown')
}

function bitrateHelp(source: Schemas['BitrateSource'] | undefined): string {
  switch (source) {
    case 'stream':
      return t('tracks.source.bitrateHelp.stream')
    case 'stats_tag':
      return t('tracks.source.bitrateHelp.statsTag')
    case 'mediainfo':
      return t('tracks.source.bitrateHelp.mediainfo')
    case 'measured':
      return t('tracks.source.bitrateHelp.measured')
  }
  return t('tracks.source.bitrateHelp.unknown')
}

function eventsHelp(stream: SubtitleStream): string | undefined {
  switch (stream.event_count_source) {
    case 'stats_tag':
      return t('tracks.source.eventsFrom.statsTag')
    case 'measured':
      return t('tracks.source.eventsFrom.measured')
  }
  return stream.event_count === null || stream.event_count === undefined
    ? t('tracks.source.eventsFrom.unknown')
    : undefined
}

function rateDepth(stream: AudioStream): string | null {
  if (!stream.sample_rate)
    return stream.bit_depth ? t('tracks.units.bits', { bits: stream.bit_depth }) : null
  const rate = t('tracks.units.khz', { value: kiloHertz(stream.sample_rate) })
  return stream.bit_depth ? t('tracks.units.rateDepth', { rate, bits: stream.bit_depth }) : rate
}

function typeLabel(stream: SubtitleStream): string {
  return stream.subtitle_kind === 'bitmap' ? t('tracks.source.bitmap') : t('tracks.source.text')
}

function seconds(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : preciseDuration(value)
}

function tagsOf(stream: SourceStream): [string, string][] {
  return Object.entries(stream.tags ?? {})
}
</script>

<template>
  <div class="track-table" :data-kind="kind">
    <p v-if="streams.length === 0" class="track-table__empty">
      {{ kind === 'audio' ? t('tracks.source.noAudio') : t('tracks.source.noSubtitles') }}
    </p>
    <div
      v-if="kind === 'subtitle' && streams.length > 0 && scanSource !== null"
      class="track-table__actions"
    >
      <ScanControl
        :run="runOf('subtitle', null)"
        :label="t('media.scan.countAll')"
        :start-label="t('media.scan.countAllLabel')"
        :progress-label="t('media.scan.countingAll')"
        :cancel-label="t('media.scan.cancelCountAll')"
        :help="t('media.scan.countHelp')"
        data-scan="events-all"
        @start="countEvents(null)"
        @cancel="cancel"
      />
    </div>
    <div v-if="streams.length > 0" class="track-table__scroll">
      <table class="track-table__table">
        <caption class="rf-sr-only">
          {{
            kind === 'audio' ? t('tracks.source.audioCaption') : t('tracks.source.subtitleCaption')
          }}
        </caption>
        <thead>
          <tr>
            <th scope="col">{{ t('tracks.source.number') }}</th>
            <th scope="col">{{ t('tracks.source.language') }}</th>
            <th scope="col">{{ t('tracks.source.name') }}</th>
            <template v-if="kind === 'audio'">
              <th scope="col">{{ t('tracks.source.codec') }}</th>
              <th scope="col">{{ t('tracks.source.channels') }}</th>
              <th scope="col">{{ t('tracks.source.rateDepth') }}</th>
              <th scope="col">{{ t('tracks.source.bitrate') }}</th>
            </template>
            <template v-else>
              <th scope="col">{{ t('tracks.source.format') }}</th>
              <th scope="col">{{ t('tracks.source.type') }}</th>
              <th scope="col">{{ t('tracks.source.events') }}</th>
            </template>
            <th scope="col">{{ t('tracks.source.roles') }}</th>
          </tr>
        </thead>
        <tbody v-for="stream in streams" :key="stream.index">
          <tr
            class="track-table__row"
            :class="{ 'track-table__row--open': expanded.has(stream.index) }"
            :data-stream="stream.index"
            @click="toggle(stream)"
          >
            <td class="track-table__number">
              <button
                type="button"
                class="track-table__toggle"
                :aria-expanded="expanded.has(stream.index)"
                :aria-controls="`${id}-${stream.index}`"
                :aria-label="t('tracks.source.details', { n: trackNumber(stream) })"
                @click.stop="toggle(stream)"
              >
                <ChevronRight class="track-table__chevron" :size="16" aria-hidden="true" />
                <span aria-hidden="true">{{ trackNumber(stream) }}</span>
              </button>
            </td>
            <td><LanguageChip :tag="streamLanguage(stream)" /></td>
            <td class="track-table__name">{{ stream.title || '—' }}</td>
            <template v-if="stream.kind === 'audio'">
              <td><CodecLabel :stream="stream" /></td>
              <td>{{ channelsText(stream) ?? '—' }}</td>
              <td class="track-table__nowrap">{{ rateDepth(stream) ?? '—' }}</td>
              <td class="track-table__bitrate" :data-source="stream.bitrate?.source ?? 'unknown'">
                <template v-if="stream.bitrate?.value">
                  <span v-tooltip.top="bitrateHelp(stream.bitrate!.source)">
                    {{ t('tracks.units.kbps', { value: kbps(stream.bitrate!.value!) }) }}
                  </span>
                  <span class="track-table__muted">
                    {{ bitrateSource(stream.bitrate!.source) }}
                  </span>
                </template>
                <span v-else class="track-table__unknown">
                  <span v-tooltip.top="bitrateHelp(undefined)">
                    <span aria-hidden="true">—</span>
                    <span class="rf-sr-only">{{ t('tracks.source.bitrateFrom.unknown') }}</span>
                  </span>
                  <ScanControl
                    v-if="scanSource !== null"
                    :run="runOf('bitrate', stream)"
                    :label="t('media.scan.measure')"
                    :start-label="t('media.scan.measureBitrate', { n: trackNumber(stream) })"
                    :progress-label="t('media.scan.measuringBitrate', { n: trackNumber(stream) })"
                    :cancel-label="t('media.scan.cancelBitrate', { n: trackNumber(stream) })"
                    :help="t('media.scan.measureHelp')"
                    data-scan="bitrate"
                    @start="measureBitrate(stream)"
                    @cancel="cancel"
                  />
                </span>
              </td>
            </template>
            <template v-else>
              <td><CodecLabel :stream="stream" /></td>
              <td>{{ typeLabel(stream) }}</td>
              <td class="track-table__events">
                <span class="track-table__unknown">
                  <span v-tooltip.top="eventsHelp(stream)">{{ stream.event_count ?? '—' }}</span>
                  <ScanControl
                    v-if="
                      scanSource !== null &&
                      (stream.event_count === null || stream.event_count === undefined)
                    "
                    :run="runOf('subtitle', stream)"
                    :label="t('media.scan.count')"
                    :start-label="t('media.scan.countTrack', { n: trackNumber(stream) })"
                    :progress-label="t('media.scan.countingTrack', { n: trackNumber(stream) })"
                    :cancel-label="t('media.scan.cancelCountTrack', { n: trackNumber(stream) })"
                    :help="t('media.scan.countHelp')"
                    :disabled="countingAll"
                    data-scan="events"
                    @start="countEvents(stream)"
                    @cancel="cancel"
                  />
                </span>
                <span
                  v-if="
                    stream.forced_event_count !== null && stream.forced_event_count !== undefined
                  "
                  class="track-table__muted"
                  data-forced
                >
                  {{ t('media.events.forced', { count: stream.forced_event_count }) }}
                </span>
              </td>
            </template>
            <td>
              <div class="track-table__roles">
                <RoleBadge
                  v-for="role in stream.roles ?? []"
                  :key="role.role"
                  :role="role"
                  :kind="kind"
                />
                <span
                  v-for="flag in shownFlags(stream)"
                  :key="flag"
                  class="track-table__flag"
                  :data-flag="flag"
                >
                  {{ flagLabel(flag) }}
                </span>
              </div>
            </td>
          </tr>
          <tr
            v-if="expanded.has(stream.index)"
            :id="`${id}-${stream.index}`"
            class="track-table__details"
          >
            <td :colspan="columns">
              <dl class="rf-kv-list">
                <KeyValue :label="t('tracks.details.stream')" :value="`0:${stream.index}`" />
                <KeyValue :label="t('tracks.details.codec')">
                  {{
                    [stream.codec, stream.codec_long, stream.profile].filter(Boolean).join(' · ') ||
                    '—'
                  }}
                </KeyValue>
                <KeyValue
                  :label="t('tracks.details.language')"
                  :value="[stream.language, stream.language_ietf].filter(Boolean).join(' · ')"
                />
                <template v-if="stream.kind === 'audio'">
                  <KeyValue
                    :label="t('tracks.details.layout')"
                    :value="
                      t('tracks.details.layoutValue', {
                        layout: stream.channel_layout ?? '—',
                        channels: stream.channels,
                      })
                    "
                  />
                  <KeyValue :label="t('tracks.details.sampleFormat')" :value="stream.sample_fmt" />
                  <KeyValue
                    :label="t('tracks.details.lossless')"
                    :value="stream.lossless ? t('tracks.details.yes') : t('tracks.details.no')"
                  />
                  <KeyValue :label="t('tracks.details.bitrate')">
                    <template v-if="stream.bitrate?.value">
                      {{ t('tracks.units.kbps', { value: kbps(stream.bitrate!.value!) }) }}
                      ·
                    </template>
                    {{ bitrateHelp(stream.bitrate?.source) }}
                  </KeyValue>
                  <KeyValue :label="t('media.loudness.title')">
                    <dl
                      v-if="loudnessOf(stream)"
                      class="rf-kv-list track-table__loudness"
                      data-loudness
                    >
                      <KeyValue
                        :label="t('media.loudness.integrated')"
                        :value="measured(loudnessOf(stream)!.integrated, 'lufs')"
                      />
                      <KeyValue
                        :label="t('media.loudness.truePeak')"
                        :value="measured(loudnessOf(stream)!.true_peak, 'dbtp')"
                      />
                      <KeyValue
                        :label="t('media.loudness.range')"
                        :value="measured(loudnessOf(stream)!.lra, 'lu')"
                      />
                    </dl>
                    <template v-else-if="scanSource === null">—</template>
                    <ScanControl
                      v-if="scanSource !== null"
                      :run="runOf('loudness', stream)"
                      :label="
                        loudnessOf(stream)
                          ? t('media.scan.measureLoudnessAgain')
                          : t('media.scan.measureLoudness')
                      "
                      :start-label="
                        t('media.scan.measureLoudnessLabel', { n: trackNumber(stream) })
                      "
                      :progress-label="
                        t('media.scan.measuringLoudness', { n: trackNumber(stream) })
                      "
                      :cancel-label="t('media.scan.cancelLoudness', { n: trackNumber(stream) })"
                      :help="t('media.loudness.help')"
                      data-scan="loudness"
                      @start="measureLoudness(stream)"
                      @cancel="cancel"
                    />
                  </KeyValue>
                </template>
                <template v-else>
                  <KeyValue
                    v-if="stream.width && stream.height"
                    :label="t('tracks.details.canvas')"
                    :value="`${stream.width}×${stream.height}`"
                  />
                  <KeyValue :label="t('tracks.details.events')">
                    {{ stream.event_count ?? '—' }}
                    <template v-if="eventsHelp(stream)"> · {{ eventsHelp(stream) }} </template>
                    <!-- The row offers the count while it is unknown; here it counts again (the forced events too). -->
                    <ScanControl
                      v-if="
                        scanSource !== null &&
                        stream.event_count !== null &&
                        stream.event_count !== undefined
                      "
                      class="track-table__detail-scan"
                      :run="runOf('subtitle', stream)"
                      :label="t('media.scan.count')"
                      :start-label="t('media.scan.countTrack', { n: trackNumber(stream) })"
                      :progress-label="t('media.scan.countingTrack', { n: trackNumber(stream) })"
                      :cancel-label="t('media.scan.cancelCountTrack', { n: trackNumber(stream) })"
                      :help="t('media.scan.countHelp')"
                      :disabled="countingAll"
                      data-scan="events"
                      @start="countEvents(stream)"
                      @cancel="cancel"
                    />
                  </KeyValue>
                  <KeyValue
                    v-if="
                      (stream.forced_event_count !== null &&
                        stream.forced_event_count !== undefined) ||
                      hasForcedEvents(stream)
                    "
                    :label="t('tracks.details.forcedEvents')"
                    :value="stream.forced_event_count ?? t('media.events.forcedUnknown')"
                  />
                </template>
                <KeyValue
                  :label="t('tracks.details.delay')"
                  :value="
                    stream.delay === null || stream.delay === undefined
                      ? null
                      : delayText(stream.delay)
                  "
                />
                <KeyValue
                  :label="t('tracks.details.startTime')"
                  :value="seconds(stream.start_time)"
                />
                <KeyValue :label="t('tracks.details.duration')" :value="seconds(stream.duration)" />
                <KeyValue :label="t('tracks.details.frameCount')" :value="stream.frame_count" />
                <KeyValue :label="t('tracks.details.roles')">
                  <ul v-if="(stream.roles ?? []).length > 0" class="track-table__list">
                    <li v-for="role in stream.roles" :key="role.role">
                      <RoleBadge :role="role" :kind="kind" />
                      <span v-if="role.detail" class="track-table__muted">{{ role.detail }}</span>
                    </li>
                  </ul>
                  <template v-else>—</template>
                </KeyValue>
                <KeyValue
                  :label="t('tracks.details.dispositions')"
                  :value="setDispositions(stream).join(', ')"
                />
                <KeyValue :label="t('tracks.details.tags')">
                  <dl v-if="tagsOf(stream).length > 0" class="rf-kv-list track-table__tags">
                    <KeyValue
                      v-for="[key, value] in tagsOf(stream)"
                      :key="key"
                      :label="key"
                      :value="value"
                    />
                  </dl>
                  <template v-else>—</template>
                </KeyValue>
              </dl>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.track-table__empty {
  margin: 0;
  color: var(--rf-color-text-muted);
}

/* Size containment: the table scrolls inside the tab instead of widening it. */
.track-table__scroll {
  contain: inline-size;
  overflow-x: auto;
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md);
}

.track-table__table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--rf-font-size-sm);
}

th {
  padding: var(--rf-space-2) var(--rf-space-1);
  border-bottom: 1px solid var(--rf-color-border);
  color: var(--rf-color-text-muted);
  font-weight: var(--rf-font-weight-medium);
  text-align: start;
  white-space: nowrap;
}

td {
  padding: var(--rf-space-1);
  vertical-align: middle;
}

tbody + tbody .track-table__row td {
  border-top: 1px solid var(--rf-color-border);
}

.track-table__row {
  cursor: pointer;
}

.track-table__row:hover {
  background: var(--rf-color-surface-hover);
}

.track-table__toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
  padding: var(--rf-space-1);
  border: 0;
  border-radius: var(--rf-radius-sm);
  background: none;
  color: inherit;
  font: inherit;
  font-weight: var(--rf-font-weight-bold);
  cursor: pointer;
}

.track-table__toggle:focus-visible {
  outline: 2px solid var(--rf-color-primary);
  outline-offset: 1px;
}

.track-table__chevron {
  transition: transform var(--rf-duration) ease;
}

.track-table__row--open .track-table__chevron {
  transform: rotate(90deg);
}

.track-table__name {
  min-width: 6rem;
  overflow-wrap: break-word;
}

.track-table__nowrap {
  white-space: nowrap;
}

.track-table__bitrate {
  white-space: nowrap;
}

.track-table__bitrate > span {
  display: block;
}

.track-table__table .track-table__unknown {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.track-table__events {
  white-space: nowrap;
}

.track-table__events > span {
  display: block;
}

.track-table__actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: var(--rf-space-2);
}

.track-table__detail-scan {
  margin-inline-start: var(--rf-space-2);
}

.track-table__loudness {
  margin-bottom: var(--rf-space-1);
}

.track-table__muted {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
}

.track-table__roles {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-1);
  min-width: 6rem;
}

.track-table__flag {
  padding: 0 var(--rf-space-2);
  border-radius: var(--rf-radius-sm);
  background: var(--p-status-info-background);
  color: var(--p-status-info-color);
  font-size: var(--rf-font-size-xs);
  line-height: 1.5rem;
  white-space: nowrap;
}

.track-table__details td {
  padding: var(--rf-space-2) var(--rf-space-3) var(--rf-space-3) var(--rf-space-6);
  background: var(--rf-color-bg);
}

.track-table__list {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.track-table__list li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
}

.track-table__tags {
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-xs);
}
</style>
