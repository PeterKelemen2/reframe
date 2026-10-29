<script setup lang="ts">
import InputNumber from 'primevue/inputnumber'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import Slider from 'primevue/slider'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { AudioOutputTrack, AudioStream } from '@/api/types'
import Field from '@/components/base/Field.vue'
import { kiloHertz, streamLabel } from '@/components/media/streams'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'

import {
  bitrateChoices,
  bitrateTable,
  canCopy,
  containerDef,
  DEFAULT_AUDIO_ENCODER,
  encoderChangeOps,
  type Mixdown,
  mixdownChangeOps,
  rateModeOps,
  sourceChangeOps,
} from './ops'
import TrackRowFrame from './TrackRowFrame.vue'

const props = defineProps<{
  index: number
  count: number
  track: AudioOutputTrack
  /** The source's audio tracks; empty while the source is not known. */
  streams: readonly AudioStream[]
}>()

const emit = defineEmits<{ move: [to: number]; remove: [] }>()

const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()

// Select shows its placeholder for a `null` value, so "keep" and "default" are named values.
const KEEP = 'keep'
const DEFAULT = 'default'

const path = computed(() => `audio[${props.index}]`)
const base = computed(() => `/audio/${props.index}`)

const definitions = computed(() => system.definitions)
const stream = computed(() =>
  props.streams.find((candidate) => candidate.index === props.track.source_stream),
)
const channels = computed(() => stream.value?.channels ?? 0)
const encoderId = computed(() => props.track.encoder ?? DEFAULT_AUDIO_ENCODER)
const encoder = computed(() => definitions.value?.audio_encoders?.[encoderId.value])
const passthru = computed(() => props.track.action === 'passthru')
/** A passthru track the container holds is copied: no encoder setting applies to it. */
const copied = computed(
  () =>
    passthru.value &&
    canCopy(
      containerDef(definitions.value, editor.job?.output?.container)?.audio,
      stream.value?.codec,
    ),
)

const sourceOptions = computed(() =>
  props.streams.map((candidate) => ({ value: candidate.index, label: streamLabel(candidate) })),
)
const sourcePlaceholder = computed(() =>
  props.track.source_stream === null || props.track.source_stream === undefined
    ? t('tracks.output.noSource')
    : t('tracks.output.missingStream', { index: props.track.source_stream }),
)

function onSource(index: number): void {
  const next = props.streams.find((candidate) => candidate.index === index)
  if (next && index !== props.track.source_stream) {
    editor.patch(sourceChangeOps('audio', props.index, props.track, next))
  }
}

const actionOptions = computed(() => [
  { value: 'passthru', label: t('tracks.output.passthru') },
  { value: 'encode', label: t('tracks.output.encode') },
])

function onAction(action: AudioOutputTrack['action'] | null): void {
  if (action && action !== props.track.action) editor.set(`${base.value}/action`, action)
}

const encoderOptions = computed(() =>
  Object.values(definitions.value?.audio_encoders ?? {})
    .filter(
      (candidate) =>
        candidate.id === props.track.encoder ||
        system.encoderStatus(candidate.id)?.state !== 'unavailable',
    )
    .map((candidate) => ({ value: candidate.id, label: candidate.label })),
)

function onEncoder(id: string): void {
  if (id === props.track.encoder) return
  editor.patch(encoderChangeOps(props.index, props.track, id, definitions.value, channels.value))
}

const mixdownOptions = computed(() => [
  { value: KEEP, label: t('tracks.output.keepLayout') },
  ...(encoder.value?.mixdowns ?? (Object.keys(definitions.value?.mixdowns ?? {}) as Mixdown[])).map(
    (mixdown) => ({
      value: mixdown,
      label: definitions.value?.mixdowns?.[mixdown]?.label ?? mixdown,
    }),
  ),
])

function onMixdown(value: string): void {
  const mixdown = value === KEEP ? null : (value as Mixdown)
  if (mixdown === (props.track.mixdown ?? null)) return
  editor.patch(
    mixdownChangeOps(props.index, props.track, mixdown, definitions.value, channels.value),
  )
}

const samplerateOptions = computed(() => [
  { value: KEEP, label: t('tracks.output.sameAsSource') },
  ...(encoder.value?.samplerates ?? []).map((rate) => ({
    value: String(rate),
    label: t('tracks.units.khz', { value: kiloHertz(rate) }),
  })),
])

function onSamplerate(value: string): void {
  editor.set(`${base.value}/samplerate`, value === KEEP ? null : Number(value))
}

const lossless = computed(() => encoder.value?.lossless === true || !encoder.value?.bitrate)
const rateMode = computed<'bitrate' | 'quality'>(() =>
  props.track.bitrate == null && props.track.quality != null ? 'quality' : 'bitrate',
)
const rateModeOptions = computed(() => [
  { value: 'bitrate', label: t('tracks.output.bitrate') },
  { value: 'quality', label: t('tracks.output.quality') },
])

