<script setup lang="ts">
import { useElementSize } from '@vueuse/core'
import { computed, nextTick, ref, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { useLanguageColor } from '@/components/base/languageColor'
import LanguageChip from '@/components/base/LanguageChip.vue'
import { rangeSpan } from '@/components/range/range'
import { useRange } from '@/components/range/useRange'
import { useJobSource } from '@/components/summary/useJobSource'
import { useEditorStore } from '@/stores/editor'
import { usePreviewStore } from '@/stores/preview'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'

import {
  buildLanes,
  chapterSegments,
  clockText,
  type Lane,
  percentAt,
  ticks,
  tickStep,
} from './programme'

/** `docked`: at the top of the editor column, where the preview is collapsed. */
const props = defineProps<{ docked?: boolean }>()

/** More lanes than this make the lanes thinner and scroll inside the strip. */
const ROOMY_LANES = 8

const { t } = useI18n()
const editor = useEditorStore()
const preview = usePreviewStore()
const system = useSystemStore()
const ui = useUiStore()
const colorOf = useLanguageColor()
const { source } = useJobSource()
const { label: rangeLabel } = useRange()
const headingId = useId()

const duration = computed(() => {
  const seconds = source.value?.container?.duration ?? source.value?.video?.[0]?.duration ?? null
  return seconds !== null && Number.isFinite(seconds) && seconds > 0 ? seconds : null
})
/** Shorter than a minute: times show tenths of a second. */
const fine = computed(() => duration.value !== null && duration.value < 60)
const clock = (seconds: number) => clockText(seconds, fine.value)

const lanes = computed<Lane[]>(() =>
  editor.job === null
    ? []
    : buildLanes(editor.job, source.value, {
        definitions: system.definitions,
        languages: system.languages,
        colorOf,
        passthru: t('summary.tracks.passthru'),
      }),
)
const audioCount = computed(() => lanes.value.filter((lane) => lane.kind === 'audio').length)
const compact = computed(() => lanes.value.length > ROOMY_LANES)

const segments = computed(() => chapterSegments(editor.job, source.value, duration.value))

/** The encoded part, in seconds; the whole programme when the source does not say. */
const span = computed(() => {
  const total = duration.value
  if (total === null) return null
  const found = rangeSpan(editor.range, source.value)
  const start = Math.min(total, Math.max(0, found?.start ?? 0))
  const end = Math.min(total, Math.max(start, found?.end ?? total))
  return { start, end, whole: start <= 0 && end >= total }
})

function at(seconds: number): string {
  return `${percentAt(seconds, duration.value ?? 0)}%`
}

const track = useTemplateRef<HTMLElement>('track')
const { width: trackWidth } = useElementSize(track)

const rulerTicks = computed(() => {
  const total = duration.value
  if (total === null) return []
  const longest = clock(total).length
  // About 0.6em per mono character at the ruler's 0.6875rem, with room between two labels.
  const room = trackWidth.value > 0 ? trackWidth.value / ((longest + 3) * 7) : 6
  const step = tickStep(total, room)
  return ticks(total, step).map((tick) =>
    Object.assign(tick, { label: clockText(tick.seconds, step < 1) }),
  )
})

/** A chapter narrower than this many pixels shows no number. */
const NUMBER_ROOM = 18

function numbered(start: number, end: number): boolean {
  const total = duration.value
  if (total === null || trackWidth.value === 0) return true
  return ((end - start) / total) * trackWidth.value >= NUMBER_ROOM
}

/** A point (`end` left out) on an end of the range is inside it; a chapter that only touches it is not. */
function outside(start: number, end?: number): boolean {
  const range = span.value
  if (range === null) return false
  if (end === undefined) return start < range.start || start > range.end
  return end <= range.start || start >= range.end
}

const playhead = computed(() => {
  const frame = preview.current
  const total = duration.value
  if (frame === null || total === null) return null
  return { seconds: frame.timestamp, left: at(frame.timestamp) }
})

const header = computed(() => {
  const parts: string[] = []
  if (duration.value !== null) {
    parts.push(t('strip.span', { start: clock(0), end: clock(duration.value) }))
  }
  if (segments.value.length > 0) parts.push(t('strip.chapters', segments.value.length))
  parts.push(t('strip.lanes', lanes.value.length))
  return parts.join(' · ')
})

const spanText = computed(() => {
  const range = span.value
  if (range === null || range.whole) return t('strip.describe.whole')
  return t('strip.describe.range', { start: clock(range.start), end: clock(range.end) })
})

// The labels are mono at 0.6875rem: a character is 0.6em wide.
const gutter = computed(() => {
  const longest = Math.max(
    4,
    ...lanes.value.map(
      (lane) => laneLabel(lane).length + 1 + lane.code.length + (lane.forcedOnly ? 2 : 0),
    ),
  )
  return `calc(${longest} * 0.4125rem + 0.25rem)`
})

function laneLabel(lane: Lane): string {
  return t(lane.kind === 'audio' ? 'strip.lane.audio' : 'strip.lane.subtitle', { n: lane.number })
}

function describe(lane: Lane): string {
  const extras = [
    lane.commentary ? t('strip.describe.commentary') : null,
    lane.burn ? t('strip.describe.burn') : null,
    lane.forcedOnly ? t('strip.describe.forcedOnly') : null,
  ].filter((extra): extra is string => extra !== null)
  const format = [lane.format, ...extras].filter(Boolean).join(', ')
  return t(lane.kind === 'audio' ? 'strip.describe.audio' : 'strip.describe.subtitle', {
    n: lane.number,
    language: lane.languageName ?? t('strip.describe.undetermined'),
    format,
    span: spanText.value,
  })
}

const programmeText = computed(() => {
  const total = duration.value
  const parts = [
    total === null
      ? t('strip.unknown')
      : t('strip.describe.programme', {
          start: clock(0),
          end: clock(total),
          range: rangeLabel.value,
        }),
  ]
  if (segments.value.length > 0) parts.push(t('strip.describe.chapters', segments.value.length))
  return parts.join(' ')
})

/** One legend entry per language, in lane order. */
const languages = computed(() => {
  const seen = new Map<string, string | null>()
  for (const lane of lanes.value) if (!seen.has(lane.code)) seen.set(lane.code, lane.language)
  return [...seen].map(([code, tag]) => ({ code, tag }))
})
const hasBurn = computed(() => lanes.value.some((lane) => lane.burn))
const hasForced = computed(() => lanes.value.some((lane) => lane.forcedOnly))

// Each group is one Tab stop: the arrow keys move inside it.
const laneStop = ref(0)
watch(
  () => lanes.value.length,
  (count) => {
    if (laneStop.value >= count) laneStop.value = Math.max(0, count - 1)
  },
)
const laneButtons = useTemplateRef<HTMLButtonElement[]>('laneButtons')

function moveLane(event: KeyboardEvent, from: number): void {
  const last = lanes.value.length - 1
  const to =
    event.key === 'ArrowDown'
      ? Math.min(last, from + 1)
      : event.key === 'ArrowUp'
        ? Math.max(0, from - 1)
        : event.key === 'Home'
          ? 0
          : event.key === 'End'
            ? last
            : null
  if (to === null) return
  event.preventDefault()
  laneStop.value = to
  laneButtons.value?.[to]?.focus()
}

const frameStop = computed(() =>
  Math.min(preview.index ?? 0, Math.max(0, preview.strip.length - 1)),
)
const frameButtons = useTemplateRef<HTMLButtonElement[]>('frameButtons')

async function moveFrame(event: KeyboardEvent, from: number): Promise<void> {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
  const last = preview.strip.length - 1
  const to =
    event.key === 'ArrowRight'
      ? Math.min(last, from + 1)
      : event.key === 'ArrowLeft'
        ? Math.max(0, from - 1)
        : event.key === 'Home'
          ? 0
          : event.key === 'End'
            ? last
            : null
  if (to === null) return
  event.preventDefault()
  preview.select(to)
  await nextTick()
  frameButtons.value?.[to]?.focus()
}
</script>

<template>
  <section
    v-if="editor.job !== null"
    class="programme-strip"
    :class="{ 'programme-strip--docked': props.docked, 'programme-strip--compact': compact }"
    :aria-labelledby="headingId"
    :style="{ '--strip-gutter': gutter }"
    data-component="programme-strip"
    :data-docked="props.docked ? 'true' : undefined"
  >
    <header class="programme-strip__header">
      <component :is="props.docked ? 'h2' : 'h3'" :id="headingId" class="programme-strip__title">
        {{ t('strip.title') }}
      </component>
      <span class="programme-strip__facts rf-mono" data-field="programme-facts">{{ header }}</span>
    </header>

    <p v-if="duration === null" class="programme-strip__note" data-state="unknown">
      {{ t('strip.unknown') }}
    </p>

    <div class="programme-strip__body">
      <div v-if="span !== null" class="programme-strip__backdrop" aria-hidden="true">
        <span
          class="programme-strip__range"
          data-layer="range"
          :style="{ left: at(span.start), width: `calc(${at(span.end)} - ${at(span.start)})` }"
        />
      </div>

      <div v-if="duration !== null" class="programme-strip__row" aria-hidden="true">
        <span class="programme-strip__gutter" />
        <div ref="track" class="programme-strip__track programme-strip__ruler" data-row="ruler">
          <template v-for="tick in rulerTicks" :key="tick.seconds">
            <span
              class="programme-strip__tick"
              :class="{ 'programme-strip__tick--minor': !tick.major }"
              :style="{ left: at(tick.seconds) }"
            />
            <span
              v-if="tick.major"
              class="programme-strip__tick-label rf-mono"
              :class="{
                'programme-strip__tick-label--end': percentAt(tick.seconds, duration) > 94,
              }"
              :style="{ left: at(tick.seconds) }"
              data-field="tick"
              >{{ tick.label }}</span
            >
          </template>
          <template v-if="span !== null && !span.whole">
            <span class="programme-strip__bracket" :style="{ left: at(span.start) }" />
            <span
              class="programme-strip__bracket programme-strip__bracket--end"
              :style="{ left: at(span.end) }"
            />
          </template>
        </div>
      </div>

      <div
        v-if="duration !== null && segments.length > 0"
        class="programme-strip__row"
        aria-hidden="true"
        data-row="chapters"
      >
        <span class="programme-strip__gutter rf-mono">{{ t('strip.row.chapters') }}</span>
        <div class="programme-strip__track">
          <span
            v-for="segment in segments"
            :key="segment.number"
            class="programme-strip__chapter rf-mono"
            :class="{ 'is-outside': outside(segment.start, segment.end) }"
            :style="{
              left: at(segment.start),
              width: `calc(${at(segment.end)} - ${at(segment.start)})`,
            }"
            :title="segment.title ?? undefined"
            data-field="chapter"
            >{{ numbered(segment.start, segment.end) ? segment.number : '' }}</span
          >
        </div>
      </div>

      <div
        v-if="duration !== null && preview.strip.length > 0"
        class="programme-strip__row"
        data-row="frames"
      >
        <span class="programme-strip__gutter rf-mono" aria-hidden="true">{{
          t('strip.row.frames')
        }}</span>
        <div class="programme-strip__track" role="group" :aria-label="t('strip.frames')">
          <button
            v-for="(frame, index) in preview.strip"
            ref="frameButtons"
            :key="frame.key"
            type="button"
            class="programme-strip__dot"
            :class="{
              'is-current': index === preview.index,
              'is-outside': outside(frame.timestamp),
            }"
            :style="{ left: at(frame.timestamp) }"
            :tabindex="index === frameStop ? 0 : -1"
            :aria-label="t('strip.frame', { time: clock(frame.timestamp) })"
            :aria-current="index === preview.index ? 'true' : undefined"
            data-field="frame-dot"
            @click="preview.select(index)"
            @keydown="moveFrame($event, index)"
          />
        </div>
      </div>

      <div
        v-if="lanes.length > 0"
        class="programme-strip__lanes"
        role="group"
        :aria-label="t('strip.lanesLabel')"
        data-row="lanes"
      >
        <button
          v-for="(lane, index) in lanes"
          ref="laneButtons"
          :key="lane.path"
          type="button"
          class="programme-strip__lane"
          :class="{
            'programme-strip__lane--first-subtitle':
              lane.kind === 'subtitle' && lane.number === 1 && audioCount > 0,
          }"
          :tabindex="index === laneStop ? 0 : -1"
          :aria-describedby="`${headingId}-lane-${index}`"
          :data-path="lane.path"
          data-field="lane"
          @click="ui.reveal(lane.path)"
          @focus="laneStop = index"
          @keydown="moveLane($event, index)"
        >
          <span class="programme-strip__gutter programme-strip__lane-label rf-mono">
            {{ laneLabel(lane) }} {{ lane.code }}
            <span v-if="lane.forcedOnly" class="programme-strip__forced">{{
              t('strip.lane.forced')
            }}</span>
          </span>
          <span class="programme-strip__track">
            <span
              class="programme-strip__bar"
              :class="{ 'is-pale': lane.commentary, 'is-burn': lane.burn }"
              :style="{
                '--lane-color': lane.color,
                left: span === null ? '0%' : at(span.start),
                width: span === null ? '100%' : `calc(${at(span.end)} - ${at(span.start)})`,
              }"
              data-field="bar"
            />
          </span>
        </button>
      </div>

      <div v-if="playhead !== null" class="programme-strip__front" aria-hidden="true">
        <span class="programme-strip__playhead" :style="{ left: playhead.left }" />
      </div>
    </div>

    <div
      v-if="playhead !== null"
      class="programme-strip__row programme-strip__foot"
      aria-hidden="true"
    >
      <span class="programme-strip__gutter" />
      <div class="programme-strip__track">
        <span
          class="programme-strip__time rf-mono"
          :class="{
            'is-start': percentAt(playhead.seconds, duration ?? 0) < 8,
            'is-end': percentAt(playhead.seconds, duration ?? 0) > 92,
          }"
          :style="{ left: playhead.left }"
          data-field="playhead"
          >{{ clock(playhead.seconds) }}</span
        >
      </div>
    </div>

    <ul
      v-if="lanes.length > 0"
      class="programme-strip__legend"
      :aria-label="t('strip.legend.label')"
    >
      <li v-for="language in languages" :key="language.code">
        <LanguageChip :tag="language.tag" />
      </li>
      <li class="programme-strip__key">{{ t('strip.legend.pale') }}</li>
      <li v-if="hasBurn" class="programme-strip__key">{{ t('strip.legend.outline') }}</li>
      <li v-if="hasForced" class="programme-strip__key">{{ t('strip.legend.forced') }}</li>
    </ul>

    <ul class="rf-sr-only" data-field="programme-text">
      <li>{{ programmeText }}</li>
      <li v-for="(lane, index) in lanes" :id="`${headingId}-lane-${index}`" :key="lane.path">
        {{ describe(lane) }}
      </li>
    </ul>
  </section>
