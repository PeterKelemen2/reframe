<script setup lang="ts">
import { Clapperboard, Files, FilePenLine, LoaderCircle, TriangleAlert } from '@lucide/vue'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, ref, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { JobType } from '@/api/types'
import Card from '@/components/base/Card.vue'
import Field from '@/components/base/Field.vue'
import IssueList from '@/components/base/IssueList.vue'
import FocusSafeButton from '@/components/shell/FocusSafeButton'
import { focusLost } from '@/components/shell/focus'
import { fileName } from '@/components/shell/format'
import { useEditorStore } from '@/stores/editor'
import { useValidationStore } from '@/stores/validation'

import { inPlaceIssues, isMatroska } from './inPlace'
import { useJobSource } from './useJobSource'
import { useJobType } from './useJobType'

const ICONS = { encode: Clapperboard, remux: Files, metadata_edit: FilePenLine } as const

const { t } = useI18n()
const editor = useEditorStore()
const validation = useValidationStore()
const { source } = useJobSource()
const { answer, error, pending } = useJobType()

const editInPlace = computed(() => editor.job?.output?.edit_in_place === true)
const sourcePath = computed(() => editor.job?.source.path ?? '')
const blockers = computed(() => answer.value?.in_place_blockers ?? [])
const issues = computed(() => inPlaceIssues(validation.issues))
const invalid = computed(() => issues.value.some((issue) => issue.severity === 'error'))
/** The switch's state counts at once: an answer on its way may be about the job before it. */
const inPlaceNow = computed(() => editInPlace.value && answer.value?.job_type === 'metadata_edit')
const couldEditInPlace = computed(
  () => !editInPlace.value && answer.value !== null && blockers.value.length === 0,
)

function typeLabel(type: JobType): string {
  switch (type) {
    case 'encode':
      return t('summary.jobType.encode')
    case 'remux':
      return t('summary.jobType.remux')
    case 'metadata_edit':
      return t('summary.jobType.metadataEdit')
  }
  return type
}

function setEditInPlace(value: boolean): void {
  editor.set('/output/edit_in_place', value)
}

const drafting = ref(false)
const remuxHelpId = `${useId()}-remux-help`
/** *Remux only* keeps the switch's choice; only a Matroska source can be edited in place. */
const remuxInPlace = computed(
  () => editInPlace.value && source.value !== null && isMatroska(source.value),
)

async function remuxOnly(): Promise<void> {
  if (drafting.value) return
  drafting.value = true
  try {
    await editor.applyRemuxDraft({ editInPlace: remuxInPlace.value })
  } catch (failure) {
    // The API client has shown the problem as a toast.
    if (!(failure instanceof ApiError)) throw failure
  } finally {
    drafting.value = false
  }
}

const body = useTemplateRef<HTMLElement>('body')
/** The issue button that had the focus: it goes away with its issue once a fix is checked. */
let focusedIssue: HTMLElement | null = null

function onIssueFocus(event: FocusEvent): void {
  focusedIssue = event.target instanceof HTMLElement ? event.target : null
}

watch(
  issues,
  () => {
    if (focusedIssue === null || focusedIssue.isConnected) return
    focusedIssue = null
    if (focusLost()) {
      body.value?.querySelector<HTMLElement>('[data-field="edit-in-place"] input')?.focus()
    }
  },
  { flush: 'post' },
)
</script>

