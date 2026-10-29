<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import JobLog from '@/components/queue/JobLog.vue'
import PowerBanner from '@/components/queue/PowerBanner.vue'
import QueueControls from '@/components/queue/QueueControls.vue'
import QueueTable from '@/components/queue/QueueTable.vue'
import WhenDoneSelect from '@/components/queue/WhenDoneSelect.vue'
import { useSettingsStore } from '@/stores/settings'

const { t } = useI18n()
const settings = useSettingsStore()

const logJob = ref<string | null>(null)
let opener: HTMLElement | null = null

function openLog(jobId: string, from: HTMLElement): void {
  opener = from
  logJob.value = jobId
}

async function closeLog(): Promise<void> {
  logJob.value = null
  await nextTick()
  // The button can be gone (the job was removed): then the focus stays where the drawer left it.
  if (opener?.isConnected) opener.focus()
  opener = null
}
</script>

<template>
  <main class="queue-view" data-view="queue">
    <header class="queue-view__header">
      <h1 class="queue-view__title">{{ t('app.views.queue') }}</h1>
      <QueueControls />
      <!-- The value is a setting: until the settings are read it is not known. -->
      <WhenDoneSelect v-if="settings.loaded" class="queue-view__when-done" />
    </header>
    <PowerBanner />
    <div class="queue-view__body">
      <QueueTable @open-log="openLog" />
    </div>
    <JobLog :job-id="logJob" @close="closeLog" />
  </main>
</template>

<style scoped>
.queue-view {
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100vh;
}

.queue-view__header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-3) var(--rf-space-5);
  padding: var(--rf-space-4);
}

.queue-view__title {
  margin: 0;
  font-size: var(--rf-font-size-2xl);
}

.queue-view__when-done {
  margin-inline-start: auto;
}

.queue-view__body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0 var(--rf-space-4) var(--rf-space-4);
}
</style>
