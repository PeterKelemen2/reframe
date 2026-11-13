<script setup lang="ts">
import { computed, nextTick, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { useCropStore } from '@/stores/crop'
import { useEditorStore } from '@/stores/editor'
import { useUiStore } from '@/stores/ui'

import { EDGES, type Edge, snapCrop } from './grid'

const { t } = useI18n()
const crop = useCropStore()
const editor = useEditorStore()
const ui = useUiStore()
const root = useTemplateRef<HTMLElement>('root')

/** Arrow presses per Shift + arrow press, and per Page Up or Page Down. */
const SHIFT_STEPS = 8
const INWARD: Record<Edge, string> = {
  top: 'ArrowDown',
  bottom: 'ArrowUp',
  left: 'ArrowRight',
  right: 'ArrowLeft',
}
const OUTWARD: Record<Edge, string> = {
  top: 'ArrowUp',
  bottom: 'ArrowDown',
  left: 'ArrowLeft',
  right: 'ArrowRight',
}

const shown = computed(
  () =>
    ui.activeTab === 'dimensions' &&
    crop.pictureEditable &&
    crop.rect !== null &&
    crop.sourceSize !== null,
)

// Handles that go away with the focus (an undo past *Manual*) hand it to the crop mode.
watch(
  () => crop.editable,
  async (editable) => {
    const focused = document.activeElement
    if (editable || !(focused instanceof HTMLElement) || !root.value?.contains(focused)) return
    await nextTick()
    document.querySelector<HTMLElement>('[data-control="crop-mode"] [aria-pressed="true"]')?.focus()
  },
)

/** Each edge in percent of the picture's box. */
const inset = computed<Record<Edge, number>>(() => {
  const rect = crop.rect
  const size = crop.sourceSize
  if (rect === null || size === null) return { top: 0, bottom: 0, left: 0, right: 0 }
  return {
    top: (rect.top / size.height) * 100,
    bottom: (rect.bottom / size.height) * 100,
    left: (rect.left / size.width) * 100,
    right: (rect.right / size.width) * 100,
  }
})

const across = (edge: Edge) => edge === 'left' || edge === 'right'

function handleStyle(edge: Edge): Record<string, string> {
  const { top, bottom, left, right } = inset.value
  const middleX = `${(left + 100 - right) / 2}%`
  const middleY = `${(top + 100 - bottom) / 2}%`
  switch (edge) {
    case 'top':
      return { top: `${top}%`, left: middleX }
    case 'bottom':
      return { top: `${100 - bottom}%`, left: middleX }
    case 'left':
      return { top: middleY, left: `${left}%` }
    case 'right':
      return { top: middleY, left: `${100 - right}%` }
  }
}

function move(edge: Edge, value: number, key: string): void {
  if (crop.rect === null) return
  crop.setRect({ ...crop.rect, [edge]: value }, { coalesce: key, quiet: true })
}

/** The largest crop of `edge` that leaves a picture, with the other edges as they are. */
function maxOf(edge: Edge): number {
  const { rect, grid, sourceSize } = crop
  if (rect === null || grid === null || sourceSize === null) return 0
  const size = across(edge) ? sourceSize.width : sourceSize.height
  return snapCrop({ ...rect, [edge]: size }, rect, grid).rect[edge]
}

/**
 * The arrows move a handle where they point. Page Up and Page Down move the top and bottom
 * handles the same way, and the left and right ones inward and outward (the slider's value).
 */
function directionOf(edge: Edge, key: string): number {
  if (key === INWARD[edge]) return 1
  if (key === OUTWARD[edge]) return -1
  if (key !== 'PageUp' && key !== 'PageDown') return 0
  const up = key === 'PageUp'
  if (across(edge)) return up ? 1 : -1
  return (edge === 'bottom') === up ? 1 : -1
}

function onKey(edge: Edge, event: KeyboardEvent): void {
  const paging = event.key === 'PageUp' || event.key === 'PageDown'
  const ends = event.key === 'Home' || event.key === 'End'
  if (!event.key.startsWith('Arrow') && !paging && !ends) return
  // The panel's ←/→ step through the frames and its keys scroll; on a handle they move the edge.
  event.preventDefault()
  event.stopPropagation()
  const grid = crop.grid
  if (grid === null || crop.rect === null) return
  const key = `crop.keys.${edge}`
  if (ends) {
    move(edge, event.key === 'Home' ? 0 : maxOf(edge), key)
    return
  }
  const direction = directionOf(edge, event.key)
  if (direction === 0) return
  const steps = paging || event.shiftKey ? SHIFT_STEPS : 1
  const step = (across(edge) ? grid.stepX : grid.stepY) * steps
  move(edge, crop.rect[edge] + direction * step, key)
}

let drag: { edge: Edge; key: string } | null = null
let drags = 0

function onPointerDown(edge: Edge, event: PointerEvent): void {
  if (event.button !== 0) return
  event.preventDefault()
  const handle = event.currentTarget as HTMLElement
  handle.setPointerCapture(event.pointerId)
  handle.focus()
  drags += 1
  drag = { edge, key: `crop.drag.${drags}` }
}

function onPointerMove(event: PointerEvent): void {
  const box = root.value?.getBoundingClientRect()
  const size = crop.sourceSize
  if (drag === null || !box || size === null) return
  const x = ((event.clientX - box.left) / box.width) * size.width
  const y = ((event.clientY - box.top) / box.height) * size.height
  const value = { top: y, bottom: size.height - y, left: x, right: size.width - x }[drag.edge]
  move(drag.edge, Math.round(value), drag.key)
}

function onPointerUp(): void {
  if (drag === null) return
  drag = null
  editor.endCoalescing()
}
</script>

<template>
  <div v-if="shown" ref="root" class="crop-overlay" data-overlay="crop">
    <div
      class="crop-overlay__removed"
      :style="{ top: 0, left: 0, right: 0, height: `${inset.top}%` }"
    />
    <div
      class="crop-overlay__removed"
      :style="{ bottom: 0, left: 0, right: 0, height: `${inset.bottom}%` }"
    />
    <div
      class="crop-overlay__removed"
      :style="{
        top: `${inset.top}%`,
        bottom: `${inset.bottom}%`,
        left: 0,
        width: `${inset.left}%`,
      }"
    />
    <div
      class="crop-overlay__removed"
      :style="{
        top: `${inset.top}%`,
        bottom: `${inset.bottom}%`,
        right: 0,
        width: `${inset.right}%`,
      }"
    />
    <div
      class="crop-overlay__frame"
      :style="{
        top: `${inset.top}%`,
        bottom: `${inset.bottom}%`,
        left: `${inset.left}%`,
        right: `${inset.right}%`,
      }"
    />
    <template v-if="crop.editable && crop.rect !== null && crop.sourceSize !== null">
      <div
        v-for="edge in EDGES"
        :key="edge"
        class="crop-overlay__handle"
        :class="[
          `crop-overlay__handle--${across(edge) ? 'across' : 'down'}`,
          `crop-overlay__handle--${edge}`,
        ]"
        :style="handleStyle(edge)"
        role="slider"
        tabindex="0"
        :aria-label="t('dimensions.overlay.handle', { edge: t(`dimensions.crop.edges.${edge}`) })"
        :aria-orientation="across(edge) ? 'horizontal' : 'vertical'"
        :aria-valuenow="crop.rect[edge]"
        aria-valuemin="0"
        :aria-valuemax="maxOf(edge)"
        :aria-valuetext="t('dimensions.overlay.handleValue', { value: crop.rect[edge] })"
        :data-crop-handle="edge"
        @keydown="onKey(edge, $event)"
        @blur="editor.endCoalescing()"
        @pointerdown="onPointerDown(edge, $event)"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
      />
    </template>
  </div>
