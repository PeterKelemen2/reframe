<script setup lang="ts">
// The workspace's sources column: open, probe progress, warnings, groups. Takes no props.
import { ChevronDown, ChevronRight, FolderTree, TriangleAlert } from '@lucide/vue'
import Button from 'primevue/button'
import ContextMenu from 'primevue/contextmenu'
import type { MenuItem } from 'primevue/menuitem'
import ProgressBar from 'primevue/progressbar'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { SourceEntry } from '@/api/types'
import ApplyToGroupDialog from '@/components/batch/ApplyToGroupDialog.vue'
import {
  clipboard,
  type Copied,
  pasteIntoFile,
  pasteIntoGroup,
  SECTIONS,
} from '@/components/batch/clipboard'
import { focusLost } from '@/components/shell/focus'
import { fileName } from '@/components/shell/format'
import { createTypeahead } from '@/components/shell/typeahead'
import { useQueueGroup } from '@/composables/useQueueGroup'
import { platform } from '@/platform'
import { useEditorStore } from '@/stores/editor'
import { type ProbeRun, useSourcesStore } from '@/stores/sources'
import { useToastStore } from '@/stores/toasts'
import { useUiStore } from '@/stores/ui'

import { type PanelItem, panelItems } from './panel'
import SourceItem from './SourceItem.vue'

const { t } = useI18n()
const sources = useSourcesStore()
const editor = useEditorStore()
const ui = useUiStore()
const toasts = useToastStore()
const { queueGroup } = useQueueGroup()
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

/** The groups first, then the files in no group, each in the order they were opened. */
const items = computed(() => {
  const all = panelItems(sources.entries, sources.grouping)
  return [
    ...all.filter((item) => item.kind === 'group'),
    ...all.filter((item) => item.kind === 'source'),
  ]
})

/** The files in no group get a heading of their own when a group is above them. */
const others = computed(() => {
  const first = items.value.findIndex((item) => item.kind === 'source')
  return first > 0 ? { first, count: items.value.length - first } : null
})

