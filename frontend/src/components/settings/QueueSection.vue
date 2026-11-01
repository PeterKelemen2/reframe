<script setup lang="ts">
import InputNumber from 'primevue/inputnumber'
import Select from 'primevue/select'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { ValidationIssue, WhenDone } from '@/api/types'
import Field from '@/components/base/Field.vue'
import Section from '@/components/base/Section.vue'
import { useQueueStore } from '@/stores/queue'
import { useSystemStore } from '@/stores/system'

import { refusalIssues, useSetting, useSettingsLocked } from './useSetting'

const { t } = useI18n()
const system = useSystemStore()
const queue = useQueueStore()
const locked = useSettingsLocked()

const parallelJobs = useSetting<number>('/queue/parallel_jobs')
const sleepInhibit = useSetting<boolean>('/queue/sleep_inhibit')
const notifications = useSetting<boolean>('/queue/notifications')

const web = computed(() => system.info?.mode !== 'desktop')

const whenDoneOptions = computed(() => [
  { value: 'nothing', label: t('settings.queue.whenDone.nothing'), disabled: false },
  { value: 'notify', label: t('settings.queue.whenDone.notify'), disabled: false },
  // Quitting is the desktop app's: a server for browsers keeps running.
  {
    value: 'quit',
    label: web.value
      ? t('settings.queue.whenDone.quitDesktopOnly')
      : t('settings.queue.whenDone.quit'),
    disabled: web.value,
  },
  { value: 'sleep', label: t('settings.queue.whenDone.sleep'), disabled: false },
  { value: 'shutdown', label: t('settings.queue.whenDone.shutdown'), disabled: false },
])
const whenDoneIssues = shallowRef<ValidationIssue[]>([])
const settingWhenDone = ref(false)

/** Through the queue, which also cancels a countdown for another action. */
async function setWhenDone(value: WhenDone): Promise<void> {
  settingWhenDone.value = true
  try {
    await queue.setWhenDone(value)
    whenDoneIssues.value = []
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
    whenDoneIssues.value = refusalIssues(error, 'queue.when_done', t)
  } finally {
    settingWhenDone.value = false
  }
}

function saveParallel(value: number | null): void {
  // An emptied field keeps the saved number.
  if (value !== null && value !== parallelJobs.value.value) void parallelJobs.save(value)
}
</script>

<template>
  <Section :title="t('settings.queue.title')">
    <div class="queue-section__fields">
      <Field
        :label="t('settings.queue.parallelJobs')"
        :help="t('settings.queue.parallelHelp')"
        :issues="parallelJobs.issues.value"
      >
        <template #default="{ id, invalid }">
          <InputNumber
            :input-id="id"
            :model-value="parallelJobs.value.value ?? null"
            :min="1"
            :use-grouping="false"
            :input-style="{ width: '6rem' }"
            show-buttons
            :invalid="invalid"
            :disabled="locked"
            data-field="parallel-jobs"
            @update:model-value="saveParallel"
          />
        </template>
      </Field>
      <Field
        :label="t('settings.queue.whenDoneLabel')"
        :help="web ? t('settings.queue.whenDoneHelpWeb') : t('settings.queue.whenDoneHelpDesktop')"
        :issues="whenDoneIssues"
      >
        <template #default="{ id, labelId, invalid }">
          <Select
            :label-id="id"
            :ariaLabelledby="labelId"
            :model-value="queue.whenDone"
            :options="whenDoneOptions"
            option-label="label"
            option-value="value"
            option-disabled="disabled"
            :invalid="invalid"
            :loading="settingWhenDone"
            :disabled="locked"
            data-field="when-done"
            @update:model-value="setWhenDone"
          />
        </template>
      </Field>
      <Field
        :label="t('settings.queue.sleepInhibit')"
        :help="t('settings.queue.sleepInhibitHelp')"
        :issues="sleepInhibit.issues.value"
      >
        <template #default="{ id }">
          <ToggleSwitch
            :input-id="id"
            :model-value="sleepInhibit.value.value ?? true"
            :disabled="locked"
            data-field="sleep-inhibit"
            @update:model-value="sleepInhibit.save($event)"
          />
        </template>
      </Field>
      <Field
        :label="t('settings.queue.notifications')"
        :help="t('settings.queue.notificationsHelp')"
        :issues="notifications.issues.value"
      >
        <template #default="{ id }">
          <ToggleSwitch
            :input-id="id"
            :model-value="notifications.value.value ?? true"
            :disabled="locked"
            data-field="notifications"
            @update:model-value="notifications.save($event)"
          />
        </template>
      </Field>
    </div>
  </Section>
</template>

<style scoped>
.queue-section__fields {
  display: grid;
  gap: var(--rf-space-3);
}
</style>
