<script setup lang="ts">
import { X } from '@lucide/vue'
import Button from 'primevue/button'
import ProgressBar from 'primevue/progressbar'
import vTooltip from 'primevue/tooltip'
import { nextTick, onBeforeUnmount, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ScanRun } from '@/stores/scans'

/**
 * A scan's start button; while it runs, a progress bar and a cancel button. It emits `leave`
 * when it goes away with the focus on it, so that the parent can place the focus.
 */
const props = defineProps<{
  run: ScanRun | undefined
  label: string
  /** The button's accessible name: which track it measures. */
  startLabel: string
  progressLabel: string
  cancelLabel: string
  help?: string
  disabled?: boolean
}>()

const emit = defineEmits<{ start: []; cancel: [run: ScanRun]; leave: [] }>()

const { t } = useI18n()
const root = useTemplateRef<HTMLElement>('root')

function holdsFocus(): boolean {
  const active = document.activeElement
  return active !== null && root.value?.contains(active) === true
}

// A pre-flush watcher still sees the button that is about to be replaced.
watch(
  () => props.run !== undefined,
  async (running) => {
    if (!holdsFocus()) return
    await nextTick()
    const next = running ? 'cancel-scan' : 'start-scan'
    root.value?.querySelector<HTMLElement>(`[data-action="${next}"]`)?.focus()
  },
)

onBeforeUnmount(() => {
  if (holdsFocus()) emit('leave')
})
</script>

<template>
  <span ref="root" class="scan-control" :data-state="run ? 'running' : 'idle'" @click.stop>
    <template v-if="run">
      <ProgressBar
        class="scan-control__bar"
        :mode="run.progress === null ? 'indeterminate' : 'determinate'"
        :value="run.progress === null ? undefined : Math.round(run.progress * 100)"
        :show-value="false"
        :pt="{ root: { 'aria-label': progressLabel } }"
      />
      <Button
        v-tooltip.top="t('media.scan.cancel')"
        class="scan-control__cancel"
        size="small"
        severity="secondary"
        text
        rounded
        data-action="cancel-scan"
        :aria-label="cancelLabel"
        @click="emit('cancel', run)"
      >
        <template #icon><X :size="14" aria-hidden="true" /></template>
      </Button>
    </template>
    <Button
      v-else
      v-tooltip.top="help"
      class="scan-control__start"
      size="small"
      severity="secondary"
      outlined
      data-action="start-scan"
      :label="label"
      :aria-label="startLabel"
      :disabled="disabled"
      @click="emit('start')"
    />
  </span>
</template>

<style scoped>
.scan-control {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
  vertical-align: middle;
}

.scan-control__bar {
  width: 5rem;
  height: 0.375rem;
}

.scan-control__start {
  padding-block: 0;
  font-size: var(--rf-font-size-xs);
}
</style>
