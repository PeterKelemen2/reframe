<script setup lang="ts">
// The web build's file and folder picker. Mounted once by App.vue; the web platform's
// `pickFiles`, `pickFolder` and `pickSavePath` open it.
import { ArrowUp, FileVideo, Folder, HardDrive, Search } from '@lucide/vue'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import Message from 'primevue/message'
import { computed, nextTick, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import type { FsListing, FsRoot, Problem } from '@/api/types'
import { fileName } from '@/components/shell/format'

import { type BrowseRequest, currentRequest, finish } from './fileBrowser'
import { crumbsOf, extensionOf, folderOf, joinPath } from './paths'

type Entry = FsListing['entries'][number]

const { t, locale } = useI18n()
/** Vue's types have no `autofocus` on a `div`; PrimeVue's dialog focuses the element that has it. */
const autofocus: Record<string, string> = { autofocus: '' }
const id = useId() ?? 'file-browser'

const request = computed(currentRequest)
const roots = ref<FsRoot[]>([])
const listing = ref<FsListing | null>(null)
const loading = ref(false)
const problem = ref<Problem | null>(null)
/** Paths of the chosen files (files mode) in the folder shown. */
const selected = ref<string[]>([])
/** The entry the keyboard is on (index into `visible`). */
const cursor = ref(0)
/** Where a Shift range starts. */
const anchor = ref<number | null>(null)
const filterOn = ref(true)
const location = ref('')
const saveName = ref('')

/** The folder each mode showed last in this tab: the next pick starts there. */
const lastFolder: Partial<Record<BrowseRequest['mode'], string>> = {}
// The newest listing wins: a slow folder answered after a later click is dropped.
let reads = 0

const mode = computed(() => request.value?.mode ?? 'files')
const filtered = computed(() => (request.value?.filters.length ?? 0) > 0)
const visible = computed<Entry[]>(() => {
  const entries = listing.value?.entries ?? []
  const wanted = request.value?.filters ?? []
  return entries.filter((entry) => {
    if (entry.kind === 'folder') return true
    return !filtered.value || !filterOn.value || wanted.includes(extensionOf(entry.name))
  })
})
const crumbs = computed(() => (listing.value ? crumbsOf(listing.value.path, roots.value) : []))
const title = computed(() => {
  if (request.value?.title) return request.value.title
  switch (mode.value) {
    case 'folder':
      return t('sources.browser.titleFolder')
    case 'save':
      return t('sources.browser.titleSave')
    default:
      return request.value?.multiple
        ? t('sources.browser.titleFiles')
        : t('sources.browser.titleFile')
  }
})
const canConfirm = computed(() => {
  if (listing.value === null) return false
  if (mode.value === 'files') return selected.value.length > 0
  if (mode.value === 'save') return saveName.value.trim() !== ''
  return true
})

function optionId(index: number): string {
  return `${id}-entry-${index}`
}

function formatSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return ''
  const units = ['byte', 'kilobyte', 'megabyte', 'gigabyte', 'terabyte'] as const
  let value = bytes
  let unit = 0
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000
    unit += 1
  }
  return new Intl.NumberFormat(locale.value, {
    style: 'unit',
    unit: units[unit],
    unitDisplay: 'short',
    maximumFractionDigits: unit === 0 ? 0 : 1,
  }).format(value)
}

async function read<T>(call: () => Promise<{ data?: T; error?: unknown; response: Response }>) {
  try {
    return { value: unwrap(await call()), problem: null }
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
    return { value: null, problem: error.problem }
  }
}

/** Shows the folder; on a refusal the folder shown stays and the problem shows above it. */
async function show(path: string, focusPath?: string): Promise<boolean> {
  const mine = ++reads
  loading.value = true
  const answer = await read(() => apiQuiet.GET('/api/fs/list', { params: { query: { path } } }))
  if (mine !== reads) return false
  loading.value = false
  problem.value = answer.problem
  if (answer.value === null) return false
  listing.value = answer.value
  location.value = answer.value.path
  selected.value = []
  anchor.value = null
  const index = focusPath === undefined ? -1 : visible.value.findIndex((e) => e.path === focusPath)
  cursor.value = Math.max(index, 0)
  if (request.value !== null) lastFolder[request.value.mode] = answer.value.path
  return true
}

