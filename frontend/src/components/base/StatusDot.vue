<script setup lang="ts">
import vTooltip from 'primevue/tooltip'

import type { StatusTone } from './types'

/** A coloured mark whose shape also tells the tone apart, for readers who do not see colour. */
defineProps<{
  tone: StatusTone
  /** Already translated; read by screen readers and shown as the tooltip. */
  label: string
  /** The label as text beside the dot instead of only in the tooltip. */
  showLabel?: boolean
}>()
</script>

<template>
  <span
    v-if="showLabel"
    class="rf-status-dot rf-status-dot--labelled"
    :class="`rf-status-dot--${tone}`"
    :data-tone="tone"
  >
    <span class="rf-status-dot__mark" aria-hidden="true" />
    <span>{{ label }}</span>
  </span>
  <span
    v-else
    v-tooltip.top="label"
    class="rf-status-dot"
    :class="`rf-status-dot--${tone}`"
    :data-tone="tone"
    role="img"
    :aria-label="label"
  >
    <span class="rf-status-dot__mark" />
  </span>
</template>

<style scoped>
.rf-status-dot {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-2);
  vertical-align: middle;
}

.rf-status-dot__mark {
  flex: none;
  box-sizing: border-box;
  width: 0.625rem;
  height: 0.625rem;
  border: 2px solid var(--rf-dot-color);
  border-radius: 50%;
  background: var(--rf-dot-color);
}

.rf-status-dot--ok {
  --rf-dot-color: var(--p-status-ok-color);
}

.rf-status-dot--busy {
  --rf-dot-color: var(--p-status-busy-color);
}

.rf-status-dot--warn {
  --rf-dot-color: var(--p-status-warn-color);
}

.rf-status-dot--error {
  --rf-dot-color: var(--p-status-error-color);
}

.rf-status-dot--off {
  --rf-dot-color: var(--p-status-off-color);
}

/* ok: filled circle; warn: diamond; error: square; off: ring; busy: a turning arc. */
.rf-status-dot--warn .rf-status-dot__mark {
  border-radius: 1px;
  transform: rotate(45deg) scale(0.85);
}

.rf-status-dot--error .rf-status-dot__mark {
  border-radius: 1px;
}

.rf-status-dot--off .rf-status-dot__mark {
  background: transparent;
}

.rf-status-dot--busy .rf-status-dot__mark {
  border-right-color: transparent;
  background: transparent;
  animation: rf-status-turn 0.9s linear infinite;
}

@keyframes rf-status-turn {
  to {
    transform: rotate(360deg);
  }
}
</style>
