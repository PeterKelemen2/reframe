<script setup lang="ts">
import { ChevronRight } from '@lucide/vue'
import { useId } from 'vue'

/** A titled part of a naming editor that can be folded away (chips, the parsed name). */
defineProps<{
  /** Already translated. */
  title: string
}>()

const open = defineModel<boolean>('open', { default: true })

defineSlots<{ default(): unknown }>()

const bodyId = `${useId()}-body`
</script>

<template>
  <div class="naming-disclosure" :class="{ 'naming-disclosure--open': open }">
    <button
      type="button"
      class="naming-disclosure__toggle"
      :aria-expanded="open"
      :aria-controls="bodyId"
      @click="open = !open"
    >
      <ChevronRight class="naming-disclosure__chevron" :size="16" aria-hidden="true" />
      <span>{{ title }}</span>
    </button>
    <div v-show="open" :id="bodyId" class="naming-disclosure__body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.naming-disclosure {
  display: grid;
  gap: var(--rf-space-2);
  min-width: 0;
}

.naming-disclosure__toggle {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  gap: var(--rf-space-1);
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: var(--rf-radius-sm);
  background: none;
  color: var(--rf-color-text);
  font: inherit;
  font-weight: var(--rf-font-weight-medium);
  cursor: pointer;
}

.naming-disclosure__toggle:focus-visible {
  outline: 2px solid var(--rf-color-primary);
  outline-offset: 2px;
}

.naming-disclosure__chevron {
  transition: transform var(--rf-duration) ease;
}

.naming-disclosure--open .naming-disclosure__chevron {
  transform: rotate(90deg);
}

.naming-disclosure__body {
  min-width: 0;
}
</style>