function onRateMode(mode: 'bitrate' | 'quality' | null): void {
  if (mode && mode !== rateMode.value) editor.patch(rateModeOps(props.index, mode, encoder.value))
}

/** The paths of the fields shown: an issue elsewhere in the track is listed under the row. */
const fieldPaths = computed(() => {
  const fields = [
    'source_stream',
    'action',
    'encoder',
    'mixdown',
    'samplerate',
    'gain',
    'drc',
    'loudness',
  ]
  if (!lossless.value)
    fields.push(rateMode.value === 'quality' && encoder.value?.quality ? 'quality' : 'bitrate')
  return fields.map((field) => `${path.value}.${field}`)
})

const limits = computed(() => bitrateTable(encoder.value, props.track.mixdown, channels.value))
const bitrateOptions = computed(() => [
  {
    value: DEFAULT,
    label:
      limits.value === null
        ? t('tracks.output.encoderDefault')
        : t('tracks.output.defaultBitrate', { value: limits.value.default }),
  },
  ...bitrateChoices(encoder.value, limits.value, props.track.bitrate).map((value) => ({
    value: String(value),
    label: t('tracks.units.kbps', { value }),
  })),
])

function onBitrate(value: string): void {
  editor.set(`${base.value}/bitrate`, value === DEFAULT ? null : Number(value))
}

function onQuality(value: number | null): void {
  if (value === null) return
  editor.set(`${base.value}/quality`, value, { coalesce: `${path.value}.quality` })
}

function onGain(value: number | null): void {
  if (value === null) return
  editor.set(`${base.value}/gain`, value, { coalesce: `${path.value}.gain` })
}

function onDrc(value: number | number[]): void {
  const drc = Array.isArray(value) ? (value[0] ?? 0) : value
  editor.set(`${base.value}/drc`, drc, { coalesce: `${path.value}.drc` })
}

const loudnessOptions = computed(() => [
  { value: 'off', label: t('tracks.output.loudnessOff') },
  { value: 'ebu_r128', label: t('tracks.output.loudnessEbu') },
  { value: 'streaming', label: t('tracks.output.loudnessStreaming') },
])

function onLoudness(value: AudioOutputTrack['loudness']): void {
  editor.set(`${base.value}/loudness`, value)
}
</script>