interface Node {
  key: string
  kind: 'source' | 'group'
  /** The sources this node stands for: one, or a group's members. */
  ids: string[]
  /** For a member: its group's key. */
  parent: string | null
  groupId: string | null
  /** What the type-ahead matches: the file name, a member's episode label, a group's name. */
  name: string
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
          name: fileName(item.entry.path),
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
      name: item.group.name,
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
        name: row.label,
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

function editedGroup(groupId: string | null): boolean {
  const target = editor.target
  return target?.kind === 'group' && target.groupId === groupId
}

/** A member of the edited group is shown in the group; any other source opens as one job. */
function choose(entryId: string, groupId: string | null): Promise<void> {
  focusKey.value = sourceKey(entryId)
  if (editedGroup(groupId)) return quietly(() => editor.showFile(entryId))
  return quietly(() => sources.select(entryId))
}

function editGroup(groupId: string): Promise<void> {
  return quietly(() => editor.editGroup(groupId))
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

const typeahead = createTypeahead()

function onKeydown(event: KeyboardEvent): void {
  if (event.altKey || event.ctrlKey || event.metaKey) return
  // A row's own buttons keep their keys: Enter and Space press them.
  if ((event.target as Element | null)?.closest('button') !== null) return
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
      else if (node.ids[0] !== undefined) void choose(node.ids[0], node.groupId)
      break
    case 'ContextMenu':
      openMenuAt(node)
      break
    case 'F10':
      if (!event.shiftKey) return
      openMenuAt(node)
      break
    case 'Delete':
    case 'Backspace':
      askRemove(node.key)
      break
    default: {
      const found = typeahead(
        event,
        shown.map((other) => other.name),
        index,
      )
      if (found === null) return
      focusNode(shown[found]?.key)
    }
  }
  event.preventDefault()
}

function onFocusin(event: FocusEvent): void {
  const node = nodeOf(event)
  if (node !== undefined) focusKey.value = node.key
}

const menu = useTemplateRef<InstanceType<typeof ContextMenu>>('menu')
/** The tree item whose context menu is open. */
const menuNode = ref<Node | null>(null)
const apply = ref<{ groupId: string; name: string; key: string } | null>(null)
const applyOpen = ref(false)

function groupName(groupId: string): string {
  return sources.grouping?.groups?.find((group) => group.id === groupId)?.name ?? ''
}

function copyItems(copy: ((section: Copied['section']) => Copied) | null): MenuItem[] {
  return SECTIONS.map((section) => ({
    label: t(`group.copy.${section}`),
    disabled: copy === null,
    command: () => {
      if (copy !== null) clipboard.value = copy(section)
    },
  }))
}

async function paste(copied: Copied, into: () => Promise<void>, name: string): Promise<void> {
  await quietly(async () => {
    await into()
    toasts.push({
      severity: 'success',
      summary: t('group.pasted', { section: t(`group.sections.${copied.section}`), name }),
      life: 5000,
    })
  })
}

function groupMenu(groupId: string): MenuItem[] {
  const target = editor.target
  const edited = target?.kind === 'group' && target.groupId === groupId ? target : null
  const copied = clipboard.value
  // The matrix is the edited group's: checking another group would quietly edit it.
  return [
    edited === null
      ? { label: t('group.actions.edit'), command: () => editGroup(groupId) }
      : { label: t('group.actions.check'), command: () => ui.openMatrix() },
    { label: t('group.actions.queue'), command: () => queueGroup(groupId) },
    { separator: true },
    ...copyItems(
      edited === null
        ? null
        : (section) => ({ from: 'group', section, template: edited.template, groupId }),
    ),
    ...(copied === null
      ? []
      : [
          {
            label: t(`group.paste.${copied.section}`),
            command: () => paste(copied, () => pasteIntoGroup(groupId, copied), groupName(groupId)),
          },
        ]),
  ]
}

function sourceMenu(node: Node, entryId: string): MenuItem[] {
  const target = editor.target
  const open = target?.kind === 'job' && target.sourceId === entryId ? target : null
  const copied = clipboard.value
  const entry = sources.entries.find((other) => other.id === entryId)
  const found: MenuItem[] = copyItems(
    open === null
      ? null
      : (section) => ({ from: 'job', section, job: open.job, sourceId: entryId }),
  )
  if (copied !== null) {
    found.push({
      label: t(`group.paste.${copied.section}`),
      command: () =>
        paste(copied, () => pasteIntoFile(entryId, copied), fileName(entry?.path ?? entryId)),
    })
  }
  // Its row's button is out of the Tab order: the keyboard reads a changed file again here.
  if (entry?.source === null) {
    found.unshift(
      { label: t('sources.panel.reprobe'), command: () => reprobe(entry) },
      { separator: true },
    )
  }
  const groupId = node.groupId
  if (open !== null && groupId !== null) {
    found.push(
      { separator: true },
      {
        label: t('group.actions.applyToGroup'),
        command: () => {
          apply.value = { groupId, name: groupName(groupId), key: node.key }
          applyOpen.value = true
        },
      },
    )
  }
  return found
}

const menuItems = computed<MenuItem[]>(() => {
  const node = menuNode.value
  if (node === null) return []
  if (node.kind === 'group' && node.groupId !== null) return groupMenu(node.groupId)
  const [entryId] = node.ids
  return entryId === undefined ? [] : sourceMenu(node, entryId)
})

function onContextmenu(event: MouseEvent): void {
  const node = nodeOf(event)
  if (node === undefined) return
  menuNode.value = node
  focusKey.value = node.key
  menu.value?.show(event)
}

/** The context menu key and Shift+F10: the menu opens at the item's corner. */
function openMenuAt(node: Node): void {
  const box = element(node.key)?.getBoundingClientRect()
  menuNode.value = node
  menu.value?.show(
    new MouseEvent('contextmenu', {
      clientX: (box?.left ?? 0) + 16,
      clientY: (box?.top ?? 0) + 16,
    }),
  )
}

// The menu leaves with the focus in it, or the focus went with a removed item.
// PrimeVue focuses the menu after this with no item in focus; a menu opens on its first item.
function menuShown(): void {
  void nextTick(() => {
    const list = document.querySelector<HTMLElement>('[data-menu="sources"] [role="menubar"]')
    if (list === null || list.getAttribute('aria-activedescendant')) return
    list.focus()
    list.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', code: 'Home', bubbles: true }))
  })
}

function menuHidden(): void {
  const node = menuNode.value
  setTimeout(() => {
    const active = document.activeElement
    if (node !== null && (focusLost() || active?.closest('.p-contextmenu'))) focusNode(node.key)
  })
}

function applyClosed(): void {
  if (apply.value !== null && focusLost()) focusNode(apply.value.key)
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
        severity="secondary"
        outlined
        :label="t('sources.panel.openFiles')"
        aria-keyshortcuts="Control+O"
        data-action="open-files"
        @click="openFiles"
      />
      <Button
        class="sources-panel__open-folder"
        size="small"
        severity="secondary"
        outlined
        :label="t('sources.panel.openFolder')"
        data-action="open-folder"
        @click="openFolder(false)"
      />
      <Button
        class="sources-panel__open-recursive"
        size="small"
        severity="secondary"
        text
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
      @contextmenu="onContextmenu"
    >
      <template
        v-for="(item, index) in items"
        :key="item.kind === 'group' ? item.group.id : item.entry.id"
      >
        <!-- A heading for the eye: the files stay items of the tree's first level. -->
        <li
          v-if="others !== null && index === others.first"
          role="none"
          aria-hidden="true"
          class="sources-panel__others"
          data-field="other-files"
        >
          <span class="sources-panel__group-name">{{ t('sources.panel.otherFiles') }}</span>
          {{ ' ' }}
          <span class="sources-panel__group-count rf-mono">{{ others.count }}</span>
        </li>
        <li
          v-if="item.kind === 'source'"
          role="treeitem"
          class="sources-panel__node sources-panel__source"
          :class="{ 'sources-panel__source--active': item.entry.id === sources.activeId }"
          :aria-selected="item.entry.id === sources.activeId"
          :aria-level="1"
          :aria-setsize="items.length"
          :aria-posinset="index + 1"
          :tabindex="tabKey === sourceKey(item.entry.id) ? 0 : -1"
          :data-key="sourceKey(item.entry.id)"
          :aria-labelledby="`${itemId(item.entry.id)}-title ${itemId(item.entry.id)}-details`"
          @click="choose(item.entry.id, null)"
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
          :class="{ 'sources-panel__group--edited': editedGroup(item.group.id) }"
          :aria-current="editedGroup(item.group.id) ? 'true' : undefined"
          :aria-expanded="!isCollapsed(item)"
          :aria-level="1"
          :aria-setsize="items.length"
          :aria-posinset="index + 1"
          :tabindex="tabKey === groupKey(item.group.id) ? 0 : -1"
          :data-key="groupKey(item.group.id)"
          :data-group="item.group.name"
          @click.self="toggle(item.group.id)"
        >
          <div class="sources-panel__group-head" @click="toggle(item.group.id)">
            <ChevronRight v-if="isCollapsed(item)" :size="16" aria-hidden="true" />
            <ChevronDown v-else :size="16" aria-hidden="true" />
            <span class="sources-panel__group-name" :title="item.group.name">{{
              item.group.name
            }}</span>
            <span class="sources-panel__group-count" data-field="count">{{
              t('sources.group.files', item.rows.length)
            }}</span>
          </div>
          <div class="sources-panel__group-meta" @click="toggle(item.group.id)">
            <span class="sources-panel__group-level">
              <template v-if="item.group.level === 'strict'">{{
                t('sources.group.level.strict')
              }}</template>
              <template v-else-if="item.group.level === 'loose'">{{
                t('sources.group.level.loose')
              }}</template>
              <template v-else>{{ t('sources.group.level.standard') }}</template>
            </span>
            <span
              v-if="editedGroup(item.group.id)"
              class="sources-panel__group-editing"
              data-field="editing"
              >{{ t('sources.group.editing') }}</span
            >
            <!-- Out of the Tab order as the rows' other buttons: the keyboard has the context menu.
                 The edited group's actions are the banner's, and the status bar queues. -->
            <span v-else class="sources-panel__group-actions" @click.stop>
              <Button
                size="small"
                text
                tabindex="-1"
                :label="t('group.actions.edit')"
                data-action="edit-group"
                @click="editGroup(item.group.id)"
              />
            </span>
          </div>
          <div
            v-if="nearCount(item) > 0"
            class="sources-panel__group-meta sources-panel__group-near"
            @click="toggle(item.group.id)"
          >
            <span data-field="near-count">
              <TriangleAlert :size="14" aria-hidden="true" />
              {{ t('sources.group.nearCount', nearCount(item)) }}
            </span>
          </div>
        </li>
        <template v-if="item.kind === 'group' && !isCollapsed(item)">
          <li
            v-for="(row, position) in item.rows"
            :key="row.entry.id"
            role="treeitem"
            class="sources-panel__node sources-panel__source sources-panel__member"
            :class="{
              'sources-panel__source--active': row.entry.id === sources.activeId,
              'sources-panel__member--edited': editedGroup(item.group.id),
            }"
            :aria-selected="row.entry.id === sources.activeId"
            :aria-level="2"
            :aria-setsize="item.rows.length"
            :aria-posinset="position + 1"
            :tabindex="tabKey === sourceKey(row.entry.id) ? 0 : -1"
            :data-key="sourceKey(row.entry.id)"
            :data-match="row.member.match"
            :aria-labelledby="`${itemId(row.entry.id)}-title ${itemId(row.entry.id)}-details`"
            @click="choose(row.entry.id, item.group.id)"
          >
            <SourceItem
              :entry="row.entry"
              :id-base="itemId(row.entry.id)"
              :member="row.member"
              :label="row.label"
              :sub-title="row.subTitle"
              @remove="askRemove(sourceKey(row.entry.id))"
              @reprobe="reprobe(row.entry)"
            />
          </li>
        </template>
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

