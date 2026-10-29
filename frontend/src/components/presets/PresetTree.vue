<script setup lang="ts">
import { ChevronRight, CircleDot, Lock, Star } from '@lucide/vue'
import { computed, nextTick, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Preset } from '@/api/types'
import type { PresetCategory } from '@/stores/presets'

/**
 * The presets by category as an ARIA tree. The selection follows the focus; Enter applies a
 * preset, Delete asks to delete a user preset, double-click applies.
 */
const props = defineProps<{
  categories: PresetCategory[]
  selectedId: string | null
  defaultId: string | null
  /** The open job's preset. */
  currentId: string | null
}>()

const emit = defineEmits<{
  select: [id: string]
  apply: [id: string]
  remove: [id: string]
}>()

const { t } = useI18n()
const id = useId()

type Item =
  | { key: string; kind: 'category'; name: string; labelId: string }
  | { key: string; kind: 'preset'; preset: Preset; parent: string }

const collapsed = ref(new Set<string>())
const focusKey = ref<string | null>(null)
const elements = new Map<string, HTMLElement>()

const categoryKey = (name: string) => `c:${name}`
const presetKey = (presetId: string) => `p:${presetId}`

/** The items a user can move through: categories, and the presets of the open ones. */
const visible = computed<Item[]>(() => {
  const items: Item[] = []
  props.categories.forEach((category, index) => {
    const key = categoryKey(category.name)
    items.push({ key, kind: 'category', name: category.name, labelId: `${id}-c${index}` })
    if (collapsed.value.has(category.name)) return
    for (const preset of category.presets) {
      items.push({ key: presetKey(preset.id), kind: 'preset', preset, parent: key })
    }
  })
  return items
})

const categoryOf = (presetId: string) =>
  props.categories.find((category) => category.presets.some((preset) => preset.id === presetId))

/** The one item in the tab order. */
const tabKey = computed(() => {
  const keys = new Set(visible.value.map((item) => item.key))
  if (focusKey.value !== null && keys.has(focusKey.value)) return focusKey.value
  if (props.selectedId !== null && keys.has(presetKey(props.selectedId))) {
    return presetKey(props.selectedId)
  }
  return visible.value[0]?.key ?? null
})

// A preset chosen elsewhere (the details, a duplicate, an import) is shown.
watch(
  () => props.selectedId,
  (selected) => {
    if (selected === null) return
    const category = categoryOf(selected)
    if (category !== undefined && collapsed.value.has(category.name)) {
      const next = new Set(collapsed.value)
      next.delete(category.name)
      collapsed.value = next
    }
    focusKey.value = presetKey(selected)
    void nextTick(() => elements.get(presetKey(selected))?.scrollIntoView?.({ block: 'nearest' }))
  },
  { immediate: true },
)

function setCollapsed(name: string, value: boolean): void {
  const next = new Set(collapsed.value)
  if (value) next.add(name)
  else next.delete(name)
  collapsed.value = next
}

async function focus(item: Item): Promise<void> {
  focusKey.value = item.key
  if (item.kind === 'preset' && item.preset.id !== props.selectedId) emit('select', item.preset.id)
  await nextTick()
  elements.get(item.key)?.focus()
}

function onKeydown(event: KeyboardEvent): void {
  const items = visible.value
  const index = items.findIndex((item) => item.key === tabKey.value)
  const item = items[index]
  if (item === undefined) return
  const move = (to: Item | undefined) => {
    event.preventDefault()
    if (to !== undefined) void focus(to)
  }
  switch (event.key) {
    case 'ArrowDown':
      return move(items[index + 1])
    case 'ArrowUp':
      return move(items[index - 1])
    case 'Home':
      return move(items[0])
    case 'End':
      return move(items.at(-1))
    case 'ArrowRight':
      if (item.kind !== 'category') return
      event.preventDefault()
      if (collapsed.value.has(item.name)) setCollapsed(item.name, false)
      else void focus(items[index + 1] ?? item)
      return
    case 'ArrowLeft':
      event.preventDefault()
      if (item.kind === 'category') setCollapsed(item.name, true)
      else move(items.find((candidate) => candidate.key === item.parent))
      return
    case 'Enter':
      event.preventDefault()
      if (item.kind === 'category') setCollapsed(item.name, !collapsed.value.has(item.name))
      else emit('apply', item.preset.id)
      return
    case ' ':
      event.preventDefault()
      if (item.kind === 'preset') emit('select', item.preset.id)
      return
    case 'Delete':
      if (item.kind !== 'preset' || item.preset.built_in) return
      event.preventDefault()
      emit('remove', item.preset.id)
      return
  }
}

