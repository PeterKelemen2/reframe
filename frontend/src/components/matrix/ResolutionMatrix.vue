<script setup lang="ts">
import { Hand, Pencil } from '@lucide/vue'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import Popover from 'primevue/popover'
import { computed, nextTick, onMounted, ref, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type {
  BatchResolution,
  MatrixColumn,
  Resolution,
  SourceEntry,
  TrackMatch,
} from '@/api/types'
import { fileName, formatList } from '@/components/shell/format'
import { useEditorStore } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'

import CandidatePicker from './CandidatePicker.vue'
import {
  MATCH_MARK,
  matchOf,
  NAME_FIELDS,
  nameIssues,
  pickedByHand,
  ROW_MARK,
  rowLabels,
  sortRows,
} from './matrix'
import NameFields from './NameFields.vue'
import RowIssues from './RowIssues.vue'

/**
 * One row per file and one column per output track, virtualised. Every cell with an action is
 * a button, reached with Tab; its popover holds the candidate picker, the row's issues or the
 * name fields.
 */
const props = defineProps<{
  resolution: BatchResolution
  problemsOnly: boolean
  /** The source id of the row to scroll to and focus first. */
  focus: string | null
}>()

const { t, locale } = useI18n()
const editor = useEditorStore()
const sources = useSourcesStore()

/** Fixed, so that the virtual scroller can place rows without measuring them. */
const ROW_HEIGHT = 60

interface MatrixRow {
  path: string
  row: Resolution
  entry: SourceEntry | undefined
  label: string
  /** By column: the rule's match in this file (none for V and the name). */
  cells: (TrackMatch | undefined)[]
}

const columns = computed(() => props.resolution.columns ?? [])

const allRows = computed<MatrixRow[]>(() => {
  const rows = props.resolution.rows ?? []
  const labels = rowLabels(rows, props.resolution.group?.members ?? [])
  const byPath = new Map(sources.entries.map((entry) => [entry.path, entry]))
  return rows.map((row, index) => ({
    path: row.path,
    row,
    entry: byPath.get(row.path),
    label: labels[index] ?? fileName(row.path),
    cells: columns.value.map((column) => matchOf(row, column)),
  }))
})

/** `null`: episode order; `c<i>`: the status of column `i`. */
const sortField = ref<string | null>(null)
const sortOrder = ref<1 | -1>(1)

const shownRows = computed(() => {
  const rows = props.problemsOnly
    ? allRows.value.filter((item) => item.row.status !== 'ok')
    : allRows.value
  const column = sortField.value?.startsWith('c') ? Number(sortField.value.slice(1)) : null
  return sortRows(rows, columns.value, column, sortOrder.value)
})

function onSort(event: { sortField?: unknown; sortOrder?: number | null }): void {
  sortField.value = typeof event.sortField === 'string' ? event.sortField : null
  sortOrder.value = event.sortOrder === -1 ? -1 : 1
}

function rowState(row: Resolution): string {
  switch (row.status) {
    case 'ok':
      return t('matrix.row.ok')
    case 'warning':
      return t('matrix.row.warning')
    case 'error':
      return t('matrix.row.error')
  }
}

function matchState(status: keyof typeof MATCH_MARK): string {
  switch (status) {
    case 'exact':
      return t('matrix.match.exact')
    case 'relaxed':
      return t('matrix.match.relaxed')
    case 'ambiguous':
      return t('matrix.match.ambiguous')
    case 'missing':
      return t('matrix.match.missing')
    case 'skipped':
      return t('matrix.match.skipped')
  }
}

function streamsText(streams: number[] | undefined): string {
  return (streams ?? []).map((stream) => `#${stream}`).join(' ')
}

function videoSize(item: MatrixRow): string {
  const video = item.entry?.source?.video?.[0]
  return video === undefined ? '' : `${video.width}×${video.height}`
}

function picked(item: MatrixRow, column: MatrixColumn): boolean {
  const target = editor.target
  if (target?.kind !== 'group' || item.entry === undefined) return false
  if (column.kind !== 'audio' && column.kind !== 'subtitle') return false
  return pickedByHand(target.overrides[item.entry.id], column.kind, column.rule ?? -1)
}

function cellLabel(item: MatrixRow, column: MatrixColumn, match: TrackMatch): string {
  const state = [matchState(match.status), streamsText(match.streams), match.message]
  if (picked(item, column)) state.push(t('matrix.cell.picked'))
  return t('matrix.cell.open', {
    column: column.label,
    label: item.label,
    state: formatList(
      state.filter((part): part is string => Boolean(part)),
      locale.value,
    ),
  })
}

function firstError(row: Resolution): string {
  return row.issues?.find((issue) => issue.severity === 'error')?.message ?? ''
}

function fieldValue(row: Resolution, field: (typeof NAME_FIELDS)[number]): string | null {
  const value = row.naming?.fields?.[field]
  return value === null || value === undefined ? null : String(value)
}

/** `{season}`, as the naming template writes the field. */
function variable(field: string): string {
  return `{${field}}`
}

type Panel =
  | { kind: 'cell'; path: string; column: number }
  | { kind: 'issues'; path: string }
  | { kind: 'name'; path: string }

const popover = useTemplateRef<InstanceType<typeof Popover>>('popover')
const titleId = `${useId()}-title`
const panel = ref<Panel | null>(null)
const popoverOpen = ref(false)
/** The `data-focus-key` of the button the popover belongs to. */
let anchorKey: string | null = null

/** The open panel's row as the newest resolution has it. */
const panelRow = computed(() =>
  panel.value === null ? undefined : allRows.value.find((item) => item.path === panel.value?.path),
)

const cellPanel = computed(() => {
  const item = panelRow.value
  if (panel.value?.kind !== 'cell' || item === undefined) return null
  const column = columns.value[panel.value.column]
  const match = item.cells[panel.value.column]
  if (column === undefined || match === undefined) return null
  const source = item.entry?.source
  return {
    column,
    match,
    tracks: (match.kind === 'audio' ? source?.audio : source?.subtitles) ?? [],
    picked: picked(item, column),
  }
})

async function openPanel(next: Panel, event: Event): Promise<void> {
  const target = event.currentTarget as HTMLElement
  if (popoverOpen.value && target.dataset.focusKey === anchorKey) {
    popover.value?.hide()
    return
  }
  const moving = popoverOpen.value
  anchorKey = target.dataset.focusKey ?? null
  panel.value = next
  popover.value?.show(event, target)
  if (!moving) return
  // An open popover neither moves nor takes the focus when it gets another target.
  await nextTick()
  popover.value?.alignOverlay()
  document.querySelector<HTMLElement>('.matrix-popover [autofocus]')?.focus()
}

function closePanel(): void {
  popover.value?.hide()
  focusKey(anchorKey)
}

function focusKey(key: string | null): void {
  if (key === null) return
  root.value?.querySelector<HTMLElement>(`[data-focus-key="${CSS.escape(key)}"]`)?.focus()
}

// The DataTable renders its cells anew for every resolution, and the focused button goes with
// them: the same cell of the new rows takes the focus back.
let focusedKey: string | null = null
function onFocusin(event: FocusEvent): void {
  focusedKey = (event.target as HTMLElement).dataset.focusKey ?? null
}
watch(
  allRows,
  () => {
    if (document.activeElement === document.body) focusKey(focusedKey)
  },
  { flush: 'post' },
)

/** Escape with the focus still on the cell closes the popover, not the matrix around it. */
function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape' || !popoverOpen.value) return
  event.preventDefault()
  closePanel()
}

