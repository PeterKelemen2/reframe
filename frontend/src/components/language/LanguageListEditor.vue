<script setup lang="ts">
import { ArrowDown, ArrowUp, GripVertical, Trash2 } from '@lucide/vue'
import Button from 'primevue/button'
import vTooltip from 'primevue/tooltip'
import { computed, nextTick, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { useSystemStore } from '@/stores/system'

import { type Container, describeTag, writtenAs } from './catalog'
import LanguagePicker from './LanguagePicker.vue'

/**
 * An ordered list of languages (Settings → Languages, the defaults' languages): add through
 * `LanguagePicker`, remove, reorder by drag and by keyboard.
 */
const props = defineProps<{
  label: string
  disabled?: boolean
  /** The id of the add control, for a `Field`'s label. */
  inputId?: string
  /** The id of the label element (`Field`'s `labelId`). */
  labelledby?: string
  /** The ISO 639-2 code shown is the one this container writes (MP4: 639-2/T). */
  container?: Container
}>()

const model = defineModel<string[]>({ required: true })

const { t } = useI18n()
const system = useSystemStore()
const root = useTemplateRef<HTMLElement>('root')

const announcement = ref('')
const dragFrom = ref<number | null>(null)
const dropAt = ref<number | null>(null)

const items = computed(() => {
  const seen = new Map<string, number>()
  return model.value.map((tag) => {
    const language = describeTag(system.languages, tag)
    const written = language ? writtenAs(language, props.container) : null
    // A hand-edited settings file may hold a tag twice.
    const count = (seen.get(tag) ?? 0) + 1
    seen.set(tag, count)
    return {
      key: `${tag}#${count}`,
      tag,
      name: written?.name ?? tag,
      codes: written
        ? t('language.picker.shortCodes', { iso: written.iso639_2, tag: written.tag })
        : null,
    }
  })
})

function nameAt(index: number): string {
  return items.value[index]?.name ?? ''
}

async function focusIn(index: number, selectors: string[]): Promise<void> {
  await nextTick()
  const item = root.value?.querySelectorAll<HTMLElement>('[data-role="item"]')[index]
  for (const selector of selectors) {
    const found = item?.querySelector<HTMLElement>(`${selector}:not(:disabled)`)
    if (found) {
      found.focus()
      return
    }
  }
}

function moved(from: number, to: number): string[] {
  const next = [...model.value]
  const [tag] = next.splice(from, 1)
  if (tag !== undefined) next.splice(to, 0, tag)
  return next
}

/** A move from the buttons keeps the focus on the moved language's button. */
function move(from: number, to: number): void {
  if (to < 0 || to >= model.value.length || to === from) return
  const name = nameAt(from)
  model.value = moved(from, to)
  announcement.value = t('language.list.moved', {
    language: name,
    position: to + 1,
    count: model.value.length,
  })
  const first = to < from ? '[data-move="up"]' : '[data-move="down"]'
  const other = to < from ? '[data-move="down"]' : '[data-move="up"]'
  void focusIn(to, [first, other])
}

async function remove(index: number): Promise<void> {
  const name = nameAt(index)
  const next = model.value.filter((_, i) => i !== index)
  model.value = next
  announcement.value = t('language.list.removed', { language: name })
  const left = next.length
  if (left === 0) {
    await nextTick()
    root.value?.querySelector<HTMLElement>('[data-role="add"] button')?.focus()
    return
  }
  await focusIn(Math.min(index, left - 1), ['[data-action="remove"]'])
}

function add(tag: string | null): void {
  if (tag === null || model.value.includes(tag)) return
  model.value = [...model.value, tag]
  const language = describeTag(system.languages, tag)
  announcement.value = t('language.list.added', { language: language?.english_name ?? tag })
}

function onDragStart(event: DragEvent, index: number): void {
  if (props.disabled) {
    event.preventDefault()
    return
  }
  dragFrom.value = index
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', model.value[index] ?? '')
  }
}

function onDragOver(event: DragEvent, index: number): void {
  if (dragFrom.value === null) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dropAt.value = index
}

function onDrop(event: DragEvent, index: number): void {
  if (dragFrom.value === null) return
  event.preventDefault()
  const from = dragFrom.value
  endDrag()
  if (from !== index) {
    const name = nameAt(from)
    model.value = moved(from, index)
    announcement.value = t('language.list.moved', {
      language: name,
      position: index + 1,
      count: model.value.length,
    })
  }
}

function endDrag(): void {
  dragFrom.value = null
  dropAt.value = null
}

