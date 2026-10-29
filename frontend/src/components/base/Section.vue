<script setup lang="ts">
import { ChevronRight } from '@lucide/vue'
import { useId } from 'vue'

defineProps<{
  /** Already translated. */
  title: string
  collapsible?: boolean
}>()

const collapsed = defineModel<boolean>('collapsed', { default: false })

defineSlots<{ default(): unknown; actions?(): unknown }>()

const id = useId()
const headingId = `${id}-title`
const bodyId = `${id}-body`
</script>

<template>
  <section
    class="rf-section"
    :class="{ 'rf-section--collapsed': collapsible && collapsed }"
    :aria-labelledby="headingId"
  >
    <header class="rf-section__header">
      <h2 :id="headingId" class="rf-section__title">
        <button
          v-if="collapsible"
          type="button"
          class="rf-section__toggle"
          :aria-expanded="!collapsed"
          :aria-controls="bodyId"
          @click="collapsed = !collapsed"
        >
          <ChevronRight class="rf-section__chevron" :size="18" aria-hidden="true" />
          <span>{{ title }}</span>
        </button>
        <template v-else>{{ title }}</template>
      </h2>
      <div v-if="$slots.actions" class="rf-section__actions">
        <slot name="actions" />
      </div>
    </header>
    <div v-show="!collapsible || !collapsed" :id="bodyId" class="rf-section__body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.rf-section {
  display: grid;
  gap: var(--rf-space-3);
}

.rf-section__header {
  display: flex;
  align-items: center;
  gap: var(--rf-space-3);
  min-height: 2rem;
  border-bottom: 1px solid var(--rf-color-border);
  padding-bottom: var(--rf-space-1);
}

.rf-section__title {
  flex: 1;
  margin: 0;
  color: var(--rf-color-text);
  font-size: var(--rf-font-size-lg);
  font-weight: var(--rf-font-weight-bold);
  line-height: var(--rf-line-height-tight);
}

.rf-section__toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: var(--rf-radius-sm);
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.rf-section__chevron {
  transform: rotate(90deg);
  transition: transform var(--rf-duration) ease;
}

.rf-section--collapsed .rf-section__chevron {
  transform: none;
}

.rf-section__actions {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.rf-section__body {
  display: grid;
  gap: var(--rf-space-3);
}
</style>
