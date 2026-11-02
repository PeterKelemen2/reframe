<script setup lang="ts">
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { FilterConfig, FilterDef, ValidationIssue } from '@/api/types'
import Field from '@/components/base/Field.vue'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'
import { useValidationStore } from '@/stores/validation'

import {
  type Availability,
  availabilityOf,
  type FilterImplementation,
  implementationOf,
  implementationOps,
  presetOf,
  presetOps,
  turnOnOps,
} from './filters'
import type { CustomCheck } from './useCustomCheck'

/** One filter of the list: on / off, and while on its implementation, preset, tune and text. */
const props = defineProps<{
  filter: FilterDef
  selected: boolean
  disabled: boolean
  /** The one-frame test of this filter's text; `null` when it was not checked. */
  check: CustomCheck | null
}>()
const emit = defineEmits<{ select: []; typed: [text: string] }>()

const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()
const validation = useValidationStore()

const base = computed(() => `filters.${props.filter.id}`)
const config = computed<FilterConfig | null>(() => editor.job?.filters?.[props.filter.id] ?? null)
const implementation = computed(() =>
  implementationOf(props.filter, config.value, system.capabilities),
)
const preset = computed(() =>
  config.value === null ? null : presetOf(implementation.value, config.value),
)
const tunes = computed(() => implementation.value.tunes ?? [])

// The source colour box says this one, with its fix.
const toggleIssues = computed(() =>
  validation.issuesFor(base.value).filter((issue) => issue.code !== 'filter.hdr_without_tonemap'),
)

function statusOf(availability: Availability, candidate: FilterImplementation): string {
  switch (availability.kind) {
    case 'unavailable':
      return availability.reason === null
        ? t('filters.implementation.notInBuild', { filter: availability.filter })
        : t('filters.implementation.failed', { reason: availability.reason })
    case 'untested':
      return candidate.needs_vulkan
        ? t('filters.implementation.untestedVulkan')
        : t('filters.implementation.untested')
    default:
      return ''
  }
}

const implementationOptions = computed(() =>
  props.filter.implementations.map((candidate) => {
    const availability = availabilityOf(candidate, system.capabilities)
    const status = statusOf(availability, candidate)
    return {
      id: candidate.id,
      text:
        status === ''
          ? candidate.label
          : t('filters.implementation.option', { label: candidate.label, status }),
      disabled: availability.kind === 'unavailable',
    }
  }),
)

// Select shows its placeholder for `null` and `''`, so the preset's own chain needs a value.
const NO_TUNE = '(default)'

const tuneOptions = computed(() => [
  // A preset without a plain chain needs a tune.
  ...(preset.value?.chain ? [{ id: NO_TUNE, label: t('filters.tune.none') }] : []),
  ...tunes.value.map((tune) => ({ id: tune.id, label: tune.label })),
])

const customText = computed(() => config.value?.custom ?? '')
const customIssues = computed<ValidationIssue[]>(() => [
  ...validation.issuesFor(`${base.value}.custom`),
  ...(props.check?.errors ?? []),
])

function toggle(on: boolean): void {
  if (on) editor.patch(turnOnOps(props.filter, system.capabilities))
  else editor.patch([{ op: 'remove', path: `/filters/${props.filter.id}` }])
}

function chooseImplementation(id: unknown): void {
  const chosen = props.filter.implementations.find((candidate) => candidate.id === id)
  const current = config.value
  if (current === null || chosen === undefined || chosen.id === implementation.value.id) return
  editor.patch(implementationOps(props.filter, current, chosen))
}

function choosePreset(id: unknown): void {
  const chosen = implementation.value.presets.find((candidate) => candidate.id === id)
  const current = config.value
  if (current === null || chosen === undefined) return
  editor.patch(presetOps(props.filter, current, chosen))
}

function chooseTune(id: unknown): void {
  editor.set(
    `/filters/${props.filter.id}/tune`,
    typeof id === 'string' && id !== NO_TUNE ? id : null,
  )
}