const root = useTemplateRef<HTMLElement>('root')

onMounted(async () => {
  if (props.focus === null) return
  const index = shownRows.value.findIndex((item) => item.entry?.id === props.focus)
  if (index === -1) return
  root.value
    ?.querySelector('[data-pc-name="virtualscroller"]')
    ?.scrollTo({ top: index * ROW_HEIGHT })
  await nextTick()
  document.querySelector<HTMLElement>(`[data-row-mark="${props.focus}"]`)?.focus()
})
</script>

<template>
  <div ref="root" class="matrix" @keydown="onKeydown" @focusin="onFocusin">
    <p class="rf-sr-only">{{ t('matrix.keyboard') }}</p>
    <p v-if="shownRows.length === 0" class="matrix__empty" data-state="empty">
      {{ t('matrix.noProblems') }}
    </p>
    <DataTable
      v-else
      :value="shownRows"
      data-key="path"
      lazy
      scrollable
      scroll-height="flex"
      :virtual-scroller-options="{ itemSize: ROW_HEIGHT }"
      :sort-field="sortField ?? undefined"
      :sort-order="sortOrder"
      :table-props="{ 'aria-label': t('matrix.table') }"
      class="matrix__table"
      @sort="onSort"
    >
      <Column field="file" :header="t('matrix.column.file')" sortable frozen>
        <template #body="{ data }">
          <button
            type="button"
            class="matrix__file"
            :data-status="data.row.status"
            :data-row-mark="data.entry?.id"
            :data-focus-key="`${data.path}|file`"
            :disabled="data.entry === undefined"
            :autofocus="
              (focus === null ? data.path === shownRows[0]?.path : data.entry?.id === focus) ||
              undefined
            "
            :aria-label="t('matrix.row.issues', { label: data.label, status: rowState(data.row) })"
            @click="openPanel({ kind: 'issues', path: data.path }, $event)"
          >
            <span class="matrix__mark" aria-hidden="true">{{
              ROW_MARK[(data.row as Resolution).status]
            }}</span>
            <span class="matrix__label" dir="ltr">{{ data.label }}</span>
          </button>
        </template>
      </Column>
      <Column
        v-for="(column, index) in columns"
        :key="`${column.kind}:${column.rule}`"
        :field="`c${index}`"
        :header="column.label"
        :sortable="column.kind !== 'video'"
      >
        <template #body="{ data }">
          <span v-if="data.row.job == null && column.kind === 'video'" class="matrix__unread">
            {{ firstError(data.row) || t('matrix.row.unreadable') }}
          </span>
          <span
            v-else-if="column.kind === 'video'"
            class="matrix__video"
            :aria-label="
              t('matrix.cell.video', {
                column: column.label,
                label: data.label,
                state: t('matrix.match.exact'),
                size: videoSize(data),
              })
            "
          >
            <span class="matrix__mark matrix__mark--exact" aria-hidden="true">✓</span>
            {{ videoSize(data) }}
          </span>
          <div v-else-if="column.kind === 'name' && data.row.job" class="matrix__name">
            <button
              type="button"
              class="matrix__edit"
              data-role="edit-name"
              :data-focus-key="`${data.path}|name`"
              :disabled="data.entry === undefined"
              :aria-label="t('matrix.name.edit', { label: data.label })"
              @click="openPanel({ kind: 'name', path: data.path }, $event)"
            >
              <Pencil :size="14" aria-hidden="true" />
            </button>
            <span class="matrix__output" dir="ltr" :data-status="nameIssues(data.row)[0]?.severity">
              {{ fileName(data.row.job.output?.path ?? '') }}
            </span>
            <span v-if="data.row.naming" class="matrix__naming">
              <span class="matrix__source">
                {{
                  data.row.naming.source === 'file'
                    ? t('matrix.name.file')
                    : t('matrix.name.folder')
                }}
              </span>
              <template v-for="field in NAME_FIELDS" :key="field">
                <span
                  v-if="fieldValue(data.row, field) !== null"
                  class="matrix__field"
                  :data-field="field"
                >
                  <span class="matrix__variable">{{ variable(field) }}</span>
                  {{ fieldValue(data.row, field) }}
                </span>
              </template>
            </span>
          </div>
          <button
            v-else-if="data.cells[index]"
            type="button"
            class="matrix__cell"
            :data-status="data.cells[index].status"
            :data-cell="`${column.kind}:${column.rule}`"
            :data-focus-key="`${data.path}|${column.kind}:${column.rule}`"
            :disabled="data.entry === undefined"
            :aria-label="cellLabel(data, column, data.cells[index])"
            @click="openPanel({ kind: 'cell', path: data.path, column: index }, $event)"
          >
            <span class="matrix__track">
              <span class="matrix__mark" aria-hidden="true">{{
                MATCH_MARK[(data.cells[index] as TrackMatch).status]
              }}</span>
              <span>{{ streamsText(data.cells[index].streams) || t('matrix.cell.none') }}</span>
              <Hand
                v-if="picked(data, column)"
                :size="14"
                aria-hidden="true"
                data-role="picked"
              /> </span
            >{{ ' '
            }}<span class="matrix__message" :title="data.cells[index].message">
              {{ data.cells[index].message }}
            </span>
          </button>
        </template>
      </Column>
    </DataTable>

    <Popover
      ref="popover"
      class="matrix-popover"
      :pt="{ root: { 'aria-labelledby': titleId } }"
      @show="popoverOpen = true"
      @hide="popoverOpen = false"
    >
      <template v-if="panel !== null && panelRow?.entry !== undefined">
        <CandidatePicker
          v-if="cellPanel !== null"
          :title-id="titleId"
          :source-id="panelRow.entry.id"
          :label="panelRow.label"
          :column="cellPanel.column"
          :match="cellPanel.match"
          :tracks="cellPanel.tracks"
          :picked="cellPanel.picked"
          @done="closePanel"
        />
        <RowIssues
          v-else-if="panel.kind === 'issues'"
          :title-id="titleId"
          :source-id="panelRow.entry.id"
          :label="panelRow.label"
          :issues="panelRow.row.issues ?? []"
          @done="closePanel"
        />
        <NameFields
          v-else-if="panel.kind === 'name' && panelRow.row.naming"
          :title-id="titleId"
          :source-id="panelRow.entry.id"
          :label="panelRow.label"
          :naming="panelRow.row.naming"
          :overrides="panelRow.row.job?.output?.naming?.field_overrides ?? {}"
          :issues="panelRow.row.issues ?? []"
        />
      </template>
    </Popover>
  </div>
