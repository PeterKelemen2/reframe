<script setup lang="ts">
// The workspace's sources column: open, probe progress, warnings, groups. Takes no props.
import { ChevronDown, ChevronRight, FilePlus, FolderOpen, FolderTree } from '@lucide/vue'
import Button from 'primevue/button'
import ProgressBar from 'primevue/progressbar'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { SourceEntry } from '@/api/types'
import StatusDot from '@/components/base/StatusDot.vue'
import { fileName } from '@/components/shell/format'
import { platform } from '@/platform'
import { type ProbeRun, useSourcesStore } from '@/stores/sources'

import { type PanelItem, panelItems } from './panel'
import SourceItem from './SourceItem.vue'

const { t } = useI18n()
const sources = useSourcesStore()
const id = useId() ?? 'sources'

function itemId(entryId: string): string {
  return `${id}-item-${entryId}`
}

const root = useTemplateRef<HTMLElement>('root')
const tree = useTemplateRef<HTMLElement>('tree')
const collapsed = ref(new Set<string>())
/** The tree item that takes the Tab focus (roving tabindex). */
const focusKey = ref<string | null>(null)

interface PendingRemoval {
  ids: string[]
  /** The tree item it was asked from (the focus goes back there on *Keep*). */
  key: string
  /** The tree item that takes the focus after the removal. */
  next: string | null
  message: string
}

/** A removal waiting for its confirmation. */
const pending = ref<PendingRemoval | null>(null)

const items = computed(() => panelItems(sources.entries, sources.grouping))

interface Node {
  key: string
  kind: 'source' | 'group'
  /** The sources this node stands for: one, or a group's members. */
  ids: string[]
  /** For a member: its group's key. */
  parent: string | null
  groupId: string | null
}

function sourceKey(entryId: string): string {
  return `source:${entryId}`
}

function groupKey(groupId: string): string {
  return `group:${groupId}`
}

function isCollapsed(item: PanelItem): boolean {
  return item.kind === 'group' && collapsed.value.has(item.group.id)
}

/** The items a keyboard reaches, in screen order (members of a collapsed group are hidden). */
const nodes = computed<Node[]>(() =>
  items.value.flatMap((item): Node[] => {
    if (item.kind === 'source') {
      return [
        {
          key: sourceKey(item.entry.id),
          kind: 'source',
          ids: [item.entry.id],
          parent: null,
          groupId: null,
        },
      ]
    }
    const key = groupKey(item.group.id)
    const head: Node = {
      key,
      kind: 'group',
      ids: item.rows.map((row) => row.entry.id),
      parent: null,
      groupId: item.group.id,
    }
    const found = [head]
    if (isCollapsed(item)) return found
    for (const row of item.rows) {
      found.push({
        key: sourceKey(row.entry.id),
        kind: 'source',
        ids: [row.entry.id],
        parent: key,
        groupId: item.group.id,
      })
    }
    return found
  }),
)

/** The tree item with the Tab focus: the chosen one while it is shown, else the active source. */
const tabKey = computed(() => {
  const shown = nodes.value
  if (focusKey.value !== null && shown.some((node) => node.key === focusKey.value)) {
    return focusKey.value
  }
  const active = sources.activeId === null ? null : sourceKey(sources.activeId)
  if (active !== null && shown.some((node) => node.key === active)) return active
  return shown[0]?.key ?? null
})

function nearCount(item: Extract<PanelItem, { kind: 'group' }>): number {
  return item.rows.filter((row) => row.member.match === 'near').length
}

function runLabel(run: ProbeRun): string {
  const [only] = run.paths
  return run.paths.length === 1 && only !== undefined
    ? t('sources.probe.one', { name: fileName(only) })
    : t('sources.probe.many', { count: run.paths.length })
}

/** An `ApiError` was shown as a toast by the API client; anything else is a bug. */
async function quietly(action: () => Promise<unknown>): Promise<void> {
  try {
    await action()
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
  }
}

function openFiles(): Promise<void> {
  return quietly(() => sources.pick())
}

function openFolder(recursive: boolean): Promise<void> {
  return quietly(() => sources.pickFolder({ recursive }))
}

