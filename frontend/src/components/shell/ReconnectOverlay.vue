<script setup lang="ts">
import { LoaderCircle } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

/** Over the app while the desktop app's server starts again, or its owner does not answer. */
const props = defineProps<{
  /** The server that went away was the app's own sidecar. */
  owned: boolean
}>()

const { t } = useI18n()
const text = computed(() =>
  props.owned ? t('desktop.reconnecting.text') : t('desktop.reconnecting.owner'),
)
const root = useTemplateRef<HTMLElement>('root')
const box = useTemplateRef<HTMLElement>('box')

// Everything else on the page waits, also PrimeVue's dialogs and overlays at the end of the page.
let made: Element[] = []
let focused: Element | null = null

onMounted(() => {
  focused = document.activeElement
  made = [...document.body.children].filter(
    (element) => element !== root.value && !element.hasAttribute('inert'),
  )
  for (const element of made) element.setAttribute('inert', '')
  box.value?.focus()
})

onBeforeUnmount(() => {
  for (const element of made) element.removeAttribute('inert')
  if (focused instanceof HTMLElement && focused.isConnected) focused.focus()
})
</script>

<template>
  <Teleport to="body">
    <div ref="root" class="reconnect-overlay" data-overlay="reconnecting">
      <div ref="box" class="reconnect-overlay__box" role="status" tabindex="-1">
        <LoaderCircle class="reconnect-overlay__spinner" :size="32" aria-hidden="true" />
        <h1 class="reconnect-overlay__title">{{ t('desktop.reconnecting.title') }}</h1>
        <p class="reconnect-overlay__text">{{ text }}</p>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.reconnect-overlay {
  position: fixed;
  inset: 0;
  /* Above PrimeVue's dialogs and overlays: each one opened over another adds about 1000. */
  z-index: 10000;
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

.reconnect-overlay__box:focus {
  outline: none;
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
