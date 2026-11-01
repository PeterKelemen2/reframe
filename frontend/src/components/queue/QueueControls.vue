<script setup lang="ts">
import { Ban, Pause, Play, Square, StepForward } from '@lucide/vue'
import ConfirmDialog from 'primevue/confirmdialog'
import { useConfirm } from 'primevue/useconfirm'
import vTooltip from 'primevue/tooltip'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { StatusTone } from '@/components/base/types'
import StatusDot from '@/components/base/StatusDot.vue'
import FocusSafeButton from '@/components/shell/FocusSafeButton'
import { useQueueStore } from '@/stores/queue'

import { runState } from './format'

/** The run state in words and the global controls: start, stop, pause, resume, cancel all. */
const { t } = useI18n()
const queue = useQueueStore()
const confirm = useConfirm()
const CONFIRM_GROUP = 'queue-cancel-all'

const state = computed(() => runState(queue.processing, queue.only, queue.jobs))
const busy = ref(false)

function describe(mode: 'all' | 'only' | 'stopped', onlyCount: number, held: number): string {
  if (mode === 'only') return t('queue.run.only', { n: onlyCount })
  if (mode === 'stopped') {
    return held > 0 ? t('queue.run.stoppedWaiting', held) : t('queue.run.stopped')
  }
  const waiting = queue.counts.waiting
  return waiting > 0 ? t('queue.run.all', waiting) : t('queue.run.allIdle')
}

const stateText = computed(() =>
  describe(state.value.mode, state.value.onlyCount, state.value.held),
)
const stateTone = computed<StatusTone>(() => (state.value.mode === 'stopped' ? 'off' : 'busy'))

/** A Start with jobs to take, or one that widens another front end's run to every job. */
const canStart = computed(
  () => state.value.mode === 'only' || (state.value.mode === 'stopped' && queue.counts.waiting > 0),
)
const open = computed(() => queue.counts.waiting + queue.counts.running + queue.counts.paused)

async function run(action: () => Promise<unknown>): Promise<void> {
  busy.value = true
  try {
    await action()
  } catch (error) {
    // The API client has shown the problem as a toast.
    if (!(error instanceof ApiError)) throw error
  } finally {
    busy.value = false
  }
}

function cancelAll(): void {
  confirm.require({
    group: CONFIRM_GROUP,
    header: t('queue.cancelAll.title'),
    message: t('queue.cancelAll.message', open.value),
    acceptLabel: t('queue.cancelAll.accept'),
    rejectLabel: t('queue.cancelAll.reject'),
    acceptProps: { severity: 'danger' },
    rejectProps: { severity: 'secondary', outlined: true },
    defaultFocus: 'reject',
    accept: () => void run(() => queue.cancelAll()),
  })
}
</script>

<template>
  <div class="queue-controls">
    <p class="queue-controls__state" data-field="run-state" :data-mode="state.mode">
      <StatusDot :tone="stateTone" :label="stateText" show-label />
    </p>
    <div class="queue-controls__buttons" role="group" :aria-label="t('queue.controls.label')">
      <FocusSafeButton
        v-tooltip.bottom="state.mode === 'only' ? t('queue.controls.startAllHelp') : undefined"
        size="small"
        data-action="start"
        :label="state.mode === 'only' ? t('queue.controls.startAll') : t('queue.controls.start')"
        :disabled="!canStart || busy"
        @click="run(() => queue.start())"
      >
        <template #icon><Play :size="16" aria-hidden="true" /></template>
      </FocusSafeButton>
      <FocusSafeButton
        v-tooltip.bottom="t('queue.controls.stopHelp')"
        size="small"
        severity="secondary"
        data-action="stop"
        :label="t('queue.controls.stop')"
        :disabled="!queue.processing || busy"
        @click="run(() => queue.stop())"
      >
        <template #icon><Square :size="16" aria-hidden="true" /></template>
      </FocusSafeButton>
      <FocusSafeButton
        size="small"
        severity="secondary"
        outlined
        data-action="pause-all"
        :label="t('queue.controls.pauseAll')"
        :disabled="queue.counts.running === 0 || busy"
        @click="run(() => queue.pauseAll())"
      >
        <template #icon><Pause :size="16" aria-hidden="true" /></template>
      </FocusSafeButton>
      <FocusSafeButton
        size="small"
        severity="secondary"
        outlined
        data-action="resume-all"
        :label="t('queue.controls.resumeAll')"
        :disabled="queue.counts.paused === 0 || busy"
        @click="run(() => queue.resumeAll())"
      >
        <template #icon><StepForward :size="16" aria-hidden="true" /></template>
      </FocusSafeButton>
      <FocusSafeButton
        size="small"
        severity="danger"
        outlined
        data-action="cancel-all"
        :label="t('queue.controls.cancelAll')"
        :disabled="open === 0 || busy"
        @click="cancelAll"
      >
        <template #icon><Ban :size="16" aria-hidden="true" /></template>
      </FocusSafeButton>
    </div>
    <ConfirmDialog :group="CONFIRM_GROUP" />
  </div>
</template>

<style scoped>
.queue-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-3) var(--rf-space-4);
}

.queue-controls__state {
  margin: 0;
  font-size: var(--rf-font-size-sm);
}

.queue-controls__buttons {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
}
</style>
