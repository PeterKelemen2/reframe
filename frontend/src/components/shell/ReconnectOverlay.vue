<script setup lang="ts">
import { LoaderCircle } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

/** Over the app while the desktop app's server starts again. */
const { t } = useI18n()
</script>

<template>
  <div class="reconnect-overlay" data-overlay="reconnecting">
    <div class="reconnect-overlay__box" role="status">
      <LoaderCircle class="reconnect-overlay__spinner" :size="32" aria-hidden="true" />
      <h1 class="reconnect-overlay__title">{{ t('desktop.reconnecting.title') }}</h1>
      <p class="reconnect-overlay__text">{{ t('desktop.reconnecting.text') }}</p>
    </div>
  </div>
</template>

<style scoped>
.reconnect-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: grid;
  place-items: center;
  padding: var(--rf-space-4);
  background: color-mix(in srgb, var(--rf-color-bg) 70%, transparent);
}

.reconnect-overlay__box {
  display: grid;
  justify-items: center;
  gap: var(--rf-space-2);
  max-width: 28rem;
  padding: var(--rf-space-4);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-lg);
  background: var(--rf-color-surface);
  text-align: center;
}

.reconnect-overlay__spinner {
  color: var(--rf-color-text-muted);
  animation: reconnect-spin 1s linear infinite;
}

.reconnect-overlay__title {
  margin: 0;
  font-size: var(--rf-font-size-lg);
}

.reconnect-overlay__text {
  margin: 0;
  color: var(--rf-color-text-muted);
}

@keyframes reconnect-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