</template>

<style scoped>
.programme-strip {
  --strip-gap: var(--rf-space-2);
  /* A lane is a button: never under the 24 px target size. */
  --strip-lane: max(1.5rem, 24px);
  --strip-bar: 0.625rem;
  --strip-ink: var(--rf-color-text);
  --strip-ground: var(--rf-color-booth);

  display: grid;
  gap: var(--rf-space-2);
  min-width: 0;
  color: var(--rf-color-text);
}

.programme-strip--docked {
  --strip-ground: var(--rf-color-surface);
  /* Above the track editor: a short window leaves the editor most of the height. */
  --strip-lanes-height: min(calc(var(--strip-lane) * 8), max(calc(var(--strip-lane) * 3), 18vh));
}

.programme-strip--compact {
  --strip-bar: 0.375rem;
}

.programme-strip__header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0 var(--rf-space-3);
}

.programme-strip__title {
  margin: 0;
  font-size: var(--rf-text-subheading);
  font-weight: var(--rf-font-weight-bold);
  line-height: var(--rf-line-height-tight);
}

.programme-strip__facts {
  margin-inline-start: auto;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
  text-align: end;
}

.programme-strip__note {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.programme-strip__body {
  position: relative;
  display: grid;
}

.programme-strip__row,
.programme-strip__lane {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: var(--strip-gutter) minmax(0, 1fr);
  column-gap: var(--strip-gap);
  align-items: center;
}

.programme-strip__gutter {
  overflow: hidden;
  color: var(--rf-color-text-muted);
  font-family: var(--rf-font-mono);
  font-size: 0.6875rem;
  white-space: nowrap;
}

.programme-strip__track {
  position: relative;
  height: 100%;
}

/* The backdrop and the playhead lie over the time column of every row. */
.programme-strip__backdrop,
.programme-strip__front {
  position: absolute;
  inset-block: 0;
  inset-inline: calc(var(--strip-gutter) + var(--strip-gap)) 0;
  pointer-events: none;
}

.programme-strip__front {
  z-index: 2;
}

.programme-strip__range {
  position: absolute;
  inset-block: 1.5rem 0;
  background: color-mix(in srgb, var(--strip-ink) 5%, transparent);
}

.programme-strip__ruler {
  height: 1.5rem;
  border-bottom: 1px solid var(--rf-color-text-muted);
}

.programme-strip__tick {
  position: absolute;
  bottom: 0;
  width: 1px;
  height: 0.4375rem;
  background: var(--rf-color-text-muted);
  transform: translateX(-50%);
}

.programme-strip__tick--minor {
  height: 0.1875rem;
}

.programme-strip__tick-label {
  position: absolute;
  top: 0;
  color: var(--rf-color-text-muted);
  font-size: 0.6875rem;
  line-height: 1;
  white-space: nowrap;
  transform: translateX(-50%);
}

.programme-strip__tick-label--end {
  transform: translateX(-100%);
}

/* The range's ends on the ruler: a bracket each, facing inwards. */
.programme-strip__bracket {
  position: absolute;
  bottom: -1px;
  width: 0.25rem;
  height: 0.625rem;
  border: solid var(--strip-ink);
  border-width: 0 0 2px 2px;
}

.programme-strip__bracket--end {
  border-width: 0 2px 2px 0;
  transform: translateX(-100%);
}

[data-row='chapters'] .programme-strip__track {
  height: 1.125rem;
  margin-block-start: var(--rf-space-1);
}

.programme-strip__chapter {
  position: absolute;
  inset-block: 0;
  display: grid;
  place-items: center;
  overflow: hidden;
  border-inline-end: 2px solid var(--strip-ground);
  background: var(--p-content-hover-background);
  color: var(--rf-color-text-muted);
  font-size: 0.6875rem;
}

.programme-strip__chapter:last-child {
  border-inline-end: none;
}

.is-outside {
  opacity: 0.45;
}

[data-row='frames'] .programme-strip__track {
  height: 1.5rem;
}

.programme-strip__dot {
  position: absolute;
  top: 0;
  display: grid;
  place-items: center;
  width: 1.5rem;
  height: 1.5rem;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  cursor: pointer;
  transform: translateX(-50%);
}

.programme-strip__dot::before {
  content: '';
  width: 0.3125rem;
  height: 0.3125rem;
  border-radius: 50%;
  background: var(--rf-color-text-muted);
}

.programme-strip__dot:hover::before {
  background: var(--strip-ink);
}

.programme-strip__dot.is-current {
  z-index: 1;
}

.programme-strip__dot.is-current::before {
  width: 0.625rem;
  height: 0.625rem;
  background: var(--strip-ink);
  box-shadow: 0 0 0 2px var(--strip-ground);
}

.programme-strip__dot:focus-visible,
.programme-strip__lane:focus-visible {
  outline: 2px solid var(--p-focus-ring-color, var(--rf-color-primary));
  outline-offset: -2px;
}

.programme-strip__lanes {
  position: relative;
  z-index: 1;
  display: grid;
  max-height: var(--strip-lanes-height, calc(var(--strip-lane) * 8));
  overflow-y: auto;
  overscroll-behavior: contain;
}

.programme-strip__lane {
  width: 100%;
  height: var(--strip-lane);
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: var(--rf-radius-sm);
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: start;
  cursor: pointer;
}

.programme-strip__lane:hover {
  background: var(--rf-color-surface-hover);
}

/* Audio and subtitles are two groups: a hairline between them. */
.programme-strip__lane--first-subtitle {
  margin-block-start: var(--rf-space-1);
}

.programme-strip__lane--first-subtitle::before {
  content: '';
  position: absolute;
  inset-block-start: calc(-1 * var(--rf-space-1) / 2);
  inset-inline: calc(var(--strip-gutter) + var(--strip-gap)) 0;
  border-top: 1px solid var(--rf-color-border);
}

.programme-strip__lane-label {
  color: var(--rf-color-text);
  padding-inline-start: 1px;
}

.programme-strip__forced {
  padding: 0 0.2em;
  border: 1px solid currentcolor;
  border-radius: 2px;
  font-size: 0.5625rem;
  vertical-align: 0.1em;
}

.programme-strip__lane .programme-strip__track {
  display: block;
}

.programme-strip__bar {
  position: absolute;
  top: 50%;
  height: var(--strip-bar);
  border-radius: 1px;
  background: var(--lane-color);
  transform: translateY(-50%);
}

.programme-strip__bar.is-pale {
  opacity: var(--rf-lang-pale);
}

/* Burned into the picture: no track of its own in the output, so only its outline. */
.programme-strip__bar.is-burn {
  border: 2px solid var(--lane-color);
  background: transparent;
}

.programme-strip__playhead {
  position: absolute;
  inset-block: 0.875rem 0;
  width: 2px;
  background: var(--strip-ink);
  transform: translateX(-50%);
}

.programme-strip__foot .programme-strip__track {
  height: 1.125rem;
}

.programme-strip__time {
  position: absolute;
  top: 0;
  padding: 0 0.3125rem;
  border-radius: var(--rf-radius-sm);
  background: var(--strip-ink);
  color: var(--strip-ground);
  font-size: 0.6875rem;
  line-height: 1.125rem;
  white-space: nowrap;
  transform: translateX(-50%);
}

.programme-strip__time.is-start {
  transform: translateX(-0.5rem);
}

.programme-strip__time.is-end {
  transform: translateX(calc(-100% + 0.5rem));
}

.programme-strip__legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0 var(--rf-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.programme-strip__legend :deep(.rf-language-chip) {
  font-size: var(--rf-font-size-xs);
}

.programme-strip__key {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
  line-height: 1.5rem;
}
</style>