function setCustom(value: string | undefined): void {
  const text = value ?? ''
  editor.set(`/filters/${props.filter.id}/custom`, text === '' ? null : text, {
    coalesce: `${base.value}.custom`,
  })
  emit('typed', text)
}
</script>

<template>
  <div
    class="filter-row"
    :class="{ 'filter-row--selected': selected }"
    :data-filter="filter.id"
    :data-on="config !== null"
    @focusin="emit('select')"
    @click="emit('select')"
  >
    <Field :label="filter.label" :path="base" :issues="toggleIssues">
      <template #default="{ id, labelId }">
        <ToggleSwitch
          :input-id="id"
          :model-value="config !== null"
          :ariaLabelledby="labelId"
          :disabled="disabled"
          @update:model-value="toggle"
        />
      </template>
    </Field>
    <div v-if="config !== null" class="filter-row__settings">
      <Field
        v-if="filter.implementations.length > 1"
        :label="t('filters.field.implementation')"
        :path="`${base}.implementation`"
      >
        <template #default="{ id, labelId, invalid }">
          <Select
            :input-id="id"
            :model-value="implementation.id"
            :options="implementationOptions"
            option-label="text"
            option-value="id"
            option-disabled="disabled"
            :ariaLabelledby="labelId"
            :invalid="invalid"
            :disabled="disabled"
            fluid
            :pt="{ option: { class: 'filter-row__option' } }"
            @update:model-value="chooseImplementation"
          />
        </template>
      </Field>
      <Field
        v-if="implementation.presets.length > 1"
        :label="t('filters.field.preset')"
        :path="`${base}.preset`"
      >
        <template #default="{ id, labelId, invalid }">
          <Select
            :input-id="id"
            :model-value="config.preset"
            :options="implementation.presets"
            option-label="label"
            option-value="id"
            :ariaLabelledby="labelId"
            :invalid="invalid"
            :disabled="disabled"
            fluid
            @update:model-value="choosePreset"
          />
        </template>
      </Field>
      <Field v-if="tunes.length > 0" :label="t('filters.field.tune')" :path="`${base}.tune`">
        <template #default="{ id, labelId, invalid }">
          <Select
            :input-id="id"
            :model-value="config.tune ?? NO_TUNE"
            :options="tuneOptions"
            option-label="label"
            option-value="id"
            :ariaLabelledby="labelId"
            :invalid="invalid"
            :disabled="disabled"
            fluid
            @update:model-value="chooseTune"
          />
        </template>
      </Field>
      <Field
        v-if="preset?.custom"
        :label="filter.id === 'custom' ? t('filters.field.chain') : t('filters.field.custom')"
        :path="`${base}.custom`"
        :issues="customIssues"
      >
        <template #default="{ id, invalid }">
          <InputText
            :id="id"
            class="filter-row__custom"
            :model-value="customText"
            :invalid="invalid"
            :disabled="disabled"
            spellcheck="false"
            autocomplete="off"
            fluid
            @update:model-value="setCustom"
            @blur="editor.endCoalescing()"
          />
          <p
            v-if="check !== null && (check.errors === null || check.errors.length === 0)"
            class="filter-row__check"
            role="status"
            :data-check="check.errors === null ? 'checking' : 'accepted'"
          >
            {{ check.errors === null ? t('filters.check.checking') : t('filters.check.accepted') }}
          </p>
        </template>
      </Field>
    </div>
    <slot />
  </div>
</template>

<style scoped>
.filter-row {
  display: grid;
  gap: var(--rf-space-2);
  padding: var(--rf-space-2) var(--rf-space-3);
  border: 1px solid transparent;
  border-radius: var(--rf-radius-md);
}

.filter-row--selected {
  border-color: var(--rf-color-border);
  background: var(--rf-color-surface-hover);
}

.filter-row__settings {
  display: grid;
  gap: var(--rf-space-2);
}

.filter-row__custom {
  font-family: var(--rf-font-mono);
}

.filter-row__check {
  margin: var(--rf-space-1) 0 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}
</style>

<style>
/* The list is teleported to the body, out of reach of scoped styles. */
.filter-row__option {
  white-space: normal;
}
</style>
