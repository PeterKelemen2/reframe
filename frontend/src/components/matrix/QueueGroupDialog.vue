<script setup lang="ts">
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import { useI18n } from 'vue-i18n'

import { useQueueGroup } from '@/composables/useQueueGroup'

/** *Add group to queue* with files that have errors: queue the others, open the matrix, or not. */
const { t } = useI18n()
const { question, answer } = useQueueGroup()
</script>

<template>
  <Dialog
    :visible="question !== null"
    modal
    :header="t('matrix.queue.dialog.title')"
    class="queue-group-dialog"
    :style="{ width: 'min(36rem, calc(100vw - 2rem))' }"
    :draggable="false"
    @update:visible="answer('cancel')"
  >
    <template v-if="question !== null">
      <p class="queue-group-dialog__text">
        {{ t('matrix.queue.dialog.text', question.failed.length) }}
      </p>
      <ul class="queue-group-dialog__files">
        <li v-for="file in question.failed" :key="file.label" :data-source="file.sourceId">
          <strong dir="ltr">{{ file.label }}</strong>
          <span>{{ file.message }}</span>
        </li>
      </ul>
    </template>
    <template #footer>
      <Button
        :label="t('matrix.queue.dialog.cancel')"
        severity="secondary"
        text
        data-role="cancel"
        @click="answer('cancel')"
      />
      <Button
        :label="t('matrix.queue.dialog.matrix')"
        severity="secondary"
        outlined
        data-role="matrix"
        @click="answer('matrix')"
      />
      <Button
        :label="t('matrix.queue.dialog.valid')"
        :disabled="question === null || question.valid === 0"
        autofocus
        data-role="valid"
        @click="answer('valid')"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.queue-group-dialog__text {
  margin: 0 0 var(--rf-space-3);
}

.queue-group-dialog__files {
  display: grid;
  gap: var(--rf-space-2);
  max-height: 50vh;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.queue-group-dialog__files li {
  display: grid;
  gap: var(--rf-space-1);
}

.queue-group-dialog__files span {
  color: var(--p-status-error-color);
  font-size: var(--rf-font-size-sm);
}
</style>