<template>
  <TrackRowFrame
    :path="path"
    :index="index"
    :count="count"
    :field-paths="fieldPaths"
    @move="(to) => emit('move', to)"
    @remove="emit('remove')"
  >
    <template #header>
      <Field :label="t('tracks.output.source')" :path="`${path}.source_stream`" stacked>
        <template #default="{ id, invalid }">
          <Select
            :input-id="id"
            class="track-field__control"
            :model-value="stream ? track.source_stream : null"
            :options="sourceOptions"
            option-label="label"
            option-value="value"
            :placeholder="sourcePlaceholder"
            :disabled="streams.length === 0"
            :invalid="invalid"
            @update:model-value="onSource"
          />
        </template>
      </Field>
    </template>
    <p v-if="copied" class="track-fields__note" data-note="copied">
      {{ t('tracks.output.copied', { codec: stream?.display_codec || stream?.codec || '' }) }}
    </p>
    <div class="track-fields">
      <Field
        class="track-field--fit"
        :label="t('tracks.output.action')"
        :path="`${path}.action`"
        stacked
      >
        <template #default="{ id, invalid, labelId }">
          <SelectButton
            :pt="{ root: { id } }"
            :model-value="track.action"
            :options="actionOptions"
            option-label="label"
            option-value="value"
            :allow-empty="false"
            :invalid="invalid"
            :ariaLabelledby="labelId"
            @update:model-value="onAction"
          />
        </template>
      </Field>
      <Field
        :label="passthru ? t('tracks.output.fallbackEncoder') : t('tracks.output.encoder')"
        :path="`${path}.encoder`"
        :help="passthru ? t('tracks.output.fallbackHelp') : undefined"
        stacked
      >
        <template #default="{ id, invalid }">
          <Select
            :input-id="id"
            class="track-field__control"
            :model-value="track.encoder"
            :options="encoderOptions"
            option-label="label"
            option-value="value"
            :placeholder="t('tracks.output.presetFallback')"
            :invalid="invalid"
            @update:model-value="onEncoder"
          />
        </template>
      </Field>
      <Field :label="t('tracks.output.mixdown')" :path="`${path}.mixdown`" stacked>
        <template #default="{ id, invalid }">
          <Select
            :input-id="id"
            class="track-field__control"
            :model-value="track.mixdown ?? KEEP"
            :options="mixdownOptions"
            option-label="label"
            option-value="value"
            :disabled="copied"
            :invalid="invalid"
            @update:model-value="onMixdown"
          />
        </template>
      </Field>
      <Field :label="t('tracks.output.samplerate')" :path="`${path}.samplerate`" stacked>
        <template #default="{ id, invalid }">
          <Select
            :input-id="id"
            class="track-field__control"
            :model-value="track.samplerate ? String(track.samplerate) : KEEP"
            :options="samplerateOptions"
            option-label="label"
            option-value="value"
            :disabled="copied"
            :invalid="invalid"
            @update:model-value="onSamplerate"
          />
        </template>
      </Field>
      <div v-if="lossless" class="track-field__static" data-note="lossless">
        <span class="track-field__static-label">{{ t('tracks.output.bitrate') }}</span>
        <span>{{ t('tracks.output.lossless') }}</span>
      </div>
      <template v-else>
        <Field
          v-if="encoder?.quality"
          class="track-field--fit"
          :label="t('tracks.output.rateMode')"
          stacked
        >
          <template #default="{ id, labelId }">
            <SelectButton
              :pt="{ root: { id } }"
              :model-value="rateMode"
              :options="rateModeOptions"
              option-label="label"
              option-value="value"
              :allow-empty="false"
              :disabled="copied"
              :ariaLabelledby="labelId"
              @update:model-value="onRateMode"
            />
          </template>
        </Field>
        <Field
          v-if="rateMode === 'quality' && encoder?.quality"
          :label="t('tracks.output.quality')"
          :path="`${path}.quality`"
          :help="encoder.quality.help || undefined"
          stacked
        >
          <template #default="{ id, invalid }">
            <InputNumber
              :input-id="id"
              class="track-field__number"
              :model-value="track.quality ?? encoder.quality.default"
              :min="encoder.quality.min"
              :max="encoder.quality.max"
              :step="encoder.quality.step"
              :min-fraction-digits="0"
              :max-fraction-digits="2"
              show-buttons
              :disabled="copied"
              :invalid="invalid"
              @update:model-value="onQuality"
              @blur="editor.endCoalescing()"
            />
          </template>
        </Field>
        <Field v-else :label="t('tracks.output.bitrate')" :path="`${path}.bitrate`" stacked>
          <template #default="{ id, invalid }">
            <Select
              :input-id="id"
              class="track-field__control"
              :model-value="track.bitrate ? String(track.bitrate) : DEFAULT"
              :options="bitrateOptions"
              option-label="label"
              option-value="value"
              :disabled="copied"
              :invalid="invalid"
              @update:model-value="onBitrate"
            />
          </template>
        </Field>
      </template>
      <Field :label="t('tracks.output.gain')" :path="`${path}.gain`" stacked>
        <template #default="{ id, invalid }">
          <InputNumber
            :input-id="id"
            class="track-field__number"
            :model-value="track.gain"
            :min="-20"
            :max="20"
            :step="1"
            :max-fraction-digits="1"
            :suffix="t('tracks.units.dbSuffix')"
            show-buttons
            :disabled="copied"
            :invalid="invalid"
            @update:model-value="onGain"
            @blur="editor.endCoalescing()"
          />
        </template>
      </Field>
      <Field
        :label="t('tracks.output.drc')"
        :path="`${path}.drc`"
        :help="t('tracks.output.drcHelp')"
        stacked
      >
        <template #default="{ id, labelId }">
          <div class="track-field__slider" @focusout="editor.endCoalescing()">
            <Slider
              :pt="{ handle: { id } }"
              :model-value="track.drc"
              :min="0"
              :max="4"
              :step="0.1"
              :disabled="copied"
              :ariaLabelledby="labelId"
              @update:model-value="onDrc"
              @slideend="editor.endCoalescing()"
            />
            <output class="track-field__value" :for="id">
              {{ track.drc === 0 ? t('tracks.output.drcOff') : track.drc.toFixed(1) }}
            </output>
          </div>
        </template>
      </Field>
      <Field :label="t('tracks.output.loudness')" :path="`${path}.loudness`" stacked>
        <template #default="{ id, invalid }">
          <Select
            :input-id="id"
            class="track-field__control"
            :model-value="track.loudness"
            :options="loudnessOptions"
            option-label="label"
            option-value="value"
            :disabled="copied"
            :invalid="invalid"
            @update:model-value="onLoudness"
          />
        </template>
      </Field>
    </div>
  </TrackRowFrame>
</template>

<style scoped>
.track-fields {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-3);
  align-items: flex-start;
}

.track-fields > * {
  flex: 1 1 11rem;
  min-width: 0;
}

.track-fields > .track-field--fit {
  flex: 0 1 auto;
}

/* A label with a help button is taller: every label gets its height, so the controls line up. */
.track-fields :deep(.rf-field__label) {
  min-height: 1.75rem;
}

.track-fields__note {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.track-field__static {
  display: grid;
  gap: var(--rf-space-1);
}

.track-field__static-label {
  font-weight: var(--rf-font-weight-medium);
}

.track-field__control,
.track-field__number {
  width: 100%;
}

.track-field__number :deep(input) {
  width: 100%;
  min-width: 0;
}

.track-field__slider {
  display: flex;
  align-items: center;
  gap: var(--rf-space-3);
  min-height: 2.5rem;
}

.track-field__slider > :first-child {
  flex: 1;
}

.track-field__value {
  min-width: 2rem;
  font-variant-numeric: tabular-nums;
  text-align: end;
}
</style>
