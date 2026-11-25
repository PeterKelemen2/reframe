<script setup lang="ts">
/** One term and its value in a `<dl>` (`rf-kv-list` aligns the labels); the default slot replaces `value`. */
defineProps<{
  /** Already translated. */
  label: string
  /** Empty, `null` or missing: a dash. */
  value?: string | number | null
  /** A measured value (size, duration, bitrate): set in the mono face. */
  mono?: boolean
}>()

defineSlots<{ default?(): unknown }>()
</script>

<template>
  <div class="rf-kv">
    <dt>{{ label }}</dt>
    <dd :class="{ 'rf-mono': mono }">
      <slot>{{ value === null || value === undefined || value === '' ? '—' : value }}</slot>
    </dd>
  </div>
</template>

<style scoped>
.rf-kv {
  display: contents;
}

dt {
  color: var(--rf-color-text-muted);
}

dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}
</style>
