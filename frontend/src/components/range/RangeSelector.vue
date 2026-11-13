<script setup lang="ts">
import { ChevronDown } from '@lucide/vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Popover from 'primevue/popover'
import RadioButton from 'primevue/radiobutton'
import Select from 'primevue/select'
import { computed, nextTick, reactive, ref, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ValidationIssue } from '@/api/types'
import Field from '@/components/base/Field.vue'
import { bySeverity, SEVERITY_ICON, useSeverityLabel } from '@/components/base/severity'
import { useReveal } from '@/composables/useReveal'
import { sameJson } from '@/editor/patch'
import { useEditorStore } from '@/stores/editor'
import { useUiStore } from '@/stores/ui'

import {
  canUseFrames,
  convertRange,
  formatClock,
  formatTime,
  hasChapters,
  parseFrame,
  parseTime,
  type Range,
  type RangeKind,
} from './range'
import { type RangePath, useRange } from './useRange'

const EDGES = ['start', 'end'] as const
type Edge = (typeof EDGES)[number]

const { t } = useI18n()
const severityLabel = useSeverityLabel()
const editor = useEditorStore()
const ui = useUiStore()
const { range, source, label, length, issues, issuesAt } = useRange()

const id = useId()
const titleId = `${id}-title`
const bodyId = `${id}-body`
const describedId = `${id}-described`
const helpId = `${id}-help`
const root = useTemplateRef<HTMLElement>('root')
const popover = useTemplateRef<InstanceType<typeof Popover>>('popover')
const open = ref(false)

useReveal('range', root)
// A field of an edge lives in the popover and shows itself (`Field`) once the popover is open.
watch(
  () => ui.revealed,
  (request) => {
    if (open.value) return
    if (request?.path !== 'range.start' && request?.path !== 'range.end') return
    // Not while the click that asked is still going up the page: the popover would take it
    // for a click outside and close.
    setTimeout(() => trigger()?.click())
  },
)

const severity = computed(() => bySeverity(issues.value)[0]?.severity ?? null)
const inGroup = computed(() => editor.target?.kind === 'group')

/** What the button's dot and severity icon show, for screen readers. */
const description = computed(() =>
  [
    editor.rangeOverridden ? t('base.field.overridden') : null,
    ...bySeverity(issues.value).map(
      (issue) => `${severityLabel(issue.severity)}: ${issue.message}`,
    ),
  ]
    .filter((part) => part !== null)
    .join(' '),
)

const buttonLabel = computed(() =>
  length.value === null
    ? t('range.buttonNoLength', { range: label.value })
    : t('range.button', { range: label.value, length: length.value }),
)

const modes = computed<{ kind: RangeKind; label: string; reason: string | null }[]>(() => {
  const media = source.value
  const framesReason = canUseFrames(media)
    ? null
    : (media?.video?.length ?? 0) > 0
      ? t('range.reason.frames')
      : t('range.reason.noVideo')
  return [
    { kind: 'full', label: t('range.modes.full'), reason: null },
    {
      kind: 'chapters',
      label: t('range.modes.chapters'),
      reason: hasChapters(media) ? null : t('range.reason.chapters'),
    },
    { kind: 'time', label: t('range.modes.time'), reason: null },
    { kind: 'frames', label: t('range.modes.frames'), reason: framesReason },
  ]
})

/**
 * The arrow keys check each mode they pass, so a mode converts from the range the user set, not
 * from the previous mode's conversion: conversions of conversions would lose part of the span.
 */
let convertedFrom: Range | null = null
let converted: Range | null = null

function chooseMode(kind: RangeKind): void {
  if (converted === null || !sameJson(range.value, converted)) convertedFrom = range.value
  converted = convertRange(convertedFrom ?? range.value, kind, source.value)
  editor.setRange(converted)
}

