<script setup lang="ts">
import vTooltip from 'primevue/tooltip'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { TrackRoleInfo } from '@/api/types'

import type { TrackKind } from './types'

/** Ink when a disposition flag sets the role, muted for a title, dashed for a guess; the tooltip names the evidence. */
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
/* Quiet beside the track's language and codec: a role describes the track, it is not a problem. */
.rf-role-badge {
  display: inline-flex;
  align-items: center;
  padding: 0 var(--rf-space-2);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-sm);
  font-size: var(--rf-font-size-xs);
  font-weight: var(--rf-font-weight-medium);
  line-height: 1.25rem;
  white-space: nowrap;
  cursor: default;
}

/* Set by a flag: the strongest evidence reads in ink. */
.rf-role-badge--solid {
  color: var(--rf-color-text);
}

.rf-role-badge--outlined {
  color: var(--rf-color-text-muted);
}

/* A guess is weaker evidence than a title: dashed. */
.rf-role-badge[data-evidence='heuristic'] {
  border-style: dashed;
}
</style>
