<script setup lang="ts">
import InputNumber from 'primevue/inputnumber'
import InputText from 'primevue/inputtext'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, nextTick, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { EncoderOption } from '@/api/types'
import Field from '@/components/base/Field.vue'
import ChoiceSelect from '@/components/video/ChoiceSelect.vue'
import type { VideoEncoderDef } from '@/components/video/encoders'
import { useEditorStore } from '@/stores/editor'

import {
  cliName,
  defaultText,
  defaultValue,
  FLOAT_DIGITS,
  type OptionValue,
  optionPath,
  optionPointer,
} from './options'
import ResetButton from './ResetButton.vue'

/** One advanced option: its control, the default, reset and help. Absent from the job = default. */
const props = defineProps<{
  option: EncoderOption
  encoder: VideoEncoderDef
  disabled: boolean
  /** The category's name, for a row shown outside its category (search results). */
  category?: string
}>()

const { t, n, locale } = useI18n()
const editor = useEditorStore()
const root = useTemplateRef<HTMLElement>('root')
const defaultId = useId()

const video = computed(() => editor.job?.video ?? null)
const path = computed(() => optionPath(props.option.key))
const pointer = computed(() => optionPointer(props.option.key))
const stored = computed(() => video.value?.advanced?.[props.option.key])
const changed = computed(() => stored.value !== undefined)
const fallback = computed(() =>
  video.value === null ? '' : defaultText(props.option, video.value, props.encoder, t, n),
)
const defaultShown = computed(() => changed.value || props.option.type === 'bool')
const help = computed(() =>
  t('advanced.help', { help: props.option.help, name: cliName(props.option) }),
)
const enumSetting = computed(() => ({
  choices: props.option.choices ?? [],
  mapping: props.option.mapping,
  help: '',
}))
const switchValue = computed(() => {
  if (typeof stored.value === 'boolean') return stored.value
  const known =
    video.value === null ? undefined : defaultValue(props.option, video.value, props.encoder)
  return known === true
})

function write(value: OptionValue, typing = false): void {
  if (value === stored.value) return
  editor.set(pointer.value, value, typing ? { coalesce: path.value } : undefined)
}

function remove(typing = false): void {
  if (!changed.value) return
  editor.patch(
    [{ op: 'remove', path: pointer.value }],
    typing ? { coalesce: path.value } : undefined,
  )
}

function setNumber(value: number | null | undefined): void {
  if (typeof value === 'number') write(value)
  else remove()
}

function setText(value: string | undefined): void {
  if (value) write(value, true)
  else remove(true)
}

function setChoice(value: string | null): void {
  if (value === null) remove()
  else write(value)
}

const COMMIT_KEYS = new Set(['Tab', 'Enter', 'NumpadEnter'])
let focusText = ''

function keepText(event: FocusEvent): void {
  focusText = (event.target as HTMLInputElement).value
}

/**
 * PrimeVue's InputNumber commits its text, clamped and rounded, on every Tab, Enter and blur: a
 * stored value outside the range or with more decimals would be rewritten by a pass through the
 * field. Unchanged text never reaches it.
 */
function skipUnchanged(event: Event): void {
  if (event instanceof KeyboardEvent && !COMMIT_KEYS.has(event.code || event.key)) return
  if ((event.target as HTMLInputElement).value === focusText) event.stopPropagation()
}

/** The reset button goes with the change: the focus goes to the option's control. */
async function reset(): Promise<void> {
  remove()
  await nextTick()
  root.value
    ?.querySelector<HTMLElement>('.rf-field__control :is(input, [tabindex]:not([tabindex="-1"]))')
    ?.focus()
}
</script>

<template>
  <div
    ref="root"
    class="advanced-row"
    :class="{ 'advanced-row--changed': changed }"
    :data-option="option.key"
    :data-changed="changed"
  >
    <span v-if="category" class="advanced-row__category">{{ category }}</span>
    <Field
      :label="option.label"
      :path="path"
      :help="help"
      :description="defaultShown ? defaultId : undefined"
    >
      <template #default="{ id, labelId, invalid }">
        <div class="advanced-row__control">
          <span
            v-if="option.type === 'int' || option.type === 'float'"
            class="advanced-row__input"
            @focusin="keepText"
            @keydown.capture="skipUnchanged"
            @blur.capture="skipUnchanged"
          >
            <InputNumber
              :input-id="id"
              :locale="locale"
              :model-value="typeof stored === 'number' ? stored : null"
              :min="option.min ?? undefined"
              :max="option.max ?? undefined"
              :step="option.step ?? 1"
              :min-fraction-digits="0"
              :max-fraction-digits="option.type === 'float' ? FLOAT_DIGITS : 0"
              :use-grouping="false"
              :suffix="option.unit ? ` ${option.unit}` : undefined"
              :placeholder="fallback"
              :invalid="invalid"
              :disabled="disabled"
              fluid
              @update:model-value="setNumber"
            />
          </span>
          <ToggleSwitch
            v-else-if="option.type === 'bool'"
            :input-id="id"
            :model-value="switchValue"
            :ariaLabelledby="labelId"
            :invalid="invalid"
            :disabled="disabled"
            @update:model-value="write($event)"
          />
          <ChoiceSelect
            v-else-if="option.type === 'enum'"
            class="advanced-row__input"
            :setting="enumSetting"
            :model-value="stored === undefined ? null : String(stored)"
            :none-label="t('advanced.default.choice', { text: fallback })"
            :input-id="id"
            :labelledby="labelId"
            :invalid="invalid"
            :disabled="disabled"
            @update:model-value="setChoice"
          />
          <InputText
            v-else
            :id="id"
            class="advanced-row__input advanced-row__text"
            :model-value="stored === undefined ? '' : String(stored)"
            :placeholder="fallback"
            :invalid="invalid"
            :disabled="disabled"
            spellcheck="false"
            autocomplete="off"
            fluid
            @update:model-value="setText"
            @blur="editor.endCoalescing()"
          />
          <ResetButton v-if="changed" :label="option.label" :disabled="disabled" @click="reset" />
          <span
            v-if="defaultShown"
            :id="defaultId"
            class="advanced-row__default"
            data-role="default"
          >
            {{ t('advanced.default.beside', { text: fallback }) }}
          </span>
        </div>
      </template>
    </Field>
  </div>
</template>

<style scoped>
.advanced-row {
  display: grid;
  gap: var(--rf-space-1);
  padding: var(--rf-space-1) var(--rf-space-2);
  border-inline-start: 3px solid transparent;
  border-radius: var(--rf-radius-sm);
}

.advanced-row--changed {
  border-inline-start-color: var(--rf-color-primary);
  background: color-mix(in srgb, var(--rf-color-primary) 10%, transparent);
}

.advanced-row__category {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
}

.advanced-row__control {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-1) var(--rf-space-2);
  min-width: 0;
}

.advanced-row__input {
  flex: 1 1 12rem;
  min-width: 0;
  max-width: 34rem;
}

.advanced-row__text {
  font-family: var(--rf-font-mono);
}

.advanced-row__text::placeholder {
  font-family: var(--rf-font-family);
}

/* Beside a switch the text wraps in its own box instead of going under the switch. */
.advanced-row__default {
  flex: 1 1 10rem;
  min-width: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

/* In a narrow column the label goes above its control. */
@container (width < 30rem) {
  .advanced-row :deep(.rf-field--inline) {
    grid-template-columns: minmax(0, 1fr);
  }

  .advanced-row :deep(.rf-field--inline .rf-field__issues) {
    grid-column: 1;
  }
}
</style>
