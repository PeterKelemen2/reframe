<script setup lang="ts">
import InputText from 'primevue/inputtext'
import { computed, nextTick, ref, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { NamingVariable } from '@/stores/system'

import {
  accept,
  type Completion,
  completionAt,
  insertAt,
  matchSpecs,
  matchVariables,
  type SpecKey,
} from './template'

/**
 * A naming template input. Typing `{` (or editing inside `{…}`) lists the variables, and after
 * `name:` the format specs of that variable's kind. Arrow keys move, Enter or Tab take one,
 * Escape closes the list.
 */
const props = defineProps<{
  modelValue: string
  variables: NamingVariable[]
  /** The input's id (from `Field`). */
  id?: string
  invalid?: boolean
  disabled?: boolean
  /** Shown while the field is empty; already translated. */
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  focus: []
  blur: []
}>()

const { t } = useI18n()

const field = useTemplateRef<InstanceType<typeof InputText>>('field')
const listId = `${useId()}-list`
const completion = ref<Completion | null>(null)
const active = ref(0)
/** The last selection, for an insertion while the focus is elsewhere (a chip click). */
let selection = { start: props.modelValue.length, end: props.modelValue.length }

function element(): HTMLInputElement | null {
  return (field.value as unknown as { $el?: HTMLInputElement } | null)?.$el ?? null
}

interface Option {
  key: string
  value: string
  label: string
  detail: string
}

function specDetail(key: SpecKey): string {
  switch (key) {
    case 'pad2':
      return t('naming.spec.pad2')
    case 'pad3':
      return t('naming.spec.pad3')
    case 'upper':
      return t('naming.spec.upper')
    case 'lower':
      return t('naming.spec.lower')
    case 'title':
      return t('naming.spec.title')
    case 'isoDate':
      return t('naming.spec.isoDate')
    case 'dotDate':
      return t('naming.spec.dotDate')
    case 'year':
      return t('naming.spec.year')
    case 'time':
      return t('naming.spec.time')
    case 'timeSeconds':
      return t('naming.spec.timeSeconds')
  }
}

const options = computed<Option[]>(() => {
  const current = completion.value
  if (current === null) return []
  if (current.kind === 'name') {
    return matchVariables(props.variables, current.query).map((variable) => ({
      key: variable.name,
      value: variable.name,
      label: `{${variable.name}}`,
      detail: variable.description,
    }))
  }
  return matchSpecs(props.variables, current.name, current.query).map((suggestion) => ({
    key: suggestion.spec,
    value: suggestion.spec,
    label: `{${current.name}:${suggestion.spec}}`,
    detail: specDetail(suggestion.key),
  }))
})
const open = computed(() => options.value.length > 0)
const activeId = computed(() => (open.value ? `${listId}-${active.value}` : undefined))

function remember(): void {
  const input = element()
  if (input === null) return
  selection = {
    start: input.selectionStart ?? input.value.length,
    end: input.selectionEnd ?? input.value.length,
  }
}

function update(): void {
  remember()
  const input = element()
  if (input === null || selection.start !== selection.end) {
    completion.value = null
    return
  }
  const next = completionAt(input.value, selection.start)
  if (next?.start !== completion.value?.start || next?.kind !== completion.value?.kind) {
    active.value = 0
  }
  completion.value = next
}

async function place(text: string, caret: number): Promise<void> {
  emit('update:modelValue', text)
  await nextTick()
  const input = element()
  if (input === null) return
  input.focus()
  input.setSelectionRange(caret, caret)
  remember()
}

function choose(index: number): void {
  const current = completion.value
  const option = options.value[index]
  if (current === null || option === undefined) return
  const next = accept(props.modelValue, current, option.value)
  completion.value = null
  void place(next.text, next.caret)
}

function onInput(value: string | undefined): void {
  emit('update:modelValue', value ?? '')
  void nextTick(update)
}

function onKeydown(event: KeyboardEvent): void {
  if (!open.value) return
  const count = options.value.length
  switch (event.key) {
    case 'ArrowDown':
      active.value = (active.value + 1) % count
      break
    case 'ArrowUp':
      active.value = (active.value - 1 + count) % count
      break
    case 'Enter':
    case 'Tab':
      choose(active.value)
      break
    case 'Escape':
      completion.value = null
      break
    default:
      return
  }
  event.preventDefault()
}

function onKeyup(event: KeyboardEvent): void {
  // Moving the caret along the text can enter or leave a variable.
  if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) update()
}

function onBlur(): void {
  remember()
  completion.value = null
  emit('blur')
}

/** Inserts `text` at the caret (or over the selection) the field had last. */
function insert(text: string): void {
  const start = Math.min(selection.start, props.modelValue.length)
  const end = Math.min(selection.end, props.modelValue.length)
  const next = insertAt(props.modelValue, start, end, text)
  void place(next.text, next.caret)
}

defineExpose({ insert })
</script>

<template>
  <div class="naming-template">
    <InputText
      :id="id"
      ref="field"
      class="naming-template__input"
      :model-value="modelValue"
      :invalid="invalid"
      :disabled="disabled"
      :placeholder="placeholder"
      fluid
      role="combobox"
      autocomplete="off"
      spellcheck="false"
      aria-autocomplete="list"
      :aria-expanded="open"
      :aria-controls="listId"
      :aria-activedescendant="activeId"
      @update:model-value="onInput"
      @keydown="onKeydown"
      @keyup="onKeyup"
      @click="update"
      @focus="emit('focus')"
      @blur="onBlur"
    />
    <ul
      v-show="open"
      :id="listId"
      class="naming-template__list"
      role="listbox"
      :aria-label="t('naming.template.completion')"
    >
      <li
        v-for="(option, index) in options"
        :id="`${listId}-${index}`"
        :key="option.key"
        class="naming-template__option"
        :class="{ 'naming-template__option--active': index === active }"
        role="option"
        :aria-selected="index === active"
        @mousedown.prevent
        @click="choose(index)"
      >
        <code>{{ option.label }}</code>
        <span class="naming-template__detail">{{ option.detail }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.naming-template {
  position: relative;
  min-width: 0;
}

.naming-template__input {
  font-family: var(--rf-font-mono);
}

.naming-template__list {
  position: absolute;
  z-index: 20;
  inset-inline: 0;
  top: calc(100% + 2px);
  max-height: 16rem;
  margin: 0;
  padding: var(--rf-space-1) 0;
  overflow-y: auto;
  list-style: none;
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md);
  background: var(--p-overlay-popover-background, var(--rf-color-surface));
  color: var(--rf-color-text);
  box-shadow: var(--p-overlay-popover-shadow, 0 4px 12px rgb(0 0 0 / 0.15));
}

.naming-template__option {
  display: flex;
  gap: var(--rf-space-3);
  align-items: baseline;
  padding: var(--rf-space-1) var(--rf-space-3);
  cursor: pointer;
}

.naming-template__option code {
  flex: none;
  font-family: var(--rf-font-mono);
}

.naming-template__option--active {
  background: var(--p-highlight-background);
  color: var(--p-highlight-color);
}

.naming-template__detail {
  min-width: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  overflow-wrap: anywhere;
}

.naming-template__option--active .naming-template__detail {
  color: inherit;
}
</style>
