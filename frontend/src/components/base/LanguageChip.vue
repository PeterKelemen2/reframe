<script setup lang="ts">
import vTooltip from 'primevue/tooltip'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { useSystemStore } from '@/stores/system'

import { findLanguage, isUndetermined } from './languages'

/** A language by its tag (BCP 47 or ISO 639-2): the name, the code in the tooltip; `und` or none: undetermined. */
const props = defineProps<{ tag: string | null | undefined }>()

const { t } = useI18n()
const system = useSystemStore()

const undetermined = computed(() => isUndetermined(props.tag))
const language = computed(() => findLanguage(system.languages, props.tag))

const text = computed(() => {
  if (undetermined.value) return t('base.language.undetermined')
  return language.value?.english_name ?? props.tag ?? ''
})

const tooltip = computed(() => {
  const lines: string[] = []
  if (props.tag) lines.push(props.tag)
  const found = language.value
  if (found && found.native_name !== found.english_name) lines.push(found.native_name)
  return lines.length > 0 ? lines.join('\n') : undefined
})
</script>

<template>
  <span
    v-tooltip.top="tooltip"
    class="rf-language-chip"
    :class="{ 'rf-language-chip--undetermined': undetermined }"
    :data-tag="tag ?? undefined"
  >
    {{ text }}
  </span>
</template>

<style scoped>
.rf-language-chip {
  display: inline-flex;
  align-items: center;
  padding: 0 var(--rf-space-2);
  border-radius: var(--rf-radius-pill);
  background: var(--p-status-off-background);
  color: var(--rf-color-text);
  font-size: var(--rf-font-size-sm);
  line-height: 1.5rem;
  white-space: nowrap;
}

.rf-language-chip--undetermined {
  color: var(--rf-color-text-muted);
  font-style: italic;
}
</style>