    <ContextMenu
      ref="menu"
      :model="menuItems"
      :ariaLabel="t('sources.panel.menu')"
      data-menu="sources"
      @show="menuShown"
      @hide="menuHidden"
    />
    <ApplyToGroupDialog
      v-if="apply"
      v-model:visible="applyOpen"
      :group-id="apply.groupId"
      :group-name="apply.name"
      @closed="applyClosed"
    />
  </aside>
</template>

<style scoped>
.sources-panel {
  display: flex;
  flex-direction: column;
  gap: var(--rf-space-2);
  padding-bottom: var(--rf-space-3);
  background: var(--rf-color-surface);
}

.sources-panel > :not(.sources-panel__actions) {
  margin-inline: var(--rf-space-2);
}

.sources-panel ul {
  margin: 0;
  padding: 0;
  list-style: none;
}

.sources-panel__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
  padding: var(--rf-space-2) var(--rf-space-3);
  border-bottom: 1px solid var(--rf-color-border);
}

/* A label keeps to one line: a narrow column wraps the buttons, not their words. */
.sources-panel__open-files,
.sources-panel__open-folder {
  flex: 1 1 6.5rem;
  padding-inline: var(--rf-space-2);
  white-space: nowrap;
}

.sources-panel__open-recursive {
  flex: none;
  color: var(--rf-color-text-muted);
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
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-xs);
  font-variant-numeric: tabular-nums;
}

