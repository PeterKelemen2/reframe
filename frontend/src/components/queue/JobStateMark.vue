<script setup lang="ts">
import type { JobState } from '@/api/types'
import type { StatusTone } from '@/components/base/types'

import { STATE_ICON } from './stateIcons'

/** A job's state as an icon and its name, both in the state's colour. */
defineProps<{
  state: JobState
  tone: StatusTone
  /** Already translated. */
  label: string
}>()
</script>

<template>
  <span class="job-state" :class="`job-state--${tone}`" :data-tone="tone" data-field="state">
    <component
      :is="STATE_ICON[state]"
      class="job-state__icon"
      :class="{ 'job-state__icon--turning': state === 'running' }"
      :size="16"
      aria-hidden="true"
    />
    <span>{{ label }}</span>
  </span>
</template>

<style scoped>
.job-state {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-2);
  color: var(--job-state-color);
  white-space: nowrap;
}

.job-state__icon {
  flex: none;
}

.job-state__icon--turning {
  animation: job-state-turn 1.2s linear infinite;
}

@keyframes job-state-turn {
  to {
    transform: rotate(360deg);
  }
}

.job-state--ok {
  --job-state-color: var(--p-status-ok-color);
}

/* Running is the normal work of the queue: ink, not a hue. */
.job-state--busy {
  --job-state-color: var(--rf-color-text);
}

.job-state--warn {
  --job-state-color: var(--p-status-warn-color);
}

.job-state--error {
  --job-state-color: var(--p-status-error-color);
}

.job-state--off {
  --job-state-color: var(--rf-color-text-muted);
}
</style>