/** The popover's focus trap wraps onto its first radio: only the checked mode takes Tab. */
function modeTabindex(kind: RangeKind): number | undefined {
  const current = modes.value.find((mode) => mode.kind === range.value.kind)
  return kind === range.value.kind || current?.reason !== null ? undefined : -1
}

const chapterOptions = computed(() =>
  (source.value?.chapters ?? []).map((chapter, index) => {
    const named = { number: index + 1, start: formatClock(chapter.start) }
    return {
      value: index + 1,
      label: chapter.title
        ? t('range.chapters.option', { ...named, name: chapter.title })
        : t('range.chapters.optionUnnamed', named),
    }
  }),
)

/** A *From* after *To* moves *To* with it, and the other way round. */
function chooseChapter(edge: Edge, value: unknown): void {
  const current = range.value
  if (current.kind !== 'chapters' || typeof value !== 'number') return
  editor.setRange(
    edge === 'start'
      ? { kind: 'chapters', start: value, end: Math.max(value, current.end) }
      : { kind: 'chapters', start: Math.min(value, current.start), end: value },
  )
}

/** What a time or frame field shows for the range as it is. */
function shown(edge: Edge): string {
  const current = range.value
  if (current.kind !== 'time' && current.kind !== 'frames') return ''
  const value = current[edge]
  if (value == null) return ''
  return current.kind === 'time' ? formatTime(value) : String(value)
}

// The typed text, kept while it does not parse; a change of its own edge shows the range again.
const texts = reactive<Record<Edge, string>>({ start: '', end: '' })
const unparsed = reactive<Record<Edge, boolean>>({ start: false, end: false })
for (const edge of EDGES) {
  watch(
    [() => range.value.kind, () => shown(edge)],
    ([, text]) => {
      texts[edge] = text
      unparsed[edge] = false
    },
    { immediate: true },
  )
}

const fieldText = computed(() => ({
  time: {
    start: t('range.time.start'),
    end: t('range.time.end'),
    toEnd: t('range.time.toEnd'),
    help: t('range.time.help'),
    invalid: t('range.time.invalid'),
  },
  frames: {
    start: t('range.frames.start'),
    end: t('range.frames.end'),
    toEnd: t('range.frames.toEnd'),
    help: t('range.frames.help'),
    invalid: t('range.frames.invalid'),
  },
}))

function commit(edge: Edge): void {
  const current = range.value
  if (current.kind !== 'time' && current.kind !== 'frames') return
  const text = texts[edge].trim()
  // The field shows a converted time to the millisecond: as it is, it changes nothing.
  if (text === shown(edge)) {
    unparsed[edge] = false
    return
  }
  let value: number | null = null
  if (text !== '') {
    value = current.kind === 'time' ? parseTime(text) : parseFrame(text)
    if (value === null) {
      unparsed[edge] = true
      return
    }
  } else if (edge === 'start') {
    value = 0
  }
  unparsed[edge] = false
  editor.setRange({ ...current, [edge]: value })
  texts[edge] = shown(edge)
}

function fieldIssues(edge: Edge): ValidationIssue[] {
  const path: RangePath = `range.${edge}`
  const own = issuesAt(path)
  if (!unparsed[edge]) return own
  const message = fieldText.value[range.value.kind === 'frames' ? 'frames' : 'time'].invalid
  return [{ severity: 'error', code: 'range.text', path, message }, ...own]
}

function trigger(): HTMLElement | null {
  return root.value?.querySelector<HTMLElement>('[data-field="range"]') ?? null
}

function toggle(event: Event): void {
  popover.value?.toggle(event)
}

function focusMode(): void {
  const body = document.getElementById(bodyId)
  const checked = body?.querySelector<HTMLElement>('input[type="radio"]:checked')
  ;(checked ?? body?.querySelector<HTMLElement>('input, button'))?.focus()
}

async function shownPopover(): Promise<void> {
  open.value = true
  converted = null
  await nextTick()
  focusMode()
}

