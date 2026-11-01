<script setup lang="ts">
import { LoaderCircle } from '@lucide/vue'
import { useEventListener } from '@vueuse/core'
import Checkbox from 'primevue/checkbox'
import Dialog from 'primevue/dialog'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { bySeverity, SEVERITY_ICON, useSeverityLabel } from '@/components/base/severity'
import { useEditorStore } from '@/stores/editor'
import { useUiStore } from '@/stores/ui'

import QueueGroupDialog from './QueueGroupDialog.vue'
import ResolutionMatrix from './ResolutionMatrix.vue'

/** The edited group's resolution matrix, open while `ui.matrixOpen`. */
const { t } = useI18n()
const severityLabel = useSeverityLabel()
const editor = useEditorStore()
const ui = useUiStore()

const problemsOnly = ref(false)

const resolution = computed(() => (editor.target?.kind === 'group' ? editor.resolution : null))
const title = computed(() => {
  const name = resolution.value?.group?.name
  return name ? t('matrix.title', { name }) : t('matrix.titleNoName')
})
const batchIssues = computed(() => bySeverity(resolution.value?.issues ?? []))

function close(): void {
  ui.matrixOpen = false
}

// The popovers in the matrix live outside the dialog: Escape there closes only the popover.
function onKey(event: KeyboardEvent): void {
  if (event.key === 'Escape' && !event.defaultPrevented) close()
}

// A click on text in the dialog leaves the focus nowhere, so the key never reaches the dialog.
useEventListener(document, 'keydown', (event: KeyboardEvent) => {
  const lost = event.target === document.body || event.target === document.documentElement
  if (event.key !== 'Escape' || !lost || !ui.matrixOpen) return
  const top = [...document.querySelectorAll('[role="dialog"][aria-modal="true"]')].at(-1)
  if (top?.classList.contains('matrix-dialog')) close()
})
</script>

<template>
  <Dialog
    :visible="ui.matrixOpen"
    modal
    maximizable
    :header="title"
    class="matrix-dialog"
    :style="{
      width: 'min(96rem, calc(100vw - 2rem))',
      height: 'min(56rem, calc(100vh - 2rem))',
    }"
    :draggable="false"
    :close-on-escape="false"
    :pt="{ root: { onKeydown: onKey }, content: { class: 'matrix-dialog__content' } }"
    @update:visible="close"
  >
    <div class="matrix-dialog__bar">
      <span v-if="resolution" data-role="count">
        {{ t('matrix.files', (resolution.rows ?? []).length) }}
      </span>
      <span v-if="editor.resolving" class="matrix-dialog__resolving" role="status">
        <LoaderCircle class="matrix-dialog__spin" :size="14" aria-hidden="true" />
        {{ resolution ? t('matrix.resolving') : t('matrix.loading') }}
      </span>
      <label class="matrix-dialog__filter">
        <Checkbox v-model="problemsOnly" binary input-id="matrix-problems-only" />
        <span>{{ t('matrix.problemsOnly') }}</span>
      </label>
    </div>
    <section
      v-if="batchIssues.length > 0"
      class="matrix-dialog__issues"
      :aria-label="t('matrix.batchIssues')"
    >
      <p v-for="(issue, index) in batchIssues" :key="index" :data-severity="issue.severity">
        <component :is="SEVERITY_ICON[issue.severity]" :size="16" aria-hidden="true" />
        <span class="rf-sr-only">{{ severityLabel(issue.severity) }}: </span>
        {{ issue.message }}
      </p>
    </section>
    <ResolutionMatrix
      v-if="resolution"
      :resolution="resolution"
      :problems-only="problemsOnly"
      :focus="ui.matrixFocus"
    />
  </Dialog>
  <QueueGroupDialog />
</template>

<style scoped>
.matrix-dialog__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2) var(--rf-space-4);
  margin-bottom: var(--rf-space-2);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.matrix-dialog__resolving {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
}

.matrix-dialog__spin {
  animation: matrix-dialog-spin 1s linear infinite;
}

@keyframes matrix-dialog-spin {
  to {
    transform: rotate(360deg);
  }
}

.matrix-dialog__filter {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-2);
  margin-left: auto;
  color: var(--rf-color-text);
}

.matrix-dialog__issues {
  display: grid;
  gap: var(--rf-space-1);
  margin-bottom: var(--rf-space-2);
}

.matrix-dialog__issues p {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
  margin: 0;
}

.matrix-dialog__issues [data-severity='error'] svg {
  color: var(--p-status-error-color);
}

.matrix-dialog__issues [data-severity='warning'] svg {
  color: var(--p-status-warn-color);
}
</style>

<style>
.matrix-dialog__content {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
}
</style>