async function start(next: BrowseRequest): Promise<void> {
  listing.value = null
  problem.value = null
  selected.value = []
  filterOn.value = true
  saveName.value = next.defaultPath === null ? '' : fileName(next.defaultPath)
  const answer = await read(() => apiQuiet.GET('/api/fs/roots'))
  if (request.value !== next) return
  roots.value = answer.value?.roots ?? []
  if (answer.problem !== null) {
    problem.value = answer.problem
    return
  }
  const preferred = next.mode === 'save' ? 'output' : 'media'
  const firstRoot =
    roots.value.find((root) => root.kind === preferred)?.path ?? roots.value[0]?.path ?? null
  const proposed = next.defaultPath === null ? null : folderOf(next.defaultPath)
  const candidates = [proposed, lastFolder[next.mode], firstRoot].filter(
    (path): path is string => typeof path === 'string',
  )
  if (await showFirst(next, candidates)) problem.value = null
}

/** The first of the folders that can be listed: a remembered one may be gone. */
async function showFirst(next: BrowseRequest, candidates: string[]): Promise<boolean> {
  const [first, ...rest] = candidates
  if (first === undefined || request.value !== next) return false
  return (await show(first)) || showFirst(next, rest)
}

// PrimeVue's dialog gives the focus back to where it was when it closes.
watch(request, (next) => {
  if (next !== null) void start(next)
})

function close(paths: string[] | null): void {
  const open = request.value
  if (open !== null) finish(open, paths)
}

function confirm(): void {
  const folder = listing.value?.path
  if (folder === undefined || !canConfirm.value) return
  if (mode.value === 'files') close([...selected.value])
  else if (mode.value === 'folder') close([folder])
  else close([joinPath(folder, saveName.value.trim())])
}

function onVisible(value: boolean): void {
  if (!value) close(null)
}

function goUp(): void {
  const current = listing.value
  if (current?.parent) void show(current.parent, current.path)
}

function goTo(): void {
  const path = location.value.trim()
  if (path !== '') void show(path)
}

function isSelected(entry: Entry): boolean {
  return selected.value.includes(entry.path)
}

function files(from: number, to: number): string[] {
  const [low, high] = from <= to ? [from, to] : [to, from]
  return visible.value
    .slice(low, high + 1)
    .filter((entry) => entry.kind === 'file')
    .map((entry) => entry.path)
}

/** Click, Shift and Ctrl (or Cmd) choose as a desktop file dialog does. */
function choose(index: number, how: { range?: boolean; toggle?: boolean } = {}): void {
  const entry = visible.value[index]
  if (entry === undefined || entry.kind !== 'file') return
  if (mode.value === 'save') {
    saveName.value = entry.name
    return
  }
  if (mode.value !== 'files') return
  const multiple = request.value?.multiple ?? false
  if (multiple && how.range && anchor.value !== null) {
    selected.value = files(anchor.value, index)
    return
  }
  if (multiple && how.toggle) {
    selected.value = isSelected(entry)
      ? selected.value.filter((path) => path !== entry.path)
      : [...selected.value, entry.path]
  } else {
    selected.value = [entry.path]
  }
  anchor.value = index
}

function onClick(index: number, event: MouseEvent): void {
  cursor.value = index
  const entry = visible.value[index]
  if (entry?.kind === 'folder') {
    void show(entry.path)
    return
  }
  choose(index, { range: event.shiftKey, toggle: event.ctrlKey || event.metaKey })
}

function onDoubleClick(index: number): void {
  const entry = visible.value[index]
  if (entry?.kind !== 'file' || mode.value === 'folder') return
  choose(index)
  confirm()
}