// An undo or *Reset to group* can take the focused control away: the focus stays inside.
watch(
  () => range.value.kind,
  () => {
    if (open.value && document.activeElement === document.body) focusMode()
  },
  { flush: 'post' },
)

function hidden(): void {
  open.value = false
  // The popover goes away with the focus in it: the focus goes back to the button. Not before
  // this key's events end: an Enter that reached the button would open it again.
  const focused = document.activeElement
  const panel = document.getElementById(bodyId)?.closest('.range-popover')
  if (focused === document.body || panel?.contains(focused)) setTimeout(() => trigger()?.focus())
}

function reset(): void {
  editor.resetRangeToGroup()
}
</script>

<template>
  <div ref="root" class="range-selector">
    <Button
      class="range-selector__trigger"
      :class="severity && `range-selector__trigger--${severity}`"
      severity="secondary"
      outlined
      size="small"
      data-field="range"
      :data-kind="range.kind"
      :data-state="editor.rangeOverridden ? 'overridden' : undefined"
      :aria-label="buttonLabel"
      :aria-describedby="description ? describedId : undefined"
      aria-haspopup="dialog"
      :aria-expanded="open"
      :aria-controls="open ? bodyId : undefined"
      @click="toggle"
    >
      <span v-if="editor.rangeOverridden" class="range-selector__override" aria-hidden="true" />
      <component
        :is="SEVERITY_ICON[severity]"
        v-if="severity"
        class="range-selector__severity"
        :size="14"
        aria-hidden="true"
      />
      <span class="range-selector__label" data-field="range-label">{{ label }}</span
      >{{ ' '
      }}<span v-if="length !== null" class="range-selector__length" data-field="range-length">{{
        length
      }}</span>
      <ChevronDown :size="16" aria-hidden="true" />
    </Button>
    <span :id="describedId" class="rf-sr-only">{{ description }}</span>
    <Popover
      ref="popover"
      class="range-popover"
      :pt="{ root: { 'aria-labelledby': titleId } }"
      @show="shownPopover"
      @hide="hidden"
    >
      <div :id="bodyId" class="range-popover__body">
        <h2 :id="titleId" class="range-popover__title">{{ t('range.title') }}</h2>
        <p v-if="inGroup" class="range-popover__note">{{ t('range.fileOnly') }}</p>
        <Field
          :label="t('range.mode')"
          path="range"
          stacked
          :overridden="false"
          :issues="issuesAt('range')"
        >
          <template #default="{ labelId, describedBy }">
            <div
              class="range-popover__modes"
              role="radiogroup"
              :aria-labelledby="labelId"
              :aria-describedby="describedBy"
            >
              <div v-for="mode in modes" :key="mode.kind" class="range-popover__mode">
                <RadioButton
                  :model-value="range.kind"
                  :input-id="`${id}-mode-${mode.kind}`"
                  :name="`${id}-mode`"
                  :value="mode.kind"
                  :disabled="mode.reason !== null"
                  :pt="{
                    input: {
                      'data-range-mode': mode.kind,
                      tabindex: modeTabindex(mode.kind),
                      'aria-disabled': mode.reason !== null ? 'true' : undefined,
                      'aria-describedby':
                        mode.reason !== null ? `${id}-reason-${mode.kind}` : undefined,
                    },
                  }"
                  @update:model-value="chooseMode(mode.kind)"
                />
                <label :for="`${id}-mode-${mode.kind}`">{{ mode.label }}</label>
                <small
                  v-if="mode.reason !== null"
                  :id="`${id}-reason-${mode.kind}`"
                  class="range-popover__reason"
                  :data-range-reason="mode.kind"
                  >{{ mode.reason }}</small
                >
              </div>
            </div>
          </template>
        </Field>

        <template v-if="range.kind === 'chapters'">
          <Field
            :label="t('range.chapters.from')"
            path="range.start"
            :overridden="false"
            :issues="issuesAt('range.start')"
          >
            <template #default="{ id: inputId, labelId, invalid }">
              <Select
                :model-value="range.start"
                :options="chapterOptions"
                option-label="label"
                option-value="value"
                :input-id="inputId"
                :ariaLabelledby="labelId"
                :invalid="invalid"
                fluid
                @update:model-value="chooseChapter('start', $event)"
              />
            </template>
          </Field>
          <Field
            :label="t('range.chapters.to')"
            path="range.end"
            :overridden="false"
            :issues="issuesAt('range.end')"
          >
            <template #default="{ id: inputId, labelId, invalid }">
              <Select
                :model-value="range.end"
                :options="chapterOptions"
                option-label="label"
                option-value="value"
                :input-id="inputId"
                :ariaLabelledby="labelId"
                :invalid="invalid"
                fluid
                @update:model-value="chooseChapter('end', $event)"
              />
            </template>
          </Field>
        </template>

        <template v-else-if="range.kind === 'time' || range.kind === 'frames'">
          <p :id="helpId" class="range-popover__help">{{ fieldText[range.kind].help }}</p>
          <Field
            v-for="edge in EDGES"
            :key="`${range.kind}-${edge}`"
            :label="fieldText[range.kind][edge]"
            :path="`range.${edge}`"
            :description="helpId"
            :overridden="false"
            :issues="fieldIssues(edge)"
          >
            <template #default="{ id: inputId, invalid }">
              <InputText
                :model-value="texts[edge]"
                :id="inputId"
                :inputmode="range.kind === 'frames' ? 'numeric' : 'text'"
                :placeholder="edge === 'end' ? fieldText[range.kind].toEnd : undefined"
                :invalid="invalid"
                fluid
                @update:model-value="texts[edge] = $event ?? ''"
                @change="commit(edge)"
                @keydown.enter="commit(edge)"
              />
            </template>
          </Field>
        </template>

        <p class="range-popover__length">
          {{ length === null ? t('range.lengthUnknown') : t('range.length', { length }) }}
        </p>
        <Button
          v-if="editor.rangeOverridden"
          class="range-popover__reset"
          size="small"
          severity="secondary"
          text
          :label="t('range.reset')"
          data-action="range-reset"
          @click="reset"
        />
      </div>
    </Popover>
  </div>
