<script setup lang="ts">
import { computed } from 'vue'

import { tabForPath, useUiStore } from '@/stores/ui'

/** Text that takes the user to the field of `path` (`ui.reveal`). */
const props = defineProps<{
  /** A validation path: `video.encoder`, `audio[1]`. */
  path: string
  /** The button's accessible name, when the text alone does not say where it goes. */
  label?: string
}>()

defineSlots<{ default(): unknown }>()

const ui = useUiStore()

// A field on a tab that is not built yet cannot be shown: plain text until it is.
const linked = computed(() => tabForPath(props.path) !== 'summary')
</script>

<template>
  <button
    v-if="linked"
    type="button"
    class="summary-link"
    :data-path="path"
    :aria-label="label"
    @click="ui.reveal(path)"
  >
    <slot />
  </button>
  <span v-else class="summary-link summary-link--static" :data-path="path">
    <slot />
  </span>
</template>

<style scoped>
.summary-link {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-1);
  min-width: 0;
  max-width: 100%;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  text-align: start;
}

button.summary-link {
  color: var(--rf-color-primary);
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 0.2em;
  cursor: pointer;
}

button.summary-link:hover {
  text-decoration-thickness: 2px;
}

button.summary-link:focus-visible {
  outline: 2px solid var(--rf-color-primary);
  outline-offset: 2px;
  border-radius: var(--rf-radius-sm);
}
</style>
