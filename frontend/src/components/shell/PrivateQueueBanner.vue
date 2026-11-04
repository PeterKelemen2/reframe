<script setup lang="ts">
import { TriangleAlert } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import type { DesktopPrivateQueue } from '@/platform/types'

/** The desktop app's sidecar runs on a queue of its own: its jobs are lost when the app quits. */
defineProps<{ queue: DesktopPrivateQueue }>()

const { t } = useI18n()
</script>

<template>
  <section
    class="private-queue"
    data-component="private-queue-banner"
    :aria-label="t('desktop.privateQueue.label')"
  >
    <TriangleAlert class="private-queue__icon" :size="20" aria-hidden="true" />
    <div class="private-queue__text" role="status">
      <p class="private-queue__title">
        {{ t('desktop.privateQueue.title') }}
        <span data-field="reason">{{ t(`desktop.privateQueue.reason.${queue.reason}`) }}</span>
      </p>
      <p class="private-queue__detail" data-field="detail">{{ queue.detail }}</p>
    </div>
  </section>
</template>

<style scoped>
.private-queue {
  display: flex;
  flex: none;
  align-items: flex-start;
  gap: var(--rf-space-3);
  padding: var(--rf-space-2) var(--rf-space-4);
  border-bottom: 1px solid var(--p-status-warn-border-color);
  background: var(--p-status-warn-background);
  color: var(--p-status-warn-color);
}

.private-queue__icon {
  flex: none;
  margin-top: 0.1em;
}

.private-queue__text {
  min-width: 0;
}

.private-queue__title,
.private-queue__detail {
  margin: 0;
}

.private-queue__title {
  font-weight: var(--rf-font-weight-medium);
}

.private-queue__detail {
  font-size: var(--rf-font-size-sm);
  overflow-wrap: anywhere;
}
</style>
