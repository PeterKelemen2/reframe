<script setup lang="ts">
import Select from 'primevue/select'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { WhenDone } from '@/api/types'
import Field from '@/components/base/Field.vue'
import { useQueueStore } from '@/stores/queue'
import { useSystemStore } from '@/stores/system'

const { t } = useI18n()
const queue = useQueueStore()
const system = useSystemStore()

const web = computed(() => system.info?.mode !== 'desktop')
const saving = ref(false)

const options = computed(() => [
  { value: 'nothing', label: t('queue.whenDone.nothing'), disabled: false },
  { value: 'notify', label: t('queue.whenDone.notify'), disabled: false },
  // A server for browsers keeps running: quitting is the desktop app's.
  {
    value: 'quit',
    label: web.value ? t('queue.whenDone.quitDesktopOnly') : t('queue.whenDone.quit'),
    disabled: web.value,
  },
  { value: 'sleep', label: t('queue.whenDone.sleep'), disabled: false },
  { value: 'shutdown', label: t('queue.whenDone.shutdown'), disabled: false },
])

/**
 * What the select shows: the choice on its way, then the queue's. PrimeVue's select keeps what
 * was chosen until its value changes, so a refused choice must change it back.
 */
const shown = ref<WhenDone>(queue.whenDone)
watch(
  () => queue.whenDone,
  (value) => (shown.value = value),
)

async function choose(value: WhenDone): Promise<void> {
  if (value === queue.whenDone) return
  shown.value = value
  saving.value = true
  try {
    await queue.setWhenDone(value)
  } catch (error) {
    // Shown as a toast.
    if (!(error instanceof ApiError)) throw error
  } finally {
    saving.value = false
    shown.value = queue.whenDone
  }
}
</script>

<template>
  <Field
    class="when-done"
    :label="t('queue.whenDone.label')"
    :help="web ? t('queue.whenDone.helpWeb') : t('queue.whenDone.helpDesktop')"
  >
    <template #default="{ id, labelId }">
      <!-- Named by its label: without it, a combobox is named by its value. -->
      <Select
        :input-id="id"
        :ariaLabelledby="labelId"
        :model-value="shown"
        :options="options"
        option-label="label"
        option-value="value"
        option-disabled="disabled"
        :loading="saving"
        data-field="when-done"
        @update:model-value="choose"
      />
    </template>
  </Field>
</template>
