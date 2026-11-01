<script setup lang="ts">
import Button from 'primevue/button'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Fix, ValidationIssue } from '@/api/types'
import { bySeverity, SEVERITY_ICON, useSeverityLabel } from '@/components/base/severity'
import { useEditorStore } from '@/stores/editor'

/** One matrix row's errors and warnings with their fixes; its notes folded. */
const props = defineProps<{ sourceId: string; label: string; issues: ValidationIssue[] }>()

const emit = defineEmits<{ done: [] }>()

const { t } = useI18n()
const severityLabel = useSeverityLabel()
const editor = useEditorStore()

const problems = computed(() => bySeverity(props.issues.filter((i) => i.severity !== 'info')))
const notes = computed(() => props.issues.filter((issue) => issue.severity === 'info'))
/** Every fix button waits for the fix under way, so that two fixes never race. */
const applying = ref<Fix | null>(null)

async function apply(fix: Fix): Promise<void> {
  if (applying.value !== null) return
  applying.value = fix
  try {
    await editor.applyRowFix(props.sourceId, fix)
    emit('done')
  } finally {
    applying.value = null
  }
}
</script>

<template>
  <div class="row-issues">
    <p class="row-issues__title">{{ t('matrix.issues.title', { label }) }}</p>
    <p v-if="problems.length === 0" class="row-issues__none">{{ t('matrix.issues.none') }}</p>
    <ul v-else class="row-issues__list">
      <li
        v-for="(issue, index) in problems"
        :key="`${issue.code}:${index}`"
        class="row-issues__issue"
        :data-severity="issue.severity"
        :data-code="issue.code"
      >
        <component
          :is="SEVERITY_ICON[issue.severity]"
          class="row-issues__icon"
          :size="16"
          aria-hidden="true"
        />
        <span>
          <span class="rf-sr-only">{{ severityLabel(issue.severity) }}: </span>
          {{ issue.message }}
        </span>
        <span v-if="(issue.fixes ?? []).length > 0" class="row-issues__fixes">
          <Button
            v-for="(fix, fixIndex) in issue.fixes ?? []"
            :key="fix.label"
            size="small"
            severity="secondary"
            outlined
            :label="fix.label"
            :loading="applying === fix"
            :disabled="applying !== null"
            :autofocus="(index === 0 && fixIndex === 0) || undefined"
            data-role="fix"
            @click="apply(fix)"
          />
        </span>
      </li>
    </ul>
    <details v-if="notes.length > 0" class="row-issues__notes">
      <summary>{{ t('matrix.issues.notes', notes.length) }}</summary>
      <ul class="row-issues__list">
        <li v-for="(issue, index) in notes" :key="`${issue.code}:${index}`" data-severity="info">
          {{ issue.message }}
        </li>
      </ul>
    </details>
  </div>
</template>

<style scoped>
.row-issues {
  display: grid;
  gap: var(--rf-space-2);
  max-width: 36rem;
}

.row-issues p {
  margin: 0;
}

.row-issues__title {
  font-weight: var(--rf-font-weight-medium);
}

.row-issues__none,
.row-issues__notes {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.row-issues__list {
  display: grid;
  gap: var(--rf-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.row-issues__issue {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--rf-space-1) var(--rf-space-2);
}

.row-issues__issue[data-severity='error'] .row-issues__icon {
  color: var(--p-status-error-color);
}

.row-issues__issue[data-severity='warning'] .row-issues__icon {
  color: var(--p-status-warn-color);
}

.row-issues__icon {
  margin-top: 0.15rem;
}

.row-issues__fixes {
  display: flex;
  flex-wrap: wrap;
  grid-column: 2;
  gap: var(--rf-space-2);
}
</style>
