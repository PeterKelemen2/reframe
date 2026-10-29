<script setup lang="ts">
defineProps<{
  /** Already translated. */
  title?: string
}>()

defineSlots<{ default(): unknown; header?(): unknown; actions?(): unknown }>()
</script>

<template>
  <article class="card">
    <slot name="header">
      <h3 v-if="title">{{ title }}</h3>
    </slot>
    <slot name="actions" />
    <slot />
  </article>
</template>
