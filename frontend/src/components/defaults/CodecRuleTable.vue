<script setup lang="ts">
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  GripVertical,
  Lock,
  Plus,
  Trash2,
} from '@lucide/vue'
import Button from 'primevue/button'
import InputNumber from 'primevue/inputnumber'
import Select from 'primevue/select'
import vTooltip from 'primevue/tooltip'
import { computed, nextTick, ref, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { AudioCodecRule, ValidationIssue } from '@/api/types'
import { describeTag } from '@/components/language/catalog'
import LanguagePicker from '@/components/language/LanguagePicker.vue'
import { useDefaultsStore } from '@/stores/defaults'
import { useSystemStore } from '@/stores/system'

import CodecRuleExtras from './CodecRuleExtras.vue'
import { useCodecOptions } from './codecs'
import IssueLines from './IssueLines.vue'
import { rulePath } from './model'
import { useDefaultsOptions } from './options'

/**
 * The codec rules, first match wins: drag or the arrow buttons reorder them, the catch-all stays
 * last and cannot be removed, and each row expands to its optional settings.
 */
const { t } = useI18n()
const defaults = useDefaultsStore()
const system = useSystemStore()
const choices = useDefaultsOptions()
const codecs = useCodecOptions()
const id = useId()
const root = useTemplateRef<HTMLElement>('root')

const expanded = ref<ReadonlySet<number>>(new Set())
const dragFrom = ref<number | null>(null)
const dropAt = ref<number | null>(null)
const announcement = ref('')

interface Row {
  rule: AudioCodecRule
  index: number
  key: number
  number: number
  catchAll: boolean
  issues: ValidationIssue[]
}

const rows = computed<Row[]>(() => {
  const list = defaults.audio?.codec_rules ?? []
  return list.map((rule, index) => {
    const key = defaults.ruleKeys[index] ?? -(index + 1)
    const at = rulePath(key)
    return {
      rule,
      index,
      key,
      number: index + 1,
      catchAll: index === list.length - 1,
      issues: defaults.issues
        .filter((placed) => placed.at === at || placed.at.startsWith(`${at}.`))
        .map((placed) => placed.issue),
    }
  })
})
const lastMovable = computed(() => rows.value.length - 2)
const locked = computed(() => defaults.readOnly)
const container = computed(() => defaults.container ?? undefined)

const col = (name: string) => `${id}-col-${name}`
const rowId = (key: number) => `${id}-rule-${key}`
const issuesId = (key: number) => `${id}-issues-${key}`
const labelled = (name: string, key: number) => `${col(name)} ${rowId(key)}`

function names(rule: AudioCodecRule): string {
  return (rule.languages ?? [])
    .map((tag) => describeTag(system.languages, tag)?.english_name ?? tag)
    .join(', ')
}

function fieldError(row: Row, field: string): boolean {
  const at = `${rulePath(row.key)}.${field}`
  return defaults.issuesAt(at).some((issue) => issue.severity === 'error')
}

function set(row: Row, next: Partial<AudioCodecRule>): void {
  defaults.setRule(row.index, { ...row.rule, ...next })
}

function setLanguage(row: Row, tag: string | null): void {
  set(row, { languages: tag === null ? null : [tag] })
}

function setMax(row: Row, value: unknown): void {
  const max = typeof value === 'number' && value > 0 ? value : null
  if (max !== (row.rule.max_bitrate ?? null)) set(row, { max_bitrate: max })
}

function toggle(key: number): void {
  const next = new Set(expanded.value)
  if (!next.delete(key)) next.add(key)
  expanded.value = next
}

function expand(key: number): void {
  if (!expanded.value.has(key)) toggle(key)
}

async function focusIn(key: number, selectors: string[]): Promise<void> {
  await nextTick()
  const body = root.value?.querySelector(`[data-rule-key="${key}"]`)
  for (const selector of selectors) {
    const found = body?.querySelector<HTMLElement>(`${selector}:not(:disabled)`)
    if (found) {
      found.focus()
      return
    }
  }
}

function announceMove(row: Row, to: number): void {
  announcement.value = t('defaults.rules.moved', { n: row.number, position: to + 1 })
}

/** A move from the buttons keeps the focus on the moved rule's button. */
function move(row: Row, to: number): void {
  if (row.catchAll || to < 0 || to > lastMovable.value || to === row.index) return
  defaults.moveRule(row.index, to)
  announceMove(row, to)
  const first = to < row.index ? '[data-move="up"]' : '[data-move="down"]'
  const other = to < row.index ? '[data-move="down"]' : '[data-move="up"]'
  void focusIn(row.key, [first, other])
}

async function remove(row: Row): Promise<void> {
  if (row.catchAll) return
  defaults.removeRule(row.index)
  announcement.value = t('defaults.rules.removed', { n: row.number })
  const next = rows.value[row.index]
  if (next !== undefined && !next.catchAll) {
    await focusIn(next.key, ['[data-action="remove"]'])
    return
  }
  await nextTick()
  root.value?.querySelector<HTMLElement>('[data-action="add-rule"]')?.focus()
}

async function add(): Promise<void> {
  const key = defaults.addRule()
  announcement.value = t('defaults.rules.added')
  await focusIn(key, ['[data-field="language"] button'])
}

function onDragStart(event: DragEvent, row: Row): void {
  if (locked.value || row.catchAll) {
    event.preventDefault()
    return
  }
  dragFrom.value = row.index
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(row.number))
    const line = (event.target as HTMLElement).closest('tr')
    if (line) event.dataTransfer.setDragImage(line, 16, 16)
  }
}

