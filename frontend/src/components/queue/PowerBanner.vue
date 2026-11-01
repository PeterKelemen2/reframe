<script setup lang="ts">
import { Power } from '@lucide/vue'
import { computed, nextTick, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import FocusSafeButton from '@/components/shell/FocusSafeButton'
import { focusLost } from '@/components/shell/focus'
import { useQueueStore } from '@/stores/queue'

import { powerActionName } from './activityLines'

/** The when-done countdown while it runs, with its Cancel. */
const { t } = useI18n()
const queue = useQueueStore()
const cancelling = ref(false)
const root = useTemplateRef<HTMLElement>('root')

const action = computed(() => (queue.power === null ? '' : powerActionName(queue.power.action, t)))
const executing = computed(() => queue.power?.phase === 'executing')

const cancellable = computed(() => queue.power !== null && !executing.value)

// Cancel goes away with the countdown: the focus it had goes to the current view's rail link.
let hadFocus = false
watch(
  cancellable,
  () => {
    hadFocus = root.value?.contains(document.activeElement) ?? false
  },
  { flush: 'pre' },
)
watch(cancellable, async (now) => {
  if (now || !hadFocus) return
  await nextTick()
  if (focusLost()) document.querySelector<HTMLElement>('.nav-rail [aria-current="page"]')?.focus()
})

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
    ref="root"
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
    <FocusSafeButton
      v-if="!executing"
      severity="warn"
      size="small"
      data-action="cancel-power"
      :label="t('queue.power.cancel')"
      :disabled="cancelling"
      @click="cancel"
    />
  </section>
</template>

<style scoped>
.power-banner {
  display: flex;
  flex: none;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2) var(--rf-space-3);
  padding: var(--rf-space-2) var(--rf-space-4);
  border-bottom: 1px solid var(--p-status-warn-border-color);
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
