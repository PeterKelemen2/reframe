<script setup lang="ts">
import { ArrowDown, ArrowUp, Trash2 } from '@lucide/vue'
import Button from 'primevue/button'
import { computed, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ValidationIssue } from '@/api/types'
import IssueList from '@/components/base/IssueList.vue'
import { SEVERITY_ICON, useSeverityLabel } from '@/components/base/severity'
import { useReveal } from '@/composables/useReveal'
import { useValidationStore } from '@/stores/validation'

/**
 * One output track's frame: its number, issue mark, move and remove buttons, and the issues
 * that no field of the row shows. `ui.reveal(path)` lands on it.
 */
const props = defineProps<{
  /** `audio[2]`. */
  path: string
  index: number
  count: number
  /** The validation paths the row's fields show (their issues are not listed again). */
  fieldPaths: readonly string[]
}>()

const emit = defineEmits<{ move: [to: number]; remove: [] }>()

defineSlots<{ header(): unknown; default(): unknown }>()

const { t } = useI18n()
const severityLabel = useSeverityLabel()
const validation = useValidationStore()
const root = useTemplateRef<HTMLElement>('root')

useReveal(() => props.path, root)

const issues = computed(() => validation.issuesFor(props.path, { nested: true }))
const severity = computed(() => issues.value[0]?.severity ?? null)
const unplaced = computed<ValidationIssue[]>(() =>
  issues.value.filter((issue) => !props.fieldPaths.includes(issue.path)),
)
</script>

<template>
  <div
    ref="root"
    class="track-row"
    :class="severity && `track-row--${severity}`"
    :data-path="path"
    :data-severity="severity ?? undefined"
  >
    <div class="track-row__header">
      <span class="track-row__number">{{ index + 1 }}</span>
      <template v-if="severity">
        <component
          :is="SEVERITY_ICON[severity]"
          class="track-row__mark"
          :size="16"
          aria-hidden="true"
        />
        <span class="rf-sr-only">{{ severityLabel(severity) }}</span>
      </template>
      <div class="track-row__lead">
        <slot name="header" />
      </div>
      <div class="track-row__buttons">
        <Button
          text
          rounded
          size="small"
          severity="secondary"
          data-move="up"
          :disabled="index === 0"
          :aria-label="t('tracks.output.moveUp', { n: index + 1 })"
          @click="emit('move', index - 1)"
        >
          <template #icon><ArrowUp :size="18" aria-hidden="true" /></template>
        </Button>
        <Button
          text
          rounded
          size="small"
          severity="secondary"
          data-move="down"
          :disabled="index >= count - 1"
          :aria-label="t('tracks.output.moveDown', { n: index + 1 })"
          @click="emit('move', index + 1)"
        >
          <template #icon><ArrowDown :size="18" aria-hidden="true" /></template>
        </Button>
        <Button
          text
          rounded
          size="small"
          severity="danger"
          data-action="remove"
          :aria-label="t('tracks.output.remove', { n: index + 1 })"
          @click="emit('remove')"
        >
          <template #icon><Trash2 :size="18" aria-hidden="true" /></template>
        </Button>
      </div>
    </div>
    <slot />
    <IssueList v-if="unplaced.length > 0" class="track-row__issues" :issues="unplaced" compact />
  </div>
</template>

<style scoped>
/* Size containment: the row wraps its fields to the tab's width instead of widening the table. */
.track-row {
  contain: inline-size;
  display: grid;
  gap: var(--rf-space-3);
  min-width: 0;
  padding: var(--rf-space-2) 0;
}

.track-row__header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
}

.track-row__number {
  display: inline-grid;
  flex: none;
  place-items: center;
  min-width: 1.75rem;
  height: 1.75rem;
  border-radius: 50%;
  background: var(--p-status-off-background);
  font-size: var(--rf-font-size-sm);
  font-weight: var(--rf-font-weight-bold);
}

.track-row--error .track-row__number {
  background: var(--p-status-error-background);
  color: var(--p-status-error-color);
}

.track-row--warning .track-row__number {
  background: var(--p-status-warn-background);
  color: var(--p-status-warn-color);
}

.track-row--error .track-row__mark {
  color: var(--p-status-error-color);
}

.track-row--warning .track-row__mark {
  color: var(--p-status-warn-color);
}

.track-row--info .track-row__mark {
  color: var(--p-status-info-color);
}

.track-row__lead {
  flex: 1 1 16rem;
  min-width: 0;
}

.track-row__buttons {
  display: flex;
  flex: none;
  gap: var(--rf-space-1);
  margin-inline-start: auto;
}
</style>
