<script setup lang="ts">
import Select from 'primevue/select'
import { computed, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import StatusDot from '@/components/base/StatusDot.vue'
import { useSystemStore } from '@/stores/system'

import {
  availabilityOf,
  type EncoderAvailability,
  type EncoderFamily,
  groupEncoders,
} from './encoders'
import { useAvailabilityText } from './text'

/** The video encoders by family, each with its detection status; unavailable ones cannot be chosen. */
const props = defineProps<{
  modelValue: string
  inputId?: string
  labelledby?: string
  invalid?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [id: string] }>()

const { t } = useI18n()
const system = useSystemStore()
const availabilityText = useAvailabilityText()
const select = useTemplateRef<InstanceType<typeof Select>>('select')

interface Item {
  id: string
  label: string
  availability: EncoderAvailability
  status: string
  /** The option's accessible name: the status is part of it, so a screen reader hears the reason. */
  text: string
  disabled: boolean
}

function familyName(family: EncoderFamily): string {
  switch (family) {
    case 'software':
      return t('video.family.software')
    case 'nvenc':
      return t('video.family.nvenc')
    case 'qsv':
      return t('video.family.qsv')
    case 'amf':
      return t('video.family.amf')
    case 'vaapi':
      return t('video.family.vaapi')
  }
}

function item(id: string, label: string): Item {
  const availability = availabilityOf(system.encoderStatus(id), system.capabilities)
  const status = availabilityText(availability)
  return {
    id,
    label,
    availability,
    status,
    text: t('video.encoder.option', { label, id, status }),
    disabled: !availability.selectable,
  }
}

const groups = computed(() => {
  const encoders = system.definitions?.video_encoders ?? {}
  const result = groupEncoders(encoders).map((group) => ({
    label: familyName(group.family),
    items: group.encoders.map((encoder) => item(encoder.id, encoder.label)),
  }))
  // A job can name an encoder these definitions do not have (a newer preset): it still shows.
  if (props.modelValue !== '' && encoders[props.modelValue] === undefined) {
    result.push({
      label: t('video.family.other'),
      items: [item(props.modelValue, props.modelValue)],
    })
  }
  return result
})

const current = computed(() =>
  groups.value.flatMap((group) => group.items).find((entry) => entry.id === props.modelValue),
)

function choose(value: unknown): void {
  const chosen = groups.value.flatMap((group) => group.items).find((entry) => entry.id === value)
  if (chosen === undefined || chosen.disabled || chosen.id === props.modelValue) return
  emit('update:modelValue', chosen.id)
}

/** Focuses the picker and opens its list (*Choose encoder*). */
function open(): void {
  select.value?.show(true)
}

defineExpose({ open })
</script>

<template>
  <Select
    ref="select"
    class="encoder-picker"
    :model-value="modelValue"
    :options="groups"
    option-group-label="label"
    option-group-children="items"
    option-label="text"
    option-value="id"
    option-disabled="disabled"
    :input-id="inputId"
    :ariaLabelledby="labelledby"
    :invalid="invalid"
    :disabled="disabled"
    scroll-height="24rem"
    fluid
    :pt="{ option: { class: 'encoder-picker__option' } }"
    @update:model-value="choose"
  >
    <template #value>
      <span v-if="current" class="encoder-picker__value">
        <StatusDot :tone="current.availability.tone" :label="current.status" />
        <span>{{ current.label }}</span>
        <code class="encoder-picker__id">{{ current.id }}</code>
      </span>
    </template>
    <template #optiongroup="{ option }">
      <span class="encoder-picker__group">{{ option.label }}</span>
    </template>
    <template #option="{ option }">
      <span
        class="encoder-picker__entry"
        :data-encoder="option.id"
        :data-state="option.availability.kind"
      >
        <span class="encoder-picker__name">
          <span>{{ option.label }}</span>
          <code class="encoder-picker__id">{{ option.id }}</code>
        </span>
        <StatusDot
          class="encoder-picker__status"
          :tone="option.availability.tone"
          :label="option.status"
          show-label
        />
      </span>
    </template>
  </Select>
</template>

<style scoped>
/* The id goes to a second line rather than being cut: it is what a user searches for. */
.encoder-picker :deep(.p-select-label) {
  white-space: normal;
}

.encoder-picker__value {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0 var(--rf-space-2);
  min-width: 0;
}

.encoder-picker__id {
  color: var(--rf-color-text-muted);
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-sm);
}
</style>

<style>
/* The list is teleported to the body, out of reach of scoped styles. */
.encoder-picker__option {
  white-space: normal;
}

.encoder-picker__option.p-disabled {
  opacity: 1;
}

.encoder-picker__option.p-disabled .encoder-picker__name {
  color: var(--rf-color-text-muted);
}

.encoder-picker__entry {
  display: grid;
  gap: var(--rf-space-1);
  min-width: 0;
}

.encoder-picker__name {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--rf-space-2);
}

.encoder-picker__entry .encoder-picker__id {
  color: var(--rf-color-text-muted);
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-sm);
}

.encoder-picker__status {
  font-size: var(--rf-font-size-sm);
}

.encoder-picker__entry[data-state='unavailable'] .encoder-picker__status,
.encoder-picker__entry[data-state='failed'] .encoder-picker__status {
  color: var(--p-status-error-color);
}

.encoder-picker__group {
  font-weight: var(--rf-font-weight-bold);
}
</style>
