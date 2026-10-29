<script setup lang="ts">
import vTooltip from 'primevue/tooltip'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { TrackRoleInfo } from '@/api/types'

import type { TrackKind } from './types'

/** Solid when a disposition flag sets the role, outlined for a title or heuristic; the tooltip names the evidence. */
const props = defineProps<{
  role: TrackRoleInfo
  /** Picks the name of `description`: audio description, or descriptions on subtitles. */
  kind?: TrackKind
}>()

const { t } = useI18n()

const name = computed(() => {
  switch (props.role.role) {
    case 'main':
      return t('base.role.main')
    case 'commentary':
      return t('base.role.commentary')
    case 'description':
      return props.kind === 'subtitle' ? t('base.role.descriptionText') : t('base.role.description')
    case 'music':
      return t('base.role.music')
    case 'sdh':
      return t('base.role.sdh')
    case 'forced':
      return t('base.role.forced')
    case 'signs':
      return t('base.role.signs')
  }
  return props.role.role
})

const evidence = computed(() => {
  switch (props.role.evidence) {
    case 'flag':
      return t('base.role.evidence.flag')
    case 'title':
      return t('base.role.evidence.title')
    case 'heuristic':
      return t('base.role.evidence.heuristic')
  }
  return props.role.evidence
})

const tooltip = computed(() =>
  props.role.detail ? `${evidence.value}\n${props.role.detail}` : evidence.value,
)
</script>

<template>
  <span
    v-tooltip.top="tooltip"
    class="rf-role-badge"
    :class="`rf-role-badge--${role.evidence === 'flag' ? 'solid' : 'outlined'}`"
    :data-evidence="role.evidence"
  >
    {{ name }}<span class="rf-sr-only">{{ t('base.role.evidenceSr', { evidence }) }}</span>
  </span>
</template>

<style scoped>
.rf-role-badge {
  display: inline-flex;
  align-items: center;
  padding: 0 var(--rf-space-2);
  border: 1px solid var(--rf-color-primary);
  border-radius: var(--rf-radius-pill);
  font-size: var(--rf-font-size-xs);
  font-weight: var(--rf-font-weight-medium);
  line-height: 1.5rem;
  white-space: nowrap;
  cursor: default;
}

.rf-role-badge--solid {
  background: var(--rf-color-primary);
  color: var(--rf-color-on-primary);
}

.rf-role-badge--outlined {
  background: transparent;
  color: var(--rf-color-primary);
}

/* A guess is weaker evidence than a title: dashed. */
.rf-role-badge[data-evidence='heuristic'] {
  border-style: dashed;
}
</style>
