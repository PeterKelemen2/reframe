<script setup lang="ts">
// The group's chapter-name policy: each file keeps its source's names, or gets numbered ones.
import SelectButton from 'primevue/selectbutton'
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'

import type { JobTemplate } from '@/api/types'
import { useEditorStore } from '@/stores/editor'

type Policy = JobTemplate['chapter_name_policy']

const { t } = useI18n()
const editor = useEditorStore()
const id = useId()

const policy = computed<Policy>(() => editor.currentTemplate?.chapter_name_policy ?? 'source')

const options = computed(() => [
  { label: t('group.chapterNames.source'), value: 'source' },
  { label: t('group.chapterNames.generated'), value: 'generated' },
])

async function choose(value: Policy | null): Promise<void> {
  if (value === null || value === policy.value) return
  await editor.patchTemplate([{ op: 'add', path: '/chapter_name_policy', value }])
}
</script>

<template>
  <span class="group-chapter-names">
    <span :id="`${id}-label`" class="group-chapter-names__label">{{
      t('group.chapterNames.label')
    }}</span>
    <SelectButton
      :model-value="policy"
      :options="options"
      option-label="label"
      option-value="value"
      :allow-empty="false"
      :ariaLabelledby="`${id}-label`"
      size="small"
      data-field="chapter-names"
      @update:model-value="choose"
    />
  </span>
</template>

<style scoped>
.group-chapter-names {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
}

.group-chapter-names__label {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}
</style>