function element(key: string): HTMLElement | null {
  return tree.value?.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`) ?? null
}

function focusNode(key: string | null | undefined): void {
  if (key === null || key === undefined) return
  focusKey.value = key
  void nextTick(() => element(key)?.focus())
}

function choose(entryId: string): Promise<void> {
  focusKey.value = sourceKey(entryId)
  return quietly(() => sources.select(entryId))
}

function toggle(groupId: string): void {
  const next = new Set(collapsed.value)
  if (!next.delete(groupId)) next.add(groupId)
  collapsed.value = next
}

function names(ids: string[]): SourceEntry[] {
  return sources.entries.filter((entry) => ids.includes(entry.id))
}

async function removeThenFocus(ids: string[], next: string | null): Promise<void> {
  await quietly(() => sources.removeMany(ids))
  focusNode(next)
}

/** Asks first; on yes the focus goes to the item after the removed ones. */
function askRemove(key: string): void {
  const shown = nodes.value
  const index = shown.findIndex((other) => other.key === key)
  const node = shown[index]
  if (node === undefined) return
  const removed = names(node.ids)
  const [only] = removed
  if (only === undefined) return
  const following = shown
    .slice(index + 1)
    .find((other) => other.parent !== node.key && !node.ids.includes(other.ids[0] ?? ''))
  pending.value = {
    ids: node.ids,
    key,
    next: following?.key ?? shown[index - 1]?.key ?? null,
    message:
      removed.length === 1
        ? t('sources.panel.confirmRemoveOne', { name: fileName(only.path) })
        : t('sources.panel.confirmRemoveMany', { count: removed.length }),
  }
  void nextTick(() =>
    root.value?.querySelector<HTMLElement>('[data-action="confirm-remove"]')?.focus(),
  )
}

function acceptRemoval(): void {
  const asked = pending.value
  pending.value = null
  if (asked !== null) void removeThenFocus(asked.ids, asked.next)
}

function keep(): void {
  const asked = pending.value
  pending.value = null
  focusNode(asked?.key)
}

function nodeOf(event: Event): Node | undefined {
  const holder = (event.target as Element | null)?.closest<HTMLElement>('[data-key]')
  const key = holder?.dataset.key
  return nodes.value.find((node) => node.key === key)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.altKey || event.ctrlKey || event.metaKey) return
  const node = nodeOf(event)
  if (node === undefined) return
  const shown = nodes.value
  const index = shown.indexOf(node)
  const open = node.kind === 'group' && node.groupId !== null && !collapsed.value.has(node.groupId)
  switch (event.key) {
    case 'ArrowDown':
      focusNode(shown[index + 1]?.key)
      break
    case 'ArrowUp':
      focusNode(shown[index - 1]?.key)
      break
    case 'Home':
      focusNode(shown[0]?.key)
      break
    case 'End':
      focusNode(shown.at(-1)?.key)
      break
    case 'ArrowRight':
      if (node.kind !== 'group' || node.groupId === null) return
      if (open) focusNode(shown[index + 1]?.key)
      else toggle(node.groupId)
      break
    case 'ArrowLeft':
      if (node.kind === 'group' && node.groupId !== null && open) toggle(node.groupId)
      else if (node.parent !== null) focusNode(node.parent)
      else return
      break
    case 'Enter':
    case ' ':
      if (node.kind === 'group' && node.groupId !== null) toggle(node.groupId)
      else if (node.ids[0] !== undefined) void choose(node.ids[0])
      break
    case 'Delete':
    case 'Backspace':
      askRemove(node.key)
      break
    default:
      return
  }
  event.preventDefault()
}

function onFocusin(event: FocusEvent): void {
  const node = nodeOf(event)
  if (node !== undefined) focusKey.value = node.key
}

function reprobe(entry: SourceEntry): Promise<void> {
  return quietly(() => sources.open([entry.path], { select: false }))
}

let stopDrops: (() => void) | null = null
onMounted(() => {
  stopDrops = platform.onFilesDropped((paths) => void quietly(() => sources.open(paths)))
})
onBeforeUnmount(() => stopDrops?.())
</script>

<template>
  <aside ref="root" class="sources-panel" :aria-label="t('sources.panel.label')">
    <div class="sources-panel__actions">
      <Button
        class="sources-panel__open-files"
        size="small"
        :label="t('sources.panel.openFiles')"
        aria-keyshortcuts="Control+O"
        data-action="open-files"
        @click="openFiles"
      >
        <template #icon><FilePlus :size="16" aria-hidden="true" /></template>
      </Button>
      <Button
        class="sources-panel__open-folder"
        size="small"
        severity="secondary"
        :label="t('sources.panel.openFolder')"
        data-action="open-folder"
        @click="openFolder(false)"
      >
        <template #icon><FolderOpen :size="16" aria-hidden="true" /></template>
      </Button>
      <Button
        size="small"
        severity="secondary"
        outlined
        :aria-label="t('sources.panel.openFolderRecursive')"
        v-tooltip.bottom="t('sources.panel.openFolderRecursive')"
        data-action="open-folder-recursive"
        @click="openFolder(true)"
      >
        <template #icon><FolderTree :size="16" aria-hidden="true" /></template>
      </Button>
    </div>

    <ul v-if="sources.probing.length > 0" class="sources-panel__runs" aria-live="polite">
      <li
        v-for="run in sources.probing"
        :key="run.taskId"
        class="sources-panel__run"
        data-state="probing"
      >
        <span class="sources-panel__run-label">{{ runLabel(run) }}</span>
        <ProgressBar
          class="sources-panel__run-bar"
          :mode="run.progress === null ? 'indeterminate' : 'determinate'"
          :value="run.progress === null ? undefined : Math.round(run.progress * 100)"
          :show-value="false"
          :pt="{ root: { 'aria-label': runLabel(run) } }"
        />
        <span v-if="run.progress !== null && run.message" class="sources-panel__run-message">{{
          run.message
        }}</span>
      </li>
    </ul>

    <div
      v-if="pending"
      class="sources-panel__confirm"
      role="alertdialog"
      :aria-labelledby="`${id}-confirm`"
      data-state="confirm-remove"
      @keydown.esc.stop.prevent="keep"
    >
      <p :id="`${id}-confirm`" class="sources-panel__confirm-text">{{ pending.message }}</p>
      <div class="sources-panel__confirm-actions">
        <Button
          size="small"
          severity="danger"
          :label="t('sources.panel.confirmRemove')"
          data-action="confirm-remove"
          @click="acceptRemoval"
        />
        <Button
          size="small"
          severity="secondary"
          text
          :label="t('sources.panel.keep')"
          data-action="keep"
          @click="keep"
        />
      </div>
    </div>

    <ul
      v-if="items.length > 0"
      ref="tree"
      class="sources-panel__tree"
      role="tree"
      :aria-label="t('sources.panel.label')"
      @keydown="onKeydown"
      @focusin="onFocusin"
    >
      <template v-for="item in items" :key="item.kind === 'group' ? item.group.id : item.entry.id">
        <li
          v-if="item.kind === 'source'"
          role="treeitem"
          class="sources-panel__node sources-panel__source"
          :class="{ 'sources-panel__source--active': item.entry.id === sources.activeId }"
          :aria-selected="item.entry.id === sources.activeId"
          :aria-level="1"
          :tabindex="tabKey === sourceKey(item.entry.id) ? 0 : -1"
          :data-key="sourceKey(item.entry.id)"
          :aria-labelledby="`${itemId(item.entry.id)}-title`"
          :aria-describedby="`${itemId(item.entry.id)}-details`"
          @click="choose(item.entry.id)"
        >
          <SourceItem
            :entry="item.entry"
            :id-base="itemId(item.entry.id)"
            @remove="askRemove(sourceKey(item.entry.id))"
            @reprobe="reprobe(item.entry)"
          />
        </li>
        <li
          v-else
          role="treeitem"
          class="sources-panel__node sources-panel__group"
          :aria-expanded="!isCollapsed(item)"
          :aria-level="1"
          :tabindex="tabKey === groupKey(item.group.id) ? 0 : -1"
          :data-key="groupKey(item.group.id)"
          :data-group="item.group.name"
          @click.self="toggle(item.group.id)"
        >
          <div class="sources-panel__group-head" @click="toggle(item.group.id)">
            <ChevronRight v-if="isCollapsed(item)" :size="16" aria-hidden="true" />
            <ChevronDown v-else :size="16" aria-hidden="true" />
            <span class="sources-panel__group-name">{{ item.group.name }}</span>
          </div>
          <div class="sources-panel__group-meta" @click="toggle(item.group.id)">
            <span data-field="count">{{ t('sources.group.files', item.rows.length) }}</span>
            <span>
              <template v-if="item.group.level === 'strict'">{{
                t('sources.group.level.strict')
              }}</template>
              <template v-else-if="item.group.level === 'loose'">{{
                t('sources.group.level.loose')
              }}</template>
              <template v-else>{{ t('sources.group.level.standard') }}</template>
            </span>
          </div>
          <div
            v-if="nearCount(item) > 0"
            class="sources-panel__group-meta"
            @click="toggle(item.group.id)"
          >
            <StatusDot
              tone="warn"
              show-label
              :label="t('sources.group.nearCount', nearCount(item))"
              data-field="near-count"
            />
          </div>
          <ul v-if="!isCollapsed(item)" role="group" class="sources-panel__members">
            <li
              v-for="row in item.rows"
              :key="row.entry.id"
              role="treeitem"
              class="sources-panel__node sources-panel__source sources-panel__member"
              :class="{ 'sources-panel__source--active': row.entry.id === sources.activeId }"
              :aria-selected="row.entry.id === sources.activeId"
              :aria-level="2"
              :tabindex="tabKey === sourceKey(row.entry.id) ? 0 : -1"
              :data-key="sourceKey(row.entry.id)"
              :data-match="row.member.match"
              :aria-labelledby="`${itemId(row.entry.id)}-title`"
              :aria-describedby="`${itemId(row.entry.id)}-details`"
              @click.stop="choose(row.entry.id)"
            >
              <SourceItem
                :entry="row.entry"
                :id-base="itemId(row.entry.id)"
                :member="row.member"
                :label="row.label"
                @remove="askRemove(sourceKey(row.entry.id))"
                @reprobe="reprobe(row.entry)"
              />
            </li>
          </ul>
        </li>
      </template>
    </ul>

    <div
      v-else-if="sources.probing.length === 0"
      class="sources-panel__empty"
      data-state="no-sources"
    >
      <p class="sources-panel__empty-title">{{ t('sources.panel.emptyTitle') }}</p>
      <p class="sources-panel__empty-text">{{ t('sources.panel.emptyText') }}</p>
    </div>
  </aside>
</template>

<style scoped>
.sources-panel {
  display: flex;
  flex-direction: column;
  gap: var(--rf-space-3);
  padding: var(--rf-space-3);
  background: var(--rf-color-surface);
}

.sources-panel ul {
  margin: 0;
  padding: 0;
  list-style: none;
}

.sources-panel__actions {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--rf-space-2);
}

.sources-panel__open-files {
  grid-column: 1 / -1;
}

.sources-panel__runs {
  display: grid;
  gap: var(--rf-space-2);
}

.sources-panel__run {
  display: grid;
  gap: var(--rf-space-1);
  font-size: var(--rf-font-size-sm);
}

.sources-panel__run-bar {
  height: 0.375rem;
}

.sources-panel__run-label,
.sources-panel__run-message {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sources-panel__run-message {
  color: var(--rf-color-text-muted);
  font-variant-numeric: tabular-nums;
}

.sources-panel__tree {
  display: grid;
  gap: 1px;
}

.sources-panel__node {
  border-radius: var(--rf-radius-md);
  outline: none;
}

.sources-panel__node:focus-visible {
  outline: 2px solid var(--rf-color-primary);
  outline-offset: -2px;
}

.sources-panel__source {
  padding: var(--rf-space-2);
  border-left: 3px solid transparent;
  cursor: pointer;
}

.sources-panel__source:hover {
  background: var(--rf-color-surface-hover);
}

.sources-panel__source--active {
  border-left-color: var(--rf-color-primary);
  background: color-mix(in srgb, var(--rf-color-primary) 14%, transparent);
}

.sources-panel__source--active:hover {
  background: color-mix(in srgb, var(--rf-color-primary) 20%, transparent);
}

.sources-panel__group {
  padding: var(--rf-space-1) 0;
}

.sources-panel__group-head,
.sources-panel__group-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-1) var(--rf-space-2);
  padding: 0 var(--rf-space-2);
  cursor: pointer;
}

.sources-panel__group-name {
  overflow: hidden;
  font-weight: var(--rf-font-weight-bold);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sources-panel__group-meta {
  padding-inline-start: calc(var(--rf-space-2) + 16px + var(--rf-space-2));
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.sources-panel__group-meta > span + span::before {
  content: '·';
  margin-inline-end: var(--rf-space-2);
}

.sources-panel__members {
  display: grid;
  gap: 1px;
  margin-top: var(--rf-space-1) !important;
  padding-inline-start: var(--rf-space-4) !important;
}

.sources-panel__member {
  padding-block: 0.125rem;
}

.sources-panel__confirm {
  position: sticky;
  z-index: 1;
  top: 0;
  display: grid;
  gap: var(--rf-space-2);
  padding: var(--rf-space-2) var(--rf-space-3);
  border: 1px solid var(--p-status-error-border-color);
  border-radius: var(--rf-radius-md);
  background: var(--p-status-error-background);
}

.sources-panel__confirm-text {
  margin: 0;
  overflow-wrap: anywhere;
}

.sources-panel__confirm-actions {
  display: flex;
  gap: var(--rf-space-2);
}

.sources-panel__empty {
  display: grid;
  gap: var(--rf-space-1);
  padding: var(--rf-space-4) var(--rf-space-2);
  color: var(--rf-color-text-muted);
  text-align: center;
}

.sources-panel__empty p {
  margin: 0;
}

.sources-panel__empty-title {
  color: var(--rf-color-text);
  font-weight: var(--rf-font-weight-medium);
}
</style>
