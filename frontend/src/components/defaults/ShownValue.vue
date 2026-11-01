<script setup lang="ts">
/** A read-only value in place of its control: the whole text, wrapped, in the text colour. */
defineProps<{ text: string }>()
</script>

<template>
  <span class="shown-value" data-role="shown-value">{{ text }}</span>
</template>

<style scoped>
.shown-value {
  display: block;
  min-width: 0;
  color: var(--rf-color-text);
  overflow-wrap: anywhere;
}
</style>