<template>
  <Card
    class="summary-card summary-job-type"
    :title="t('summary.jobType.title')"
    data-card="job-type"
  >
    <template v-if="pending && answer !== null" #actions>
      <span class="summary-card__note" data-state="updating">{{
        t('summary.jobType.updating')
      }}</span>
    </template>
    <div ref="body" class="summary-job-type__body">
      <p v-if="error !== null" class="summary-job-type__failed" data-state="failed">
        {{ t('summary.jobType.failed', { reason: error }) }}
      </p>
      <p v-else-if="answer === null" class="summary-card__note" data-state="checking">
        {{ t('summary.jobType.checking') }}
      </p>
      <div v-else class="summary-job-type__answer" :data-job-type="answer.job_type">
        <span
          class="summary-job-type__badge"
          :class="`is-${answer.job_type}`"
          data-field="job-type"
        >
          <component :is="ICONS[answer.job_type]" :size="16" aria-hidden="true" />
          {{ typeLabel(answer.job_type) }}
        </span>
        <p class="summary-job-type__reason" data-field="reason">{{ answer.reason }}</p>
      </div>

      <Field
        :label="t('summary.jobType.editInPlace')"
        :help="t('summary.jobType.editInPlaceHelp')"
        path="output.edit_in_place"
        :issues="[]"
      >
        <template #default="{ id }">
          <ToggleSwitch
            :input-id="id"
            :model-value="editInPlace"
            :invalid="invalid"
            data-field="edit-in-place"
            @update:model-value="setEditInPlace"
          />
        </template>
      </Field>

      <div v-if="inPlaceNow" class="summary-job-type__in-place" data-state="in-place">
        <TriangleAlert :size="16" aria-hidden="true" />
        <i18n-t keypath="summary.jobType.inPlace" tag="p">
          <template #path>
            <code dir="ltr">{{ sourcePath }}</code>
          </template>
        </i18n-t>
      </div>
      <p v-else-if="couldEditInPlace" class="summary-card__note" data-state="can-edit-in-place">
        {{ t('summary.jobType.canEditInPlace', { name: fileName(sourcePath) }) }}
      </p>

      <div v-if="blockers.length > 0" class="summary-job-type__blockers" data-state="blocked">
        <p class="summary-card__note">{{ t('summary.jobType.blocked') }}</p>
        <ul class="summary-card__notes">
          <li v-for="blocker in blockers" :key="blocker" data-field="blocker">{{ blocker }}</li>
        </ul>
      </div>

      <div v-if="issues.length > 0" @focusin="onIssueFocus">
        <IssueList :issues="issues" />
      </div>

      <div class="summary-job-type__remux">
        <FocusSafeButton
          size="small"
          severity="secondary"
          outlined
          :label="t('summary.jobType.remuxOnly')"
          :disabled="drafting || editor.job === null"
          :aria-busy="drafting || undefined"
          :aria-describedby="remuxHelpId"
          data-action="remux-only"
          @click="remuxOnly"
        >
          <template v-if="drafting" #icon>
            <LoaderCircle class="summary-job-type__spin" :size="16" aria-hidden="true" />
          </template>
        </FocusSafeButton>
        <p :id="remuxHelpId" class="summary-card__note">
          {{
            remuxInPlace
              ? t('summary.jobType.remuxOnlyInPlaceHelp')
              : t('summary.jobType.remuxOnlyHelp')
          }}
        </p>
      </div>
    </div>
  </Card>
</template>

<style scoped>
.summary-job-type__body {
  display: grid;
  gap: var(--rf-space-3);
}

.summary-job-type__answer {
  display: grid;
  gap: var(--rf-space-2);
  justify-items: start;
}

.summary-job-type__badge {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
  padding: 0 var(--rf-space-2);
  border: 1px solid var(--p-status-off-border-color);
  border-radius: var(--rf-radius-pill);
  background: var(--p-status-off-background);
  color: var(--p-status-off-color);
  font-weight: var(--rf-font-weight-bold);
  line-height: 1.75rem;
}

.summary-job-type__badge.is-remux {
  border-color: var(--p-status-info-border-color);
  background: var(--p-status-info-background);
  color: var(--p-status-info-color);
}

.summary-job-type__badge.is-metadata_edit {
  border-color: var(--p-status-ok-border-color);
  background: var(--p-status-ok-background);
  color: var(--p-status-ok-color);
}

.summary-job-type__reason,
.summary-job-type__failed {
  margin: 0;
}

.summary-job-type__failed {
  color: var(--p-status-error-color);
}

.summary-job-type__in-place {
  display: flex;
  align-items: flex-start;
  gap: var(--rf-space-2);
  padding: var(--rf-space-2);
  border: 1px solid var(--p-status-warn-border-color);
  border-radius: var(--rf-radius-md);
  background: var(--p-status-warn-background);
  color: var(--p-status-warn-color);
  font-size: var(--rf-font-size-sm);
  overflow-wrap: anywhere;
}

.summary-job-type__in-place svg {
  flex: none;
  margin-top: 0.15rem;
}

.summary-job-type__in-place p {
  margin: 0;
}

.summary-job-type__blockers {
  display: grid;
  gap: var(--rf-space-1);
}

.summary-job-type__remux {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
}

.summary-job-type__remux .summary-card__note {
  flex: 1 1 14rem;
}

.summary-job-type__spin {
  animation: summary-job-type-spin 1s linear infinite;
}

@keyframes summary-job-type-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
