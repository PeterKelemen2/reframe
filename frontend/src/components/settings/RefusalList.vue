<script setup lang="ts">
import type { ValidationIssue } from '@/api/types'
import { SEVERITY_ICON, useSeverityLabel } from '@/components/base/severity'

/** Why the server refused a change, for a group of controls that is not one `Field`. */
defineProps<{ issues: ValidationIssue[] }>()

const severityLabel = useSeverityLabel()
</script>

<template>
  <ul v-if="issues.length > 0" class="refusal-list" role="alert">
    <li v-for="(issue, index) in issues" :key="`${issue.code}:${index}`" class="refusal-list__item">
      <component :is="SEVERITY_ICON[issue.severity]" :size="14" aria-hidden="true" />
      <span class="rf-sr-only">{{ severityLabel(issue.severity) }}: </span>
      <span>{{ issue.message }}</span>
    </li>
  </ul>
</template>

<style scoped>
.refusal-list {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
  color: var(--p-status-error-color);
  font-size: var(--rf-font-size-sm);
}

.refusal-list__item {
  display: flex;
  align-items: flex-start;
  gap: var(--rf-space-1);
}

.refusal-list__item svg {
  flex: none;
  margin-top: 0.15em;
}
</style>
