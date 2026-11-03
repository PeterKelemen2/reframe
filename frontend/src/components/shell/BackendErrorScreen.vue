<script setup lang="ts">
import { ServerCrash } from '@lucide/vue'
import Button from 'primevue/button'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { DesktopBackendError } from '@/platform/types'

/** The desktop app's server did not start (or stopped for good); Retry runs the start again. */
const props = defineProps<{ error: DesktopBackendError; retry: () => Promise<void> }>()

const { t } = useI18n()
const busy = ref(false)

// The shell's next `backend-state` replaces this screen; the button only waits for the request.
async function retryNow(): Promise<void> {
  busy.value = true
  try {
    await props.retry()
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="backend-error" data-phase="failed">
    <div class="backend-error__box" role="alert">
      <ServerCrash class="backend-error__icon" :size="40" aria-hidden="true" />
      <h1 class="backend-error__title">{{ t('desktop.backend.title') }}</h1>
      <p class="backend-error__message" data-field="message">{{ error.message }}</p>
      <template v-if="error.log !== null">
        <p class="backend-error__text">{{ t('desktop.backend.log') }}</p>
        <code class="backend-error__log" data-field="log">{{ error.log }}</code>
      </template>
      <Button
        :label="t('desktop.backend.retry')"
        :loading="busy"
        data-action="retry-backend"
        @click="retryNow"
      />
    </div>
  </main>
</template>

<style scoped>
.backend-error {
  display: grid;
  min-height: 100vh;
  place-items: center;
  padding: var(--rf-space-4);
}

.backend-error__box {
  display: grid;
  justify-items: center;
  gap: var(--rf-space-3);
  max-width: 36rem;
  text-align: center;
}

.backend-error__icon {
  color: var(--p-status-error-color);
}

.backend-error__title {
  margin: 0;
  font-size: var(--rf-font-size-xl);
}

.backend-error__message {
  margin: 0;
  white-space: pre-line;
  overflow-wrap: anywhere;
}

.backend-error__text {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.backend-error__log {
  overflow-wrap: anywhere;
  user-select: all;
}
</style>
