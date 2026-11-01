<script setup lang="ts">
import Button from 'primevue/button'
import { computed } from 'vue'

import type { Fix, ValidationIssue } from '@/api/types'
import { bySeverity, SEVERITY_ICON, useSeverityLabel } from '@/components/base/severity'
import { useDefaultsStore } from '@/stores/defaults'

/** The issues of one rule, field or the whole defaults; `fixes` adds their fix buttons. */
const props = defineProps<{
  issues: readonly ValidationIssue[]
  id?: string
  fixes?: boolean
}>()

const defaults = useDefaultsStore()
const severityLabel = useSeverityLabel()

const sorted = computed(() => bySeverity(props.issues))

/** Fixes that change another part of the template (the container) are not the dialog's to make. */
function offered(issue: ValidationIssue): Fix[] {
  return (issue.fixes ?? []).filter((fix) => defaults.offersFix(fix))
}
</script>

<template>
  <ul v-if="sorted.length > 0" :id="id" class="defaults-issues">
    <li
      v-for="(issue, index) in sorted"
      :key="`${issue.code}:${index}`"
      class="defaults-issues__issue"
      :class="`defaults-issues__issue--${issue.severity}`"
      :data-code="issue.code"
      :data-severity="issue.severity"
    >
      <component
        :is="SEVERITY_ICON[issue.severity]"
        class="defaults-issues__icon"
        :size="14"
        aria-hidden="true"
      />
      <span class="rf-sr-only">{{ severityLabel(issue.severity) }}: </span>
      <span class="defaults-issues__message">{{ issue.message }}</span>
      <span v-if="fixes && offered(issue).length > 0" class="defaults-issues__fixes">
        <Button
          v-for="fix in offered(issue)"
          :key="fix.label"
          size="small"
          severity="secondary"
          outlined
          data-action="fix"
          :label="fix.label"
          :disabled="defaults.previewing"
          @click="defaults.applyFix(fix)"
        />
      </span>
    </li>
  </ul>
</template>

<style scoped>
.defaults-issues {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--rf-font-size-sm);
}

.defaults-issues__issue {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: var(--rf-space-1) var(--rf-space-2);
}

.defaults-issues__icon {
  flex: none;
  margin-top: 0.15rem;
}

.defaults-issues__issue--error .defaults-issues__icon {
  color: var(--p-status-error-color);
}

.defaults-issues__issue--warning .defaults-issues__icon {
  color: var(--p-status-warn-color);
}

.defaults-issues__issue--info .defaults-issues__icon {
  color: var(--p-status-info-color);
}

.defaults-issues__message {
  flex: 1 1 16rem;
  min-width: 0;
}

.defaults-issues__fixes {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-1);
}
</style>
