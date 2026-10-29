<script setup lang="ts">
import { Power } from '@lucide/vue'
import Button from 'primevue/button'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import { useQueueStore } from '@/stores/queue'

import { powerActionName } from './activityLines'

/** The when-done countdown while it runs, with its Cancel. */
const { t } = useI18n()
const queue = useQueueStore()
const cancelling = ref(false)

const action = computed(() => (queue.power === null ? '' : powerActionName(queue.power.action, t)))
const executing = computed(() => queue.power?.phase === 'executing')

async function cancel(): Promise<void> {
  cancelling.value = true
  try {
    await queue.cancelPower()
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
  } finally {
    cancelling.value = false
  }
}
</script>

<template>
  <section
    v-if="queue.power !== null"
    class="power-banner"
    data-component="power-banner"
    :aria-label="t('queue.power.label')"
  >
    <Power class="power-banner__icon" :size="20" aria-hidden="true" />
    <p class="power-banner__text" role="alert">
      {{
        executing ? t('queue.power.executing', { action }) : t('queue.power.countdown', { action })
      }}
    </p>
    <span v-if="!executing" class="power-banner__seconds" data-field="seconds">
      {{ t('queue.power.seconds', { n: queue.power.seconds_left }) }}
    </span>
    <Button
      v-if="!executing"
      severity="warn"
      size="small"
      data-action="cancel-power"
      :label="t('queue.power.cancel')"
      :loading="cancelling"
      @click="cancel"
    />
  </section>
</template>

<style scoped>
.power-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-3);
  margin: 0 var(--rf-space-4) var(--rf-space-3);
  padding: var(--rf-space-3) var(--rf-space-4);
  border: 1px solid var(--p-status-warn-border-color);
  border-radius: var(--rf-radius-md);
  background: var(--p-status-warn-background);
  color: var(--p-status-warn-color);
}

.power-banner__text {
  flex: 1 1 16rem;
  margin: 0;
  font-weight: var(--rf-font-weight-medium);
}

.power-banner__seconds {
  font-size: var(--rf-font-size-lg);
  font-variant-numeric: tabular-nums;
  font-weight: var(--rf-font-weight-bold);
}
</style>
