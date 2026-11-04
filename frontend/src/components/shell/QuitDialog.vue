<script setup lang="ts">
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'

import { focusLost } from '@/components/shell/focus'
import type { QuitAnswer, QuitQuestion } from '@/composables/useQuitFlow'

/** The desktop app's question when its window closes while jobs run. */
const props = defineProps<{ question: QuitQuestion | null }>()
const emit = defineEmits<{ answer: [choice: QuitAnswer] }>()

const { t } = useI18n()
const textId = useId()

// PrimeVue gives the focus back to where it was; with none there, it would be on no control.
function afterHide(): void {
  if (focusLost()) document.querySelector<HTMLElement>('.nav-rail [aria-current="page"]')?.focus()
}

const visible = computed({
  get: () => props.question !== null,
  // Escape and the close button mean Cancel.
  set: (shown) => {
    if (!shown) emit('answer', 'cancel')
  },
})
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    class="quit-dialog"
    :header="t('desktop.quit.title')"
    :style="{ width: 'min(34rem, calc(100vw - 2rem))' }"
    data-dialog="quit"
    :pt="{ root: { 'aria-describedby': textId } }"
    @after-hide="afterHide"
  >
    <p :id="textId" class="quit-dialog__text">
      {{ t('desktop.quit.text', question?.active ?? 0) }}
    </p>
    <template #footer>
      <Button
        severity="secondary"
        text
        :label="t('desktop.quit.cancel')"
        data-action="quit-cancel"
        @click="emit('answer', 'cancel')"
      />
      <Button
        v-if="question?.tray"
        severity="secondary"
        :label="t('desktop.quit.tray')"
        data-action="quit-tray"
        @click="emit('answer', 'tray')"
      />
      <Button
        severity="danger"
        :label="t('desktop.quit.stop')"
        data-action="quit-stop"
        @click="emit('answer', 'stop')"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.quit-dialog__text {
  margin: 0;
}
</style>