</template>

<style scoped>
.range-selector {
  display: inline-flex;
  align-items: center;
  min-width: 0;
}

.range-selector__trigger {
  gap: var(--rf-space-2);
  max-width: 24rem;
}

.range-selector__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.range-selector__length {
  color: var(--rf-color-text-muted);
  font-variant-numeric: tabular-nums;
}

.range-selector__override {
  flex: none;
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: var(--rf-color-primary);
}

.range-selector__severity {
  flex: none;
}

.range-selector__trigger--error {
  --p-button-outlined-secondary-border-color: var(--p-status-error-border-color);
}

.range-selector__trigger--error .range-selector__severity {
  color: var(--p-status-error-color);
}

.range-selector__trigger--warning {
  --p-button-outlined-secondary-border-color: var(--p-status-warn-border-color);
}

.range-selector__trigger--warning .range-selector__severity {
  color: var(--p-status-warn-color);
}

.range-selector__trigger--info .range-selector__severity {
  color: var(--p-status-info-color);
}

.range-popover__body {
  display: grid;
  gap: var(--rf-space-3);
  width: min(32rem, 90vw);
}

.range-popover__title {
  margin: 0;
  font-size: var(--rf-font-size-md);
}

.range-popover__note,
.range-popover__help,
.range-popover__length {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.range-popover__modes {
  display: grid;
  gap: var(--rf-space-2);
}

.range-popover__mode {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  column-gap: var(--rf-space-2);
}

.range-popover__reason {
  grid-column: 2;
  color: var(--rf-color-text-muted);
}

.range-popover__reset {
  justify-self: start;
}
</style>