</template>

<style scoped>
.matrix {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
}

.matrix__empty {
  color: var(--rf-color-text-muted);
}

.matrix__table {
  flex: 1 1 auto;
  min-height: 0;
}
.matrix__table :deep(tbody tr) {
  height: 60px;
}

.matrix__table :deep(td),
.matrix__table :deep(th) {
  padding: var(--rf-space-1) var(--rf-space-2);
  white-space: nowrap;
}

.matrix__file,
.matrix__cell,
.matrix__edit {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
  padding: var(--rf-space-1);
  border: 1px solid transparent;
  border-radius: var(--rf-radius-sm);
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.matrix__file:hover,
.matrix__cell:hover,
.matrix__edit:hover {
  border-color: var(--rf-color-border);
  background: var(--rf-color-surface-hover);
}

.matrix__cell {
  flex-direction: column;
  align-items: flex-start;
  gap: 0;
  max-width: 16rem;
}

.matrix__track {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
}

.matrix__mark {
  font-weight: var(--rf-font-weight-bold);
}

[data-status='ok'] > .matrix__mark,
[data-status='exact'] .matrix__mark,
.matrix__mark--exact {
  color: var(--p-status-ok-color);
}

[data-status='warning'] > .matrix__mark,
[data-status='relaxed'] .matrix__mark,
[data-status='ambiguous'] .matrix__mark {
  color: var(--p-status-warn-color);
}

[data-status='error'] > .matrix__mark,
[data-status='missing'] .matrix__mark {
  color: var(--p-status-error-color);
}

[data-status='skipped'] .matrix__mark {
  color: var(--rf-color-text-muted);
}

.matrix__message {
  overflow: hidden;
  max-width: 100%;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
  text-overflow: ellipsis;
}

.matrix__unread {
  color: var(--p-status-error-color);
}

.matrix__name {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  column-gap: var(--rf-space-2);
}

.matrix__output {
  font-family: var(--rf-font-mono);
}

.matrix__output[data-status='error'] {
  color: var(--p-status-error-color);
}

.matrix__naming {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
  display: flex;
  grid-column: 2;
  gap: var(--rf-space-2);
}

.matrix__edit {
  grid-row: 1 / span 2;
}

.matrix__variable {
  font-family: var(--rf-font-mono);
}
</style>
