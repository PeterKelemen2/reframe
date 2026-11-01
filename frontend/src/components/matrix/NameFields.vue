<script setup lang="ts">
import InputText from 'primevue/inputtext'
import { ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { NameResult, ValidationIssue } from '@/api/types'
import { useEditorStore } from '@/stores/editor'

import { type NameField, NAME_FIELDS } from './matrix'

/** One file's parsed-name fields; an edit is that file's correction, an empty field none. */
const props = defineProps<{
  sourceId: string
  label: string
  naming: NameResult
  /** The file's corrections (`field_overrides` of its job). */
  overrides: Record<string, string>
  issues: ValidationIssue[]
}>()

const { t } = useI18n()
const editor = useEditorStore()
const id = useId()

/** What is typed, until the next resolution shows the file's fields. */
const drafts = ref<Partial<Record<NameField, string>>>({})
/** Enter and then the blur commit one value once. */
const sent = new Map<NameField, string>()
watch(
  () => props.naming,
  () => {
    drafts.value = {}
    sent.clear()
  },
)

function fieldLabel(field: NameField): string {
  switch (field) {
    case 'name':
      return t('naming.field.name')
    case 'season':
      return t('naming.field.season')
    case 'episode':
      return t('naming.field.episode')
    case 'sub_title':
      return t('naming.field.sub_title')
    case 'year':
      return t('naming.field.year')
  }
}

function shown(field: NameField): string {
  const value = props.naming.fields?.[field]
  return value === null || value === undefined ? '' : String(value)
}

function commit(field: NameField): void {
  const value = drafts.value[field]?.trim()
  if (value === undefined || sent.get(field) === value) return
  sent.set(field, value)
  if (value === '') {
    if (field in props.overrides) editor.setNameField(props.sourceId, field, null)
  } else if (value !== shown(field)) {
    editor.setNameField(props.sourceId, field, value)
  }
}

function issuesOf(field: NameField): ValidationIssue[] {
  return props.issues.filter((issue) => issue.path === `output.naming.field_overrides.${field}`)
}
</script>

<template>
  <div class="name-fields">
    <p class="name-fields__title">{{ t('matrix.name.title', { label }) }}</p>
    <p class="name-fields__reason">{{ naming.reason }}</p>
    <p class="name-fields__hint">{{ t('matrix.name.hint') }}</p>
    <div v-for="(field, index) in NAME_FIELDS" :key="field" class="name-fields__field">
      <label :for="`${id}-${field}`">
        {{ fieldLabel(field) }}
        <span v-if="field in overrides" class="name-fields__corrected">
          {{ t('matrix.name.corrected') }}
        </span>
      </label>
      <InputText
        :id="`${id}-${field}`"
        :model-value="drafts[field] ?? shown(field)"
        :data-field="field"
        :invalid="issuesOf(field).length > 0"
        :autofocus="index === 0 || undefined"
        :inputmode="field === 'name' || field === 'sub_title' ? undefined : 'numeric'"
        size="small"
        @update:model-value="drafts[field] = $event ?? ''"
        @blur="commit(field)"
        @keydown.enter="commit(field)"
      />
      <small v-for="issue in issuesOf(field)" :key="issue.code" class="name-fields__issue">
        {{ issue.message }}
      </small>
    </div>
  </div>
</template>

<style scoped>
.name-fields {
  display: grid;
  gap: var(--rf-space-2);
  width: min(24rem, 80vw);
}

.name-fields p {
  margin: 0;
}

.name-fields__title {
  font-weight: var(--rf-font-weight-medium);
}

.name-fields__reason,
.name-fields__hint {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.name-fields__field {
  display: grid;
  gap: var(--rf-space-1);
}

.name-fields__corrected {
  margin-left: var(--rf-space-1);
  color: var(--rf-color-primary);
  font-size: var(--rf-font-size-xs);
}

.name-fields__issue {
  color: var(--p-status-error-color);
}
</style>
