<script setup lang="ts">
import InputNumber from 'primevue/inputnumber'
import Slider from 'primevue/slider'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { decimals } from '@/components/summary/format'

import { type QualityBand, type QualityMode, roundToStep } from './encoders'

/**
 * A constant-quality value on the encoder's scale, with the recommended band shaded. Emits
 * `update:modelValue` for every step of a drag or a key, and `commit` when the gesture ends.
 */
const props = defineProps<{
  mode: QualityMode
  modelValue: number
  /** The recommended band for the output size; `null`: none is known. */
  band: QualityBand | null
  /** The short side of the output picture that `band` is for. */
  lines: number | null
  inputId?: string
  labelledby?: string
  invalid?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: number]; commit: [] }>()

const { t, n, locale } = useI18n()

const digits = computed(() => {
  const fraction = String(props.mode.step).split('.')[1]
  return fraction === undefined ? 0 : fraction.length
})

function format(value: number): string {
  return decimals(value, digits.value, n)
}

function percent(value: number): number {
  const span = props.mode.max - props.mode.min
  return span <= 0 ? 0 : ((value - props.mode.min) / span) * 100
}

const bandStyle = computed(() => {
  const band = props.band
  if (band === null) return null
  const start = percent(Math.max(band.low, props.mode.min))
  const end = percent(Math.min(band.high, props.mode.max))
  return { left: `${start}%`, width: `${Math.max(end - start, 0)}%` }
})

const better = computed(() => props.mode.direction === 'lower_is_better')
const inBand = computed(
  () =>
    props.band !== null &&
    props.modelValue >= props.band.low &&
    props.modelValue <= props.band.high,
)

function update(value: number | number[] | null | undefined): void {
  if (typeof value !== 'number' || Number.isNaN(value)) return
  const next = roundToStep(value, props.mode)
  if (next !== props.modelValue) emit('update:modelValue', next)
}

// PrimeVue's Slider moves one `step` for every key, PageUp and PageDown included: on x264's
// 0.1 scale that is 510 presses end to end. A page is 5 x264 RF, about 25 on the 0–255 scales.
const keySteps = computed(() => {
  const { min, max, step } = props.mode
  const unit = Math.max(1, Math.round((max - min) / 51))
  return { arrow: step < 1 ? 0.5 : step, page: 5 * unit }
})

function onKey(event: KeyboardEvent): void {
  if (props.disabled) return
  const { arrow, page } = keySteps.value
  const value = props.modelValue
  let next: number
  switch (event.key) {
    case 'ArrowLeft':
    case 'ArrowDown':
      next = value - arrow
      break
    case 'ArrowRight':
    case 'ArrowUp':
      next = value + arrow
      break
    case 'PageDown':
      next = value - page
      break
    case 'PageUp':
      next = value + page
      break
    case 'Home':
      next = props.mode.min
      break
    case 'End':
      next = props.mode.max
      break
    default:
      return
  }
  event.preventDefault()
  event.stopPropagation()
  update(next)
}

function typed(value: number | null | undefined): void {
  update(value)
  emit('commit')
}
</script>

<template>
  <div class="quality-slider" :class="{ 'quality-slider--disabled': disabled }">
    <div class="quality-slider__row">
      <div class="quality-slider__track" @keydown.capture="onKey" @keyup="emit('commit')">
        <span
          v-if="bandStyle"
          class="quality-slider__band"
          :style="bandStyle"
          data-band
          aria-hidden="true"
        />
        <Slider
          class="quality-slider__slider"
          :model-value="modelValue"
          :min="mode.min"
          :max="mode.max"
          :step="mode.step"
          :disabled="disabled"
          :ariaLabelledby="labelledby"
          :pt="{
            handle: {
              'aria-valuetext': t('video.quality.valueText', {
                scale: mode.label,
                value: format(modelValue),
              }),
            },
          }"
          @update:model-value="update"
          @slideend="emit('commit')"
        />
      </div>
      <InputNumber
        class="quality-slider__input"
        :input-id="inputId"
        :model-value="modelValue"
        :min="mode.min"
        :max="mode.max"
        :step="mode.step"
        :min-fraction-digits="digits"
        :max-fraction-digits="digits"
        :prefix="`${mode.label} `"
        :locale="locale"
        :invalid="invalid"
        :disabled="disabled"
        @update:model-value="typed"
      />
    </div>
    <div class="quality-slider__ends" aria-hidden="true">
      <span>{{ better ? t('video.quality.better') : t('video.quality.smaller') }}</span>
      <span>{{ better ? t('video.quality.smaller') : t('video.quality.better') }}</span>
    </div>
    <p v-if="band !== null && lines !== null" class="quality-slider__band-note" data-band-note>
      <span class="quality-slider__swatch" aria-hidden="true" />
      {{
        t('video.quality.recommended', {
          lines,
          scale: mode.label,
          low: format(band.low),
          high: format(band.high),
        })
      }}
      <span v-if="!inBand" class="quality-slider__outside">{{ t('video.quality.outside') }}</span>
    </p>
  </div>
</template>

<style scoped>
.quality-slider {
  display: grid;
  gap: var(--rf-space-1);
}

.quality-slider__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 7.5rem;
  align-items: center;
  gap: var(--rf-space-4);
}

.quality-slider__track {
  position: relative;
  margin-inline: var(--rf-space-2);
}

.quality-slider__band {
  position: absolute;
  top: 50%;
  height: 1.25rem;
  transform: translateY(-50%);
  border: 1px solid var(--p-status-ok-border-color);
  border-radius: var(--rf-radius-sm);
  background: color-mix(in srgb, var(--p-status-ok-color) 22%, transparent);
  pointer-events: none;
}

.quality-slider__slider {
  position: relative;
}

.quality-slider__input :deep(input) {
  width: 100%;
  text-align: end;
}

.quality-slider__ends {
  display: flex;
  justify-content: space-between;
  padding-inline-end: calc(7.5rem + var(--rf-space-4));
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
}

.quality-slider__band-note {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.quality-slider__swatch {
  width: 1rem;
  height: 0.625rem;
  border: 1px solid var(--p-status-ok-border-color);
  border-radius: 2px;
  background: color-mix(in srgb, var(--p-status-ok-color) 22%, transparent);
}

.quality-slider__outside {
  color: var(--p-status-warn-color);
}
</style>
