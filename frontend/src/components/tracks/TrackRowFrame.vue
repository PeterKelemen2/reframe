<script setup lang="ts">
import { ArrowDown, ArrowUp, Trash2 } from '@lucide/vue'
import Button from 'primevue/button'
import vTooltip from 'primevue/tooltip'
import { computed, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ValidationIssue } from '@/api/types'
import IssueList from '@/components/base/IssueList.vue'
import { SEVERITY_ICON, useSeverityLabel } from '@/components/base/severity'
import { useReveal } from '@/composables/useReveal'
import { useEditorStore } from '@/stores/editor'
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
const editor = useEditorStore()
const id = useId()
const root = useTemplateRef<HTMLElement>('root')
/** Scope `file` of a group: the template's rules fix the track list. */
const fixedList = computed(() => editor.target?.kind === 'group' && editor.target.scope === 'file')
const describedBy = computed(() => (fixedList.value ? `${id}-fixed` : undefined))

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
      <span class="track-row__badge">
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
      </span>
      <div class="track-row__lead">
        <slot name="header" />
      </div>
      <!-- Not every browser sends pointer events to a disabled button: the wrapper has the tooltip. -->
      <div
        v-tooltip.top="fixedList ? t('tracks.output.rowFileScope') : undefined"
        class="track-row__buttons"
      >
        <span v-if="fixedList" :id="`${id}-fixed`" hidden>{{
          t('tracks.output.rowFileScope')
        }}</span>
        <Button
          text
          rounded
          size="small"
          severity="secondary"
          data-move="up"
          :disabled="index === 0 || fixedList"
          :aria-describedby="describedBy"
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
          :disabled="index >= count - 1 || fixedList"
          :aria-describedby="describedBy"
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
          :disabled="fixedList"
          :aria-describedby="describedBy"
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
  align-items: flex-start;
  gap: var(--rf-space-2);
}

/* The header's field is a label over a control: the number and the buttons stand beside the
   control, centred on it. */
.track-row__badge,
.track-row__buttons {
  display: flex;
  align-items: center;
  height: var(--rf-control-height);
  margin-top: calc(var(--rf-field-label-height) + var(--rf-space-1));
}

.track-row__badge {
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
  flex: none;
  gap: var(--rf-space-1);
  margin-inline-start: auto;
}
</style>