function onDragOver(event: DragEvent, row: Row): void {
  if (dragFrom.value === null || row.catchAll) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dropAt.value = row.index
}

function onDrop(event: DragEvent, row: Row): void {
  if (dragFrom.value === null || row.catchAll) return
  event.preventDefault()
  const from = rows.value[dragFrom.value]
  endDrag()
  if (from !== undefined && from.index !== row.index) {
    defaults.moveRule(from.index, row.index)
    announceMove(from, row.index)
  }
}

function endDrag(): void {
  dragFrom.value = null
  dropAt.value = null
}

/** Where the dragged rule would land: above the row when it comes from below. */
function dropSide(index: number): 'before' | 'after' | null {
  if (dragFrom.value === null || dropAt.value !== index || dragFrom.value === index) return null
  return dragFrom.value > index ? 'before' : 'after'
}
</script>

<template>
  <div ref="root" class="rule-table">
    <div class="rule-table__scroll">
      <table class="rule-table__table" :aria-label="t('defaults.rules.title')">
        <thead>
          <tr>
            <th scope="col" class="rule-table__narrow">
              <span class="rf-sr-only">{{ t('defaults.rules.dragColumn') }}</span>
            </th>
            <th :id="col('number')" scope="col" class="rule-table__narrow">
              {{ t('defaults.rules.number') }}
            </th>
            <th :id="col('language')" scope="col">{{ t('defaults.rules.language') }}</th>
            <th :id="col('channels')" scope="col">{{ t('defaults.rules.channels') }}</th>
            <th :id="col('codec')" scope="col">{{ t('defaults.rules.codec') }}</th>
            <th :id="col('mixdown')" scope="col">{{ t('defaults.rules.mixdown') }}</th>
            <th :id="col('max')" scope="col">{{ t('defaults.rules.maxBitrate') }}</th>
            <th :id="col('fits')" scope="col">{{ t('defaults.rules.ifFits') }}</th>
            <th scope="col">
              <span class="rf-sr-only">{{ t('defaults.rules.actions') }}</span>
            </th>
          </tr>
        </thead>
        <tbody
          v-for="row in rows"
          :key="row.key"
          class="rule-table__rule"
          :class="[
            dropSide(row.index) && `rule-table__rule--drop-${dropSide(row.index)}`,
            { 'rule-table__rule--dragging': dragFrom === row.index },
          ]"
          :data-rule-key="row.key"
          :data-index="row.index"
          :data-catch-all="row.catchAll || undefined"
          @dragover="onDragOver($event, row)"
          @drop="onDrop($event, row)"
        >
          <tr>
            <td class="rule-table__narrow">
              <span
                v-if="row.catchAll"
                v-tooltip.top="t('defaults.rules.catchAllLocked')"
                class="rule-table__lock"
                role="img"
                :aria-label="t('defaults.rules.catchAllLocked')"
                data-role="locked"
              >
                <Lock :size="16" aria-hidden="true" />
              </span>
              <span
                v-else
                v-tooltip.top="t('defaults.rules.drag')"
                class="rule-table__handle"
                :draggable="!locked"
                data-role="drag"
                @dragstart="onDragStart($event, row)"
                @dragend="endDrag"
              >
                <GripVertical :size="16" aria-hidden="true" />
              </span>
            </td>
            <th :id="rowId(row.key)" scope="row" class="rule-table__number">
              <span class="rf-sr-only">{{ t('defaults.rules.rule') }} </span>{{ row.number }}
            </th>
            <td data-field="language">
              <span v-if="row.catchAll" class="rule-table__any">
                {{ t('defaults.rules.anyLanguage') }}
              </span>
              <LanguagePicker
                v-else-if="(row.rule.languages ?? []).length <= 1"
                :model-value="row.rule.languages?.[0] ?? null"
                clearable
                :none-label="t('defaults.rules.anyLanguage')"
                :labelledby="labelled('language', row.key)"
                :disabled="locked"
                :container="container"
                :invalid="fieldError(row, 'languages')"
                @update:model-value="setLanguage(row, $event)"
              />
              <Button
                v-else
                link
                size="small"
                class="rule-table__languages"
                :label="names(row.rule)"
                :aria-label="t('defaults.rules.editLanguages', { n: row.number })"
                @click="expand(row.key)"
              />
            </td>
            <td data-field="channels">
              <span v-if="row.catchAll" class="rule-table__any">
                {{ t('defaults.rules.anyChannels') }}
              </span>
              <Select
                v-else
                :model-value="row.rule.source_channels"
                :options="choices.sourceChannels"
                option-label="label"
                option-value="value"
                :ariaLabelledby="labelled('channels', row.key)"
                :disabled="locked"
                :invalid="fieldError(row, 'source_channels')"
                @update:model-value="set(row, { source_channels: $event })"
              />
            </td>
            <td data-field="codec">
              <Select
                :model-value="row.rule.codec"
                :options="codecs.options(row.rule.codec)"
                option-label="label"
                option-value="value"
                :ariaLabelledby="labelled('codec', row.key)"
                :disabled="locked"
                :invalid="fieldError(row, 'codec')"
                @update:model-value="set(row, { codec: $event })"
              />
            </td>
            <td data-field="mixdown">
              <Select
                :model-value="row.rule.mixdown"
                :options="choices.mixdown"
                option-label="label"
                option-value="value"
                :ariaLabelledby="labelled('mixdown', row.key)"
                :disabled="locked"
                :invalid="fieldError(row, 'mixdown')"
                @update:model-value="set(row, { mixdown: $event })"
              />
            </td>
            <td data-field="max_bitrate">
              <InputNumber
                class="rule-table__number-input"
                :model-value="row.rule.max_bitrate ?? null"
                :min="1"
                :max="10000"
                :use-grouping="false"
                :suffix="t('defaults.units.kbpsSuffix')"
                :placeholder="t('defaults.rules.noMax')"
                :ariaLabelledby="labelled('max', row.key)"
                :disabled="locked"
                :invalid="fieldError(row, 'max_bitrate')"
                @input="setMax(row, $event.value)"
                @update:model-value="setMax(row, $event)"
              />
            </td>
            <td data-field="if_fits">
              <Select
                :model-value="row.rule.if_fits"
                :options="choices.ifFits"
                option-label="label"
                option-value="value"
                :ariaLabelledby="labelled('fits', row.key)"
                :disabled="locked"
                @update:model-value="set(row, { if_fits: $event })"
              />
            </td>
            <td class="rule-table__actions">
              <Button
                text
                rounded
                size="small"
                severity="secondary"
                data-action="expand"
                :aria-expanded="expanded.has(row.key)"
                :aria-controls="expanded.has(row.key) ? `${id}-extras-${row.key}` : undefined"
                :aria-label="t('defaults.rules.more', { n: row.number })"
                @click="toggle(row.key)"
              >
                <template #icon>
                  <ChevronDown v-if="expanded.has(row.key)" :size="16" aria-hidden="true" />
                  <ChevronRight v-else :size="16" aria-hidden="true" />
                </template>
              </Button>
              <Button
                text
                rounded
                size="small"
                severity="secondary"
                data-move="up"
                :disabled="locked || row.catchAll || row.index === 0"
                :aria-label="t('defaults.rules.moveUp', { n: row.number })"
                @click="move(row, row.index - 1)"
              >
                <template #icon><ArrowUp :size="16" aria-hidden="true" /></template>
              </Button>
              <Button
                text
                rounded
                size="small"
                severity="secondary"
                data-move="down"
                :disabled="locked || row.catchAll || row.index >= lastMovable"
                :aria-label="t('defaults.rules.moveDown', { n: row.number })"
                @click="move(row, row.index + 1)"
              >
                <template #icon><ArrowDown :size="16" aria-hidden="true" /></template>
              </Button>
              <Button
                text
                rounded
                size="small"
                severity="secondary"
                data-action="remove"
                :disabled="locked || row.catchAll"
                :aria-label="t('defaults.rules.remove', { n: row.number })"
                @click="remove(row)"
              >
                <template #icon><Trash2 :size="16" aria-hidden="true" /></template>
              </Button>
            </td>
          </tr>
          <tr v-if="row.issues.length > 0" class="rule-table__issues">
            <td />
            <td colspan="8">
              <IssueLines :id="issuesId(row.key)" :issues="row.issues" fixes />
            </td>
          </tr>
          <tr
            v-if="expanded.has(row.key)"
            :id="`${id}-extras-${row.key}`"
            class="rule-table__extras"
          >
            <td />
            <td colspan="8">
              <CodecRuleExtras
                :rule="row.rule"
                :index="row.index"
                :rule-key="row.key"
                :catch-all="row.catchAll"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <Button
      class="rule-table__add"
      size="small"
      severity="secondary"
      outlined
      data-action="add-rule"
      :label="t('defaults.rules.add')"
      :disabled="locked"
      @click="add"
    >
      <template #icon><Plus :size="16" aria-hidden="true" /></template>
    </Button>
    <span class="rf-sr-only" aria-live="polite">{{ announcement }}</span>
  </div>