</template>

<style scoped>
.crop-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.crop-overlay__removed {
  position: absolute;
  background: rgb(0 0 0 / 55%);
}

/* Light and dark lines together stay visible on any picture. */
.crop-overlay__frame {
  position: absolute;
  outline: 1px solid rgb(255 255 255 / 90%);
  box-shadow: 0 0 0 2px rgb(0 0 0 / 60%);
}

.crop-overlay__handle {
  position: absolute;
  border: 1px solid rgb(0 0 0 / 70%);
  border-radius: 999px;
  background: rgb(255 255 255 / 95%);
  pointer-events: auto;
  touch-action: none;
}

/* Each handle sits on the kept side of its line, so that it stays inside the picture's box
   (the stage clips what is outside) even with no crop on that edge. */
.crop-overlay__handle--top {
  transform: translate(-50%, 0);
}

.crop-overlay__handle--bottom {
  transform: translate(-50%, -100%);
}

.crop-overlay__handle--left {
  transform: translate(0, -50%);
}

.crop-overlay__handle--right {
  transform: translate(-100%, -50%);
}

.crop-overlay__handle--down {
  width: 2.5rem;
  height: 0.75rem;
  cursor: ns-resize;
}

.crop-overlay__handle--across {
  width: 0.75rem;
  height: 2.5rem;
  cursor: ew-resize;
}

/* White inside black, as the crop frame: one of them stands out on any picture. */
.crop-overlay__handle:focus-visible {
  outline: 3px solid #fff;
  outline-offset: 0;
  box-shadow: 0 0 0 6px #000;
}
</style>
