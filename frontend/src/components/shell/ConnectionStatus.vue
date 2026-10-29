<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import StatusDot from '@/components/base/StatusDot.vue'
import type { StatusTone } from '@/components/base/types'
import { useSystemStore } from '@/stores/system'

/**
 * `compact`: a short label under the dot (the navigation rail). Only the rail's copy is a live
 * region: it is on every screen, and two would announce each change twice.
 */
defineProps<{ compact?: boolean }>()

const { t } = useI18n()
const system = useSystemStore()

const state = computed<{ tone: StatusTone; label: string; short: string | null }>(() => {
  switch (system.connection) {
    case 'open':
      return { tone: 'ok', label: t('shell.connection.open'), short: null }
    case 'connecting':
      return {
        tone: 'busy',
        label: t('shell.connection.connecting'),
        short: t('shell.connection.short.connecting'),
      }
    case 'reconnecting':
      return {
        tone: 'warn',
        label: t('shell.connection.reconnecting'),
        short: t('shell.connection.short.reconnecting'),
      }
    case 'unauthorized':
      return {
        tone: 'error',
        label: t('shell.connection.unauthorized'),
        short: t('shell.connection.short.unauthorized'),
      }
    default:
      return {
        tone: 'off',
        label: t('shell.connection.closed'),
        short: t('shell.connection.short.closed'),
      }
  }
})
</script>

<template>
  <span
    class="connection-status"
    :class="{ 'connection-status--compact': compact }"
    :role="compact ? 'status' : undefined"
    :data-connection="system.connection"
  >
    <StatusDot :tone="state.tone" :label="state.label" />
    <span v-if="state.short !== null" class="connection-status__label" aria-hidden="true">
      {{ compact ? state.short : state.label }}
    </span>
  </span>
</template>

<style scoped>
.connection-status {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
  font-size: var(--rf-font-size-sm);
}

.connection-status--compact {
  flex-direction: column;
  font-size: var(--rf-font-size-xs);
  text-align: center;
}

.connection-status__label {
  color: var(--rf-color-text-muted);
}
</style>