function moveTo(index: number, extend: boolean): void {
  const last = visible.value.length - 1
  if (last < 0) return
  cursor.value = Math.min(Math.max(index, 0), last)
  if (extend && mode.value === 'files' && request.value?.multiple) {
    anchor.value ??= cursor.value
    selected.value = files(anchor.value, cursor.value)
  }
  void nextTick(() =>
    document.getElementById(optionId(cursor.value))?.scrollIntoView({ block: 'nearest' }),
  )
}

function onKeydown(event: KeyboardEvent): void {
  const entry = visible.value[cursor.value]
  const extend = event.shiftKey
  switch (event.key) {
    case 'ArrowDown':
      if (event.altKey) return
      moveTo(cursor.value + 1, extend)
      break
    case 'ArrowUp':
      if (event.altKey) goUp()
      else moveTo(cursor.value - 1, extend)
      break
    case 'Home':
      moveTo(0, extend)
      break
    case 'End':
      moveTo(visible.value.length - 1, extend)
      break
    case 'Backspace':
      goUp()
      break
    case ' ':
      if (entry?.kind === 'folder') void show(entry.path)
      else choose(cursor.value, { toggle: true })
      break
    case 'Enter':
      if (entry?.kind === 'folder') {
        void show(entry.path)
        break
      }
      // Enter opens what is chosen; with nothing chosen, the file under the cursor.
      if (entry !== undefined && (mode.value === 'save' || selected.value.length === 0)) {
        choose(cursor.value)
      }
      confirm()
      break
    case 'a':
      if (!(event.ctrlKey || event.metaKey) || !request.value?.multiple || mode.value !== 'files') {
        return
      }
      selected.value = files(0, visible.value.length - 1)
      break
    default:
      return
  }
  event.preventDefault()
}

const summary = computed(() => {
  if (mode.value === 'files') return t('sources.browser.selected', selected.value.length)
  if (mode.value === 'folder') return listing.value?.path ?? ''
  return ''
})
</script>

