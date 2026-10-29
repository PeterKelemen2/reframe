<script setup lang="ts">
import { computed } from 'vue'

import type { ValidationIssue } from '@/api/types'
import { bySeverity, SEVERITY_ICON, useSeverityLabel } from '@/components/base/severity'

/**
 * The preview's issues that belong to no field here, as messages. Their fixes are not offered:
 * a naming preview has no job to patch (the job's own validation lists them with fixes).
 */
const props = defineProps<{ issues: ValidationIssue[] }>()

const severityLabel = useSeverityLabel()
const sorted = computed(() => bySeverity(props.issues))
</script>

<template>
  <ul v-if="sorted.length > 0" class="naming-issues">
    <li
      v-for="(issue, index) in sorted"
      :key="`${issue.code}:${index}`"
      class="naming-issues__item"
      :class="`naming-issues__item--${issue.severity}`"
    >
      <component :is="SEVERITY_ICON[issue.severity]" :size="14" aria-hidden="true" />
      <span class="rf-sr-only">{{ severityLabel(issue.severity) }}: </span>
      <span>{{ issue.message }}</span>
    </li>
  </ul>
</template>

<style scoped>
.naming-issues {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--rf-font-size-sm);
}

.naming-issues__item {
  display: flex;
  align-items: flex-start;
  gap: var(--rf-space-1);
}

.naming-issues__item svg {
  flex: none;
  margin-top: 0.15em;
}

.naming-issues__item--error {
  color: var(--p-status-error-color);
}

.naming-issues__item--warning {
  color: var(--p-status-warn-color);
}

.naming-issues__item--info {
  color: var(--p-status-info-color);
}
</style>
