<script setup lang="ts">
import Button from 'primevue/button'
import Slider from 'primevue/slider'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ChoiceSetting } from './encoders'

/** The encoder's speed presets, fastest first; `null` is the encoder's default. */
const props = defineProps<{
  setting: ChoiceSetting
  modelValue: string | null
  inputId?: string
  labelledby?: string
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string | null]; commit: [] }>()

const { t } = useI18n()

const choices = computed(() => props.setting.choices)
const index = computed(() => {
  const own = choices.value.findIndex((choice) => choice.value === props.modelValue)
  if (own !== -1) return own
  const fallback = choices.value.findIndex((choice) => choice.value === props.setting.default)
  return fallback === -1 ? Math.floor((choices.value.length - 1) / 2) : fallback
})
const defaultChoice = computed(
  () => choices.value.find((choice) => choice.value === props.setting.default) ?? null,
)
const shown = computed(() => {
  if (props.modelValue === null) {
    return defaultChoice.value === null
      ? t('video.speed.encoderDefault')
      : t('video.speed.default', { label: defaultChoice.value.label })
  }
  return (
    choices.value.find((choice) => choice.value === props.modelValue)?.label ?? props.modelValue
  )
})

function update(value: number | number[]): void {
  if (typeof value !== 'number') return
  const choice = choices.value[Math.round(value)]
  if (choice !== undefined && choice.value !== props.modelValue) {
    emit('update:modelValue', choice.value)
  }
}

function reset(): void {
  emit('update:modelValue', null)
  emit('commit')
}
</script>

<template>
  <div class="speed-preset">
    <div class="speed-preset__row" @keyup="emit('commit')">
      <Slider
        class="speed-preset__slider"
        :model-value="index"
        :min="0"
        :max="Math.max(choices.length - 1, 0)"
        :step="1"
        :disabled="disabled"
        :ariaLabelledby="labelledby"
        :pt="{ handle: { id: inputId, 'aria-valuetext': shown } }"
        @update:model-value="update"
        @slideend="emit('commit')"
      />
      <output class="speed-preset__value" data-speed-value>{{ shown }}</output>
    </div>
    <div class="speed-preset__ends" aria-hidden="true">
      <span>{{ t('video.speed.faster') }}</span>
      <span>{{ t('video.speed.slower') }}</span>
    </div>
    <Button
      v-if="modelValue !== null"
      class="speed-preset__reset"
      link
      size="small"
      :label="t('video.speed.useDefault')"
      :disabled="disabled"
      @click="reset"
    />
  </div>
</template>

<style scoped>
.speed-preset {
  display: grid;
  gap: var(--rf-space-1);
  justify-items: start;
}

.speed-preset__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 7.5rem;
  align-items: center;
  gap: var(--rf-space-4);
  width: 100%;
}

.speed-preset__slider {
  margin-inline: var(--rf-space-2);
}

.speed-preset__value {
  font-weight: var(--rf-font-weight-medium);
}

.speed-preset__ends {
  display: flex;
  justify-content: space-between;
  width: 100%;
  padding-inline-end: calc(7.5rem + var(--rf-space-4));
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
}

.speed-preset__reset {
  padding-inline: 0;
}
</style>
