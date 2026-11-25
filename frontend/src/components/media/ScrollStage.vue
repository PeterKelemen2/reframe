<script setup lang="ts">
import { useTemplateRef } from 'vue'

import { usePanOnSpace } from './zoom'

defineProps<{
  role?: string
  /** The stage's accessible name. */
  label?: string
  tabindex?: number
}>()

const root = useTemplateRef<HTMLElement>('root')
const { ready, dragging } = usePanOnSpace(root)

defineExpose({ focus: () => root.value?.focus() })
</script>

<template>
  <div
    ref="root"
    class="scroll-stage"
    :role="role"
    :aria-label="label"
    :tabindex="tabindex"
    :data-pan="dragging ? 'dragging' : ready ? 'ready' : undefined"
  >
    <slot />
  </div>
</template>

<style scoped>
.scroll-stage {
  overflow: auto;
  max-height: 70vh;
}

.scroll-stage:focus-visible {
  outline: 2px solid var(--rf-color-primary);
  outline-offset: 2px;
}

.scroll-stage[data-pan] {
  cursor: grab;
}

.scroll-stage[data-pan='dragging'] {
  cursor: grabbing;
}

/* The press must land on the stage, not on a handle or the split slider inside it. */
.scroll-stage[data-pan] :deep(*) {
  pointer-events: none;
}
</style>
