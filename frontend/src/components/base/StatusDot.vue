<script setup lang="ts">
import type { StatusTone } from './types'

defineProps<{
  tone: StatusTone
  /** Already translated; read by screen readers and shown as the tooltip. */
  label: string
}>()
</script>

<template>
  <span class="status-dot" :aria-label="label" />
</template>
