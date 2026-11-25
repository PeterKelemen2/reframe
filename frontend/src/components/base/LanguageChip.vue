<script setup lang="ts">
import vTooltip from 'primevue/tooltip'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { useSystemStore } from '@/stores/system'

import { useLanguageColor } from './languageColor'
import { findLanguage, isUndetermined } from './languages'

/**
 * A language by its tag (BCP 47 or ISO 639-2): its colour mark and name, the code in the tooltip;
 * `und` or none: undetermined. `pale` draws the mark of a commentary or secondary track.
 */
const props = defineProps<{ tag: string | null | undefined; pale?: boolean }>()

const { t } = useI18n()
const system = useSystemStore()

const colorOf = useLanguageColor()
const undetermined = computed(() => isUndetermined(props.tag))
const color = computed(() => colorOf(props.tag))
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
    :style="{ '--rf-language-color': color }"
  >
    <span class="rf-language-chip__mark" :class="{ 'is-pale': pale }" aria-hidden="true" />{{
      text
    }}
  </span>
</template>

<style scoped>
.rf-language-chip {
  display: inline-flex;
  gap: var(--rf-space-2);
  align-items: center;
  color: var(--rf-color-text);
  font-size: var(--rf-font-size-sm);
  line-height: 1.5rem;
  white-space: nowrap;
}

/* The language's lane colour, as the programme strip draws it. */
.rf-language-chip__mark {
  flex: none;
  width: 0.25rem;
  height: 1rem;
  border-radius: 1px;
  background: var(--rf-language-color);
}

.rf-language-chip__mark.is-pale {
  opacity: var(--rf-lang-pale);
}

.rf-language-chip--undetermined {
  color: var(--rf-color-text-muted);
  font-style: italic;
}
</style>
