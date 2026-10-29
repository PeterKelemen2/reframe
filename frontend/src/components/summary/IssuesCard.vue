<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Severity, ValidationIssue } from '@/api/types'
import Card from '@/components/base/Card.vue'
import IssueList from '@/components/base/IssueList.vue'
import { SEVERITY_ICON } from '@/components/base/severity'
import { useValidationStore } from '@/stores/validation'

const SEVERITIES: Severity[] = ['error', 'warning', 'info']

const { t } = useI18n()
const validation = useValidationStore()

const groups = computed(() =>
  SEVERITIES.map((severity) => ({
    severity,
    issues: validation.issues.filter((issue) => issue.severity === severity),
  })).filter((group) => group.issues.length > 0),
)

function heading(severity: Severity, issues: ValidationIssue[]): string {
  switch (severity) {
    case 'error':
      return t('summary.issues.errors', issues.length)
    case 'warning':
      return t('summary.issues.warnings', issues.length)
    case 'info':
      return t('summary.issues.infos', issues.length)
  }
  return severity
}
</script>

<template>
  <Card
    class="summary-card summary-card--wide summary-issues"
    :title="t('summary.issues.title')"
    data-card="issues"
  >
    <template v-if="validation.pending" #actions>
      <span class="summary-card__note" data-state="checking">{{
        t('summary.issues.checking')
      }}</span>
    </template>
    <IssueList v-if="groups.length === 0" :issues="[]" />
    <div v-else class="summary-issues__groups">
      <section
        v-for="group in groups"
        :key="group.severity"
        class="summary-issues__group"
        :data-severity="group.severity"
      >
        <h4 class="summary-card__subtitle summary-issues__heading" :class="`is-${group.severity}`">
          <component :is="SEVERITY_ICON[group.severity]" :size="16" aria-hidden="true" />
          {{ heading(group.severity, group.issues) }}
        </h4>
        <IssueList :issues="group.issues" />
      </section>
    </div>
  </Card>
</template>

<style scoped>
.summary-issues__groups,
.summary-issues__group {
  display: grid;
  gap: var(--rf-space-2);
}

.summary-issues__groups {
  gap: var(--rf-space-4);
}

.summary-issues__heading {
  display: flex;
  align-items: center;
  gap: var(--rf-space-1);
}

.summary-issues__heading.is-error {
  color: var(--p-status-error-color);
}

.summary-issues__heading.is-warning {
  color: var(--p-status-warn-color);
}

.summary-issues__heading.is-info {
  color: var(--p-status-info-color);
}
</style>
