<script setup lang="ts">
defineProps<{
  /** Already translated. */
  title?: string
}>()

defineSlots<{ default(): unknown; header?(): unknown; actions?(): unknown }>()
</script>

<template>
  <article class="rf-card">
    <header v-if="title || $slots.header || $slots.actions" class="rf-card__header">
      <div class="rf-card__title">
        <slot name="header">
          <h3>{{ title }}</h3>
        </slot>
      </div>
      <div v-if="$slots.actions" class="rf-card__actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="rf-card__body">
      <slot />
    </div>
  </article>
</template>

<style scoped>
.rf-card {
  display: grid;
  gap: var(--rf-space-3);
  min-width: 0;
  padding: var(--rf-space-4);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-lg);
  background: var(--rf-color-surface);
  color: var(--rf-color-text);
}

.rf-card__header {
  display: flex;
  align-items: center;
  gap: var(--rf-space-3);
}

.rf-card__title {
  flex: 1;
  min-width: 0;
}

.rf-card__title h3 {
  margin: 0;
  font-size: var(--rf-font-size-md);
  font-weight: var(--rf-font-weight-bold);
  line-height: var(--rf-line-height-tight);
}

.rf-card__actions {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.rf-card__body {
  min-width: 0;
}
</style>