<template>
  <Dialog
    :visible="request !== null"
    modal
    :header="title"
    class="file-browser-dialog"
    :style="{ width: 'min(56rem, calc(100vw - 2rem))' }"
    :breakpoints="{ '40rem': 'calc(100vw - 1rem)' }"
    :draggable="false"
    :data-mode="mode"
    @update:visible="onVisible"
  >
    <div class="file-browser">
      <nav class="file-browser__roots" :aria-label="t('sources.browser.roots')">
        <ul>
          <li v-for="root in roots" :key="root.path">
            <button
              type="button"
              class="file-browser__root"
              :aria-current="crumbs[0]?.path === root.path ? 'location' : undefined"
              :title="root.path"
              data-role="root"
              @click="show(root.path)"
            >
              <HardDrive :size="16" aria-hidden="true" />
              <span class="file-browser__root-name">{{ root.name }}</span>
              <span class="file-browser__root-kind">
                <template v-if="root.kind === 'media'">{{
                  t('sources.browser.kind.media')
                }}</template>
                <template v-else-if="root.kind === 'output'">
                  {{ t('sources.browser.kind.output') }}
                </template>
                <template v-else-if="root.kind === 'home'">{{
                  t('sources.browser.kind.home')
                }}</template>
                <template v-else>{{ t('sources.browser.kind.drive') }}</template>
              </span>
            </button>
          </li>
        </ul>
      </nav>

      <div class="file-browser__main">
        <div class="file-browser__bar">
          <Button
            severity="secondary"
            text
            size="small"
            :disabled="!listing?.parent"
            :aria-label="t('sources.browser.up')"
            v-tooltip.bottom="t('sources.browser.up')"
            data-action="up"
            @click="goUp"
          >
            <template #icon><ArrowUp :size="16" aria-hidden="true" /></template>
          </Button>
          <nav class="file-browser__crumbs" :aria-label="t('sources.browser.crumbs')">
            <ol>
              <li v-for="(crumb, index) in crumbs" :key="crumb.path">
                <button
                  type="button"
                  class="file-browser__crumb"
                  :aria-current="index === crumbs.length - 1 ? 'location' : undefined"
                  data-role="crumb"
                  @click="show(crumb.path)"
                >
                  {{ crumb.label }}
                </button>
              </li>
            </ol>
          </nav>
        </div>

        <form class="file-browser__location" @submit.prevent="goTo">
          <label class="file-browser__location-label" :for="`${id}-location`">
            {{ t('sources.browser.location') }}
          </label>
          <InputText
            :id="`${id}-location`"
            :model-value="location"
            @update:model-value="location = $event ?? ''"
            size="small"
            class="file-browser__location-input"
            spellcheck="false"
            autocomplete="off"
            data-field="location"
          />
          <Button
            type="submit"
            severity="secondary"
            size="small"
            :label="t('sources.browser.go')"
            data-action="go"
          >
            <template #icon><Search :size="16" aria-hidden="true" /></template>
          </Button>
        </form>

        <Message v-if="problem" severity="error" class="file-browser__problem" data-state="problem">
          <strong class="file-browser__problem-title">{{ problem.title }}</strong>
          <span v-if="problem.detail" class="file-browser__problem-detail">{{
            problem.detail
          }}</span>
        </Message>

        <div
          :id="`${id}-list`"
          class="file-browser__list"
          role="listbox"
          tabindex="0"
          v-bind="autofocus"
          :aria-label="listing ? fileName(listing.path) : t('sources.browser.roots')"
          :aria-multiselectable="mode === 'files' && request?.multiple ? 'true' : undefined"
          :aria-activedescendant="visible.length > 0 ? optionId(cursor) : undefined"
          :aria-busy="loading ? 'true' : undefined"
          @keydown="onKeydown"
        >
          <div
            v-for="(entry, index) in visible"
            :id="optionId(index)"
            :key="entry.path"
            role="option"
            class="file-browser__entry"
            :class="{
              'file-browser__entry--cursor': index === cursor,
              'file-browser__entry--selected': isSelected(entry),
            }"
            :aria-selected="entry.kind === 'file' ? isSelected(entry) : undefined"
            :aria-disabled="entry.kind === 'file' && mode === 'folder' ? 'true' : undefined"
            :data-kind="entry.kind"
            :data-name="entry.name"
            @click="onClick(index, $event)"
            @dblclick="onDoubleClick(index)"
          >
            <Folder v-if="entry.kind === 'folder'" :size="18" aria-hidden="true" />
            <FileVideo v-else :size="18" aria-hidden="true" />
            <span class="file-browser__name">{{ entry.name }}</span>
            <span class="file-browser__size">{{ formatSize(entry.size) }}</span>
          </div>
          <p v-if="listing && visible.length === 0" class="file-browser__empty" data-state="empty">
            {{ t('sources.browser.empty') }}
          </p>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="file-browser__footer">
        <div class="file-browser__footer-info">
          <div v-if="filtered && mode !== 'folder'" class="file-browser__filter">
            <Checkbox v-model="filterOn" :input-id="`${id}-filter`" binary data-field="filter" />
            <label :for="`${id}-filter`">
              {{ t('sources.browser.filter', { types: request?.filters.join(', ') ?? '' }) }}
            </label>
          </div>
          <form v-if="mode === 'save'" class="file-browser__save" @submit.prevent="confirm">
            <label :for="`${id}-name`">{{ t('sources.browser.fileName') }}</label>
            <InputText
              :id="`${id}-name`"
              :model-value="saveName"
              size="small"
              data-field="name"
              @update:model-value="saveName = $event ?? ''"
            />
          </form>
          <span v-else class="file-browser__summary" aria-live="polite" data-field="summary">
            {{ summary }}
          </span>
        </div>
        <Button
          severity="secondary"
          text
          :label="t('sources.browser.cancel')"
          data-action="cancel"
          @click="close(null)"
        />
        <Button :disabled="!canConfirm" data-action="confirm" @click="confirm">
          <template v-if="mode === 'folder'">{{ t('sources.browser.chooseFolder') }}</template>
          <template v-else-if="mode === 'save'">{{ t('sources.browser.save') }}</template>
          <template v-else>{{ t('sources.browser.open') }}</template>
        </Button>
      </div>
    </template>
  </Dialog>