function register(key: string, element: unknown): void {
  if (element instanceof HTMLElement) elements.set(key, element)
  else elements.delete(key)
}

function clickCategory(name: string): void {
  focusKey.value = categoryKey(name)
  setCollapsed(name, !collapsed.value.has(name))
}

function clickPreset(preset: Preset): void {
  void focus({ key: presetKey(preset.id), kind: 'preset', preset, parent: '' })
}
</script>

<template>
  <ul class="preset-tree" role="tree" :aria-label="t('presets.tree.label')" @keydown="onKeydown">
    <li
      v-for="(category, index) in categories"
      :key="category.name"
      :ref="(element) => register(categoryKey(category.name), element)"
      class="preset-tree__category"
      role="treeitem"
      :aria-expanded="!collapsed.has(category.name)"
      :aria-labelledby="`${id}-c${index}`"
      :tabindex="tabKey === categoryKey(category.name) ? 0 : -1"
      :data-category="category.name"
      @focus.self="focusKey = categoryKey(category.name)"
    >
      <div
        class="preset-tree__row preset-tree__row--category"
        @click="clickCategory(category.name)"
      >
        <ChevronRight class="preset-tree__chevron" :size="16" aria-hidden="true" />
        <span :id="`${id}-c${index}`">{{ category.name }}</span>
        <span class="preset-tree__count">{{ category.presets.length }}</span>
      </div>
      <ul v-if="!collapsed.has(category.name)" role="group" class="preset-tree__group">
        <li
          v-for="preset in category.presets"
          :key="preset.id"
          :ref="(element) => register(presetKey(preset.id), element)"
          class="preset-tree__preset"
          :class="{ 'preset-tree__preset--selected': preset.id === selectedId }"
          role="treeitem"
          :aria-selected="preset.id === selectedId"
          :tabindex="tabKey === presetKey(preset.id) ? 0 : -1"
          :data-preset="preset.id"
          @focus.self="focusKey = presetKey(preset.id)"
          @click.stop="clickPreset(preset)"
          @dblclick.stop="emit('apply', preset.id)"
        >
          <div class="preset-tree__row">
            <span class="preset-tree__name">{{ preset.name }}</span>
            <CircleDot
              v-if="preset.id === currentId"
              class="preset-tree__mark preset-tree__mark--current"
              :size="14"
              aria-hidden="true"
            />
            <span v-if="preset.id === currentId" class="rf-sr-only">{{
              t('presets.tree.current')
            }}</span>
            <Lock v-if="preset.built_in" class="preset-tree__mark" :size="14" aria-hidden="true" />
            <span v-if="preset.built_in" class="rf-sr-only">{{ t('presets.builtIn') }}</span>
            <Star
              v-if="preset.id === defaultId"
              class="preset-tree__mark preset-tree__mark--default"
              :size="14"
              aria-hidden="true"
            />
            <span v-if="preset.id === defaultId" class="rf-sr-only">{{
              t('presets.default')
            }}</span>
          </div>
        </li>
      </ul>
    </li>
  </ul>
</template>

<style scoped>
.preset-tree,
.preset-tree__group {
  margin: 0;
  padding: 0;
  list-style: none;
}

.preset-tree__category {
  outline: none;
}

.preset-tree__row {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
  padding: var(--rf-space-1) var(--rf-space-2);
  border-radius: var(--rf-radius-sm);
  cursor: pointer;
}

.preset-tree__row--category {
  font-weight: var(--rf-font-weight-bold);
}

.preset-tree__chevron {
  flex: none;
  transition: transform var(--rf-duration);
}

[aria-expanded='true'] > .preset-tree__row > .preset-tree__chevron {
  transform: rotate(90deg);
}

.preset-tree__count {
  margin-left: auto;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
  font-weight: var(--rf-font-weight-normal);
}

.preset-tree__preset {
  outline: none;
}

.preset-tree__preset > .preset-tree__row {
  padding-left: calc(var(--rf-space-2) + 16px + var(--rf-space-2));
}

.preset-tree__row:hover {
  background: var(--rf-color-surface-hover);
}

.preset-tree__preset--selected > .preset-tree__row {
  background: var(--p-highlight-background);
  color: var(--p-highlight-color);
}

.preset-tree__category:focus-visible > .preset-tree__row,
.preset-tree__preset:focus-visible > .preset-tree__row {
  outline: 2px solid var(--rf-color-primary);
  outline-offset: -2px;
}

.preset-tree__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preset-tree__mark {
  flex: none;
  color: var(--rf-color-text-muted);
}

.preset-tree__mark--current {
  color: var(--rf-color-primary);
}

.preset-tree__mark--default {
  color: var(--p-status-warn-color);
}
</style>
