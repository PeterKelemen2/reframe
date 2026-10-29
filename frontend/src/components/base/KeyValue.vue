<script setup lang="ts">
/** One term and its value in a `<dl>`; the default slot replaces `value`. */
defineProps<{
  /** Already translated. */
  label: string
  value?: string | number | null
}>()

defineSlots<{ default?(): unknown }>()
</script>

<template>
  <div class="key-value">
    <dt>{{ label }}</dt>
    <dd>
      <slot>{{ value }}</slot>
    </dd>
  </div>
</template>