</template>

<style scoped>
.file-browser {
  display: grid;
  grid-template-columns: minmax(9rem, 12rem) minmax(0, 1fr);
  gap: var(--rf-space-4);
  min-height: 22rem;
}

.file-browser ul,
.file-browser ol {
  margin: 0;
  padding: 0;
  list-style: none;
}

.file-browser__roots ul {
  display: grid;
  gap: var(--rf-space-1);
}

.file-browser__root {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 0 var(--rf-space-2);
  width: 100%;
  padding: var(--rf-space-2);
  border: 1px solid transparent;
  border-radius: var(--rf-radius-md);
  background: none;
  color: inherit;
  font: inherit;
  text-align: start;
  cursor: pointer;
}

.file-browser__root:hover {
  background: var(--rf-color-surface-hover);
}

.file-browser__root[aria-current] {
  border-color: var(--rf-color-border);
  background: var(--rf-color-surface-hover);
  font-weight: var(--rf-font-weight-medium);
}

.file-browser__root-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-browser__root-kind {
  grid-column: 2;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
}

.file-browser__main {
  display: flex;
  flex-direction: column;
  gap: var(--rf-space-2);
  min-width: 0;
}

.file-browser__bar {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.file-browser__crumbs ol {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}

.file-browser__crumbs li + li::before {
  content: '/';
  padding: 0 var(--rf-space-1);
  color: var(--rf-color-text-muted);
}

.file-browser__crumb {
  padding: var(--rf-space-1);
  border: none;
  border-radius: var(--rf-radius-sm);
  background: none;
  color: var(--rf-color-primary);
  font: inherit;
  cursor: pointer;
}

.file-browser__crumb[aria-current] {
  color: var(--rf-color-text);
  font-weight: var(--rf-font-weight-medium);
}

.file-browser__crumb:hover {
  background: var(--rf-color-surface-hover);
}

.file-browser__location {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.file-browser__location-label {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.file-browser__location-input {
  flex: 1;
  min-width: 0;
  font-family: var(--rf-font-mono);
}

.file-browser__list {
  flex: 1;
  min-height: 14rem;
  max-height: 50vh;
  overflow: auto;
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md);
  outline: none;
}

.file-browser__list:focus-visible {
  outline: 2px solid var(--rf-color-primary);
  outline-offset: 1px;
}

.file-browser__entry {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--rf-space-2);
  padding: var(--rf-space-1) var(--rf-space-2);
  border-left: 3px solid transparent;
  cursor: pointer;
  user-select: none;
}

.file-browser__entry:hover {
  background: var(--rf-color-surface-hover);
}

.file-browser__entry--selected,
.file-browser__entry--selected:hover {
  background: color-mix(in srgb, var(--rf-color-primary) 16%, transparent);
}

.file-browser__list:focus .file-browser__entry--cursor {
  border-left-color: var(--rf-color-primary);
  outline: 1px dashed var(--rf-color-primary);
  outline-offset: -1px;
}

.file-browser__entry[data-kind='folder'] {
  color: var(--rf-color-text);
}

.file-browser__entry[aria-disabled='true'] {
  color: var(--rf-color-text-muted);
  cursor: default;
}

.file-browser__problem-title,
.file-browser__problem-detail {
  display: block;
}

.file-browser__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-browser__size {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  font-variant-numeric: tabular-nums;
}

.file-browser__empty {
  margin: 0;
  padding: var(--rf-space-4);
  color: var(--rf-color-text-muted);
  text-align: center;
}

.file-browser__footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
  width: 100%;
}

.file-browser__footer-info {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2) var(--rf-space-4);
  min-width: 0;
}

.file-browser__filter,
.file-browser__save {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.file-browser__summary {
  overflow: hidden;
  color: var(--rf-color-text-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (width < 40rem) {
  .file-browser {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
