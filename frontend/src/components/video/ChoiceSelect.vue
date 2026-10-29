<script setup lang="ts">
import Select from 'primevue/select'
import { computed } from 'vue'

import type { ChoiceSetting } from './encoders'

/** One of an encoder's choices (tune, profile, level), or `null`: the encoder decides. */
const props = defineProps<{
  setting: ChoiceSetting
  modelValue: string | null | undefined
  /** The text of the `null` entry; already translated. */
  noneLabel: string
  /** Only the choices for this bit depth, besides the current one. */
  bitDepth?: number
  inputId?: string
  labelledby?: string
  invalid?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string | null] }>()

// Select shows its placeholder for `null` and `''`, so the encoder's default needs a value of its own.
const NONE = '(default)'

const options = computed(() => {
  const current = props.modelValue ?? null
  const choices = props.setting.choices.filter(
    (choice) =>
      choice.value === current ||
      props.bitDepth === undefined ||
      (choice.bit_depths ?? null) === null ||
      choice.bit_depths?.includes(props.bitDepth),
  )
  const result = [
    { value: NONE, label: props.noneLabel },
    ...choices.map((choice) => ({ value: choice.value, label: choice.label })),
  ]
  if (current !== null && !choices.some((choice) => choice.value === current)) {
    result.push({ value: current, label: current })
  }
  return result
})

function update(value: unknown): void {
  const next = typeof value === 'string' && value !== NONE ? value : null
  if (next !== (props.modelValue ?? null)) emit('update:modelValue', next)
}
</script>

<template>
  <Select
    class="choice-select"
    :model-value="modelValue ?? NONE"
    :options="options"
    option-label="label"
    option-value="value"
    :input-id="inputId"
    :ariaLabelledby="labelledby"
    :invalid="invalid"
    :disabled="disabled"
    fluid
    @update:model-value="update"
  />
</template>