/* One column no wider than the panel: a long group name is cut, not the row widened. */
.sources-panel__tree {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
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
  padding: 0.375rem var(--rf-space-2);
  cursor: pointer;
  transition: background-color var(--rf-duration);
}

.sources-panel__source:hover {
  background: var(--rf-color-surface-hover);
}

/* The open file: the whole row tinted. */
.sources-panel__source--active,
.sources-panel__source--active:hover {
  background: var(--p-highlight-background);
}

.sources-panel__group,
.sources-panel__others {
  padding: var(--rf-space-3) 0 var(--rf-space-1);
}

.sources-panel__group-head,
.sources-panel__others {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
  min-width: 0;
  padding-inline: var(--rf-space-2);
}

.sources-panel__group-head {
  cursor: pointer;
}

.sources-panel__group-head > svg {
  flex: none;
  color: var(--rf-color-text-muted);
}

.sources-panel__group-name {
  overflow: hidden;
  min-width: 0;
  font-size: var(--rf-text-subheading);
  font-weight: var(--rf-font-weight-bold);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sources-panel__group-count {
  flex: none;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  white-space: nowrap;
}

.sources-panel__group-count::before {
  content: '·';
  margin-inline-end: var(--rf-space-2);
}

.sources-panel__group-editing {
  flex: none;
  margin-inline: auto var(--rf-space-2);
  padding: 0 0.375rem;
  border: 1px solid currentColor;
  border-radius: var(--rf-radius-sm);
  color: var(--rf-color-text);
  font-size: var(--rf-font-size-xs);
  font-weight: var(--rf-font-weight-medium);
  line-height: 1.4;
}

.sources-panel__group-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0 var(--rf-space-3);
  min-height: 1.75rem;
  padding-inline: calc(var(--rf-space-2) + 16px + var(--rf-space-2)) var(--rf-space-1);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  cursor: pointer;
}

.sources-panel__group-near {
  min-height: 0;
  color: var(--p-status-warn-color);
  font-size: var(--rf-font-size-xs);
}

.sources-panel__group-near > span {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
}

.sources-panel__group-actions {
  margin-inline-start: auto;
}

.sources-panel__group-actions :deep(.p-button) {
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