/** Where the dragged language would land: above the item when it comes from below. */
function dropSide(index: number): 'before' | 'after' | null {
  if (dragFrom.value === null || dropAt.value !== index || dragFrom.value === index) return null
  return dragFrom.value > index ? 'before' : 'after'
}
</script>

<template>
  <div ref="root" class="language-list">
    <ol
      v-if="items.length > 0"
      class="language-list__items"
      :aria-label="labelledby ? undefined : label"
      :aria-labelledby="labelledby"
    >
      <li
        v-for="(item, index) in items"
        :key="item.key"
        class="language-list__item"
        :class="[
          dropSide(index) && `language-list__item--drop-${dropSide(index)}`,
          { 'language-list__item--dragging': dragFrom === index },
        ]"
        data-role="item"
        :data-tag="item.tag"
        :draggable="!disabled"
        @dragstart="onDragStart($event, index)"
        @dragover="onDragOver($event, index)"
        @drop="onDrop($event, index)"
        @dragend="endDrag"
      >
        <span v-tooltip.top="t('language.list.drag')" class="language-list__grip">
          <GripVertical :size="16" aria-hidden="true" />
        </span>
        <span class="language-list__number" aria-hidden="true">{{ index + 1 }}</span>
        <span class="language-list__text">
          <span class="language-list__name">{{ item.name }}</span>
          <span v-if="item.codes" class="language-list__codes">{{ ` ${item.codes}` }}</span>
        </span>
        <span class="language-list__buttons">
          <Button
            text
            rounded
            size="small"
            severity="secondary"
            data-move="up"
            :disabled="disabled || index === 0"
            :aria-label="t('language.list.moveUp', { language: item.name })"
            @click="move(index, index - 1)"
          >
            <template #icon><ArrowUp :size="16" aria-hidden="true" /></template>
          </Button>
          <Button
            text
            rounded
            size="small"
            severity="secondary"
            data-move="down"
            :disabled="disabled || index === items.length - 1"
            :aria-label="t('language.list.moveDown', { language: item.name })"
            @click="move(index, index + 1)"
          >
            <template #icon><ArrowDown :size="16" aria-hidden="true" /></template>
          </Button>
          <Button
            text
            rounded
            size="small"
            severity="secondary"
            data-action="remove"
            :disabled="disabled"
            :aria-label="t('language.list.remove', { language: item.name })"
            @click="remove(index)"
          >
            <template #icon><Trash2 :size="16" aria-hidden="true" /></template>
          </Button>
        </span>
      </li>
    </ol>
    <p v-else class="language-list__empty" data-state="empty">{{ t('language.list.empty') }}</p>
    <span data-role="add" class="language-list__add">
      <LanguagePicker
        :model-value="null"
        :input-id="inputId"
        :label="t('language.list.addTo', { label })"
        :placeholder="t('language.list.add')"
        :disabled="disabled"
        :container="container"
        :exclude="model"
        @update:model-value="add"
      />
    </span>
    <span class="rf-sr-only" aria-live="polite">{{ announcement }}</span>
  </div>
</template>

<style scoped>
.language-list {
  display: grid;
  gap: var(--rf-space-2);
  justify-items: start;
}

.language-list__items {
  display: grid;
  width: 100%;
  max-width: 34rem;
  margin: 0;
  padding: 0;
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md);
  list-style: none;
}

.language-list__item {
  position: relative;
  display: grid;
  grid-template-columns: auto 1.5rem minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--rf-space-2);
  padding: var(--rf-space-1) var(--rf-space-2);
}

.language-list__item + .language-list__item {
  border-top: 1px solid var(--rf-color-border);
}

.language-list__item[draggable='true'] .language-list__grip {
  cursor: grab;
}

.language-list__item--dragging {
  opacity: 0.5;
}

.language-list__item--drop-before::before,
.language-list__item--drop-after::after {
  position: absolute;
  inset-inline: 0;
  height: 2px;
  background: var(--rf-color-primary);
  content: '';
}

.language-list__item--drop-before::before {
  top: -1px;
}

.language-list__item--drop-after::after {
  bottom: -1px;
}

.language-list__grip {
  color: var(--rf-color-text-muted);
}

.language-list__number {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  font-variant-numeric: tabular-nums;
  text-align: end;
}

.language-list__text {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--rf-space-2);
  min-width: 0;
}

.language-list__codes,
.language-list__empty {
  color: var(--rf-color-text-muted);
}

.language-list__codes {
  font-size: var(--rf-font-size-sm);
}

.language-list__empty {
  margin: 0;
}

.language-list__buttons {
  display: flex;
  gap: var(--rf-space-1);
}
</style>
