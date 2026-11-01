<script setup lang="ts">
import InputText from 'primevue/inputtext'
import { computed, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { OutputChapter } from '@/api/types'
import { useReveal } from '@/composables/useReveal'

import { formatTime, nameSlot } from './chapters'

/** One chapter of the output; its name is edited in place. */
const props = defineProps<{
  chapter: OutputChapter
  /** What the name field shows. */
  name: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  rename: [name: string]
  /** The field lost the focus: the edit is over. */
  done: []
}>()

const { t } = useI18n()
const root = useTemplateRef<HTMLElement>('root')

const path = computed(() => `chapters.names[${nameSlot(props.chapter)}]`)
useReveal(path, root)

function leave(event: KeyboardEvent): void {
  ;(event.target as HTMLElement).blur()
}
</script>

<template>
  <tr ref="root" class="chapter-row" :data-chapter="chapter.number" :data-path="path">
    <td class="chapter-row__number">{{ chapter.number }}</td>
    <td class="chapter-row__time">{{ formatTime(chapter.start) }}</td>
    <td class="chapter-row__time">{{ formatTime(chapter.end - chapter.start) }}</td>
    <td class="chapter-row__name">
      <InputText
        :model-value="name"
        :aria-label="t('chapters.table.nameLabel', { n: chapter.number })"
        :disabled="disabled"
        size="small"
        fluid
        spellcheck="false"
        data-field="name"
        @update:model-value="emit('rename', $event ?? '')"
        @keydown.enter.prevent="leave"
        @blur="emit('done')"
      />
      <span
        v-if="chapter.source_name && chapter.source_name !== name"
        class="chapter-row__source"
        data-field="source-name"
      >
        {{ t('chapters.table.sourceName', { name: chapter.source_name }) }}
      </span>
    </td>
  </tr>
</template>

<style scoped>
td {
  padding: var(--rf-space-1) var(--rf-space-2);
  vertical-align: middle;
}

.chapter-row + .chapter-row td {
  border-top: 1px solid var(--rf-color-border);
}

.chapter-row__number {
  width: 3rem;
  color: var(--rf-color-text-muted);
  font-variant-numeric: tabular-nums;
  text-align: end;
}

.chapter-row__time {
  width: 8rem;
  font-family: var(--rf-font-mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.chapter-row__name {
  min-width: 14rem;
}

.chapter-row__source {
  display: block;
  margin-top: 2px;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}
</style>
