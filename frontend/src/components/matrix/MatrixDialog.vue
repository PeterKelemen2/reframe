<script setup lang="ts">
import { CircleX, LoaderCircle } from '@lucide/vue'
import { useEventListener } from '@vueuse/core'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import Dialog from 'primevue/dialog'
import { computed, nextTick, ref, watch } from 'vue'
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
const maximized = ref(false)

const title = computed(() => {
  const name = editor.resolution?.group?.name
  return name ? t('matrix.title', { name }) : t('matrix.titleNoName')
})
const batchIssues = computed(() => bySeverity(editor.resolution?.issues ?? []))
const status = computed(() => {
  if (!editor.resolving) return ''
  return editor.resolution ? t('matrix.resolving') : t('matrix.loading')
})

// The matrix of an older template is only looked at: a pick there would name another rule.
const outdated = computed(() => editor.matrixError !== null && editor.resolution !== null)
watch(outdated, async (now) => {
  await nextTick()
  const active = document.activeElement
  if (now && (active === document.body || active?.closest('.matrix') != null))
    document.querySelector<HTMLElement>('.matrix-dialog [data-role="retry"]')?.focus()
})

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
    :maximize-button-props="{
      severity: 'secondary',
      text: true,
      rounded: true,
      'aria-label': maximized ? t('matrix.restore') : t('matrix.maximize'),
    }"
    :pt="{ root: { onKeydown: onKey }, content: { class: 'matrix-dialog__content' } }"
    @update:visible="close"
    @maximize="maximized = true"
    @unmaximize="maximized = false"
  >
    <div class="matrix-dialog__bar">
      <span v-if="editor.resolution" data-role="count">
        {{ t('matrix.files', (editor.resolution.rows ?? []).length) }}
      </span>
      <span class="matrix-dialog__resolving" role="status">
        <LoaderCircle v-if="status" class="matrix-dialog__spin" :size="14" aria-hidden="true" />{{
          status
        }}
      </span>
      <label class="matrix-dialog__filter">
        <Checkbox
          v-model="problemsOnly"
          binary
          input-id="matrix-problems-only"
          :pt="{ input: { autofocus: editor.resolution === null || undefined } }"
        />
        <span>{{ t('matrix.problemsOnly') }}</span>
      </label>
    </div>
    <div v-if="editor.matrixError !== null" class="matrix-dialog__failure">
      <CircleX :size="16" aria-hidden="true" />
      <p role="alert">
        {{ t('matrix.failed', { reason: editor.matrixError }) }}
        {{ editor.resolution ? t('matrix.outdated') : t('matrix.none') }}
      </p>
      <Button
        :label="t('matrix.retry')"
        size="small"
        severity="secondary"
        outlined
        :loading="editor.resolving"
        data-role="retry"
        @click="editor.retryMatrix()"
      />
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
    <div
      v-if="editor.resolution"
      class="matrix-dialog__matrix"
      :class="{ 'matrix-dialog__matrix--outdated': outdated }"
      :inert="outdated || undefined"
      :data-state="outdated ? 'outdated' : undefined"
    >
      <ResolutionMatrix
        :resolution="editor.resolution"
        :problems-only="problemsOnly"
        :focus="ui.matrixFocus"
      />
    </div>
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

.matrix-dialog__failure {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
  margin-bottom: var(--rf-space-2);
  color: var(--p-status-error-color);
}

.matrix-dialog__failure p {
  flex: 1 1 20rem;
  margin: 0;
}

.matrix-dialog__matrix {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
}

.matrix-dialog__matrix--outdated {
  opacity: 0.5;
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