</template>

<style scoped>
.rule-table {
  display: grid;
  gap: var(--rf-space-2);
  justify-items: start;
}

.rule-table__scroll {
  width: 100%;
  overflow-x: auto;
}

.rule-table__table {
  width: 100%;
  border-collapse: collapse;
}

.rule-table__table th,
.rule-table__table td {
  padding: var(--rf-space-1) var(--rf-space-2);
  text-align: start;
  vertical-align: middle;
}

.rule-table__table thead th {
  border-bottom: 1px solid var(--rf-color-border);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  font-weight: var(--rf-font-weight-medium);
  white-space: nowrap;
}

.rule-table__rule {
  position: relative;
  border-bottom: 1px solid var(--rf-color-border);
}

.rule-table__rule--dragging {
  opacity: 0.5;
}

.rule-table__rule--drop-before {
  box-shadow: inset 0 2px 0 var(--rf-color-primary);
}

.rule-table__rule--drop-after {
  box-shadow: inset 0 -2px 0 var(--rf-color-primary);
}

.rule-table__narrow {
  width: 2rem;
}

.rule-table__number {
  color: var(--rf-color-text-muted);
  font-variant-numeric: tabular-nums;
  font-weight: var(--rf-font-weight-normal);
}

.rule-table__handle {
  display: inline-flex;
  color: var(--rf-color-text-muted);
  cursor: grab;
}

.rule-table__handle[draggable='false'] {
  cursor: default;
}

.rule-table__lock {
  display: inline-flex;
  color: var(--rf-color-text-muted);
}

.rule-table__any {
  color: var(--rf-color-text-muted);
  white-space: nowrap;
}

.rule-table__languages {
  padding-inline: 0;
  text-align: start;
}

.rule-table__number-input :deep(input) {
  width: 7.5rem;
}

.rule-table__actions {
  white-space: nowrap;
}

.rule-table__issues td,
.rule-table__extras td {
  padding-top: 0;
  padding-bottom: var(--rf-space-2);
}
</style>
