<script setup lang="ts">
import { useEventListener } from '@vueuse/core'
import Toast, { type ToastMessageOptions } from 'primevue/toast'
import { useToast } from 'primevue/usetoast'
import { computed, nextTick, onMounted, ref, toRaw, watch } from 'vue'

import { useToastStore } from '@/stores/toasts'

import { STATUS_BAR_HEIGHT } from './StatusBar.vue'

const toasts = useToastStore()
const toast = useToast()

/** The store's id of each message on screen. */
const ids = new WeakMap<object, number>()
const onScreen = new Set<number>()

function show(items: typeof toasts.items): void {
  for (const item of items) {
    if (onScreen.has(item.id)) continue
    onScreen.add(item.id)
    const message: ToastMessageOptions = {
      severity: item.severity,
      summary: item.summary,
      detail: item.detail,
      life: item.life,
    }
    ids.set(message, item.id)
    toast.add(message)
  }
}

// PrimeVue's toast drops messages added before it listens, so the first ones wait for its mount.
// A toast leaves the store only when it leaves the screen: the API client shows one "cannot be
// reached" toast at a time by looking for it in the store.
onMounted(() => watch(() => toasts.items, show, { immediate: true, deep: true }))

/**
 * Bottom right, clear of the header's controls and of the status bar's actions. The focus must
 * never be hidden under them (WCAG 2.4.11): on something they cover they go to the top right,
 * and where they cover it there too, out of sight until the focus moves on.
 */
const atTop = ref(false)
const aside = ref(false)
const position = computed(() => ({
  root: {
    class: { 'shell-toasts--aside': aside.value },
    style: atTop.value
      ? { top: 'var(--rf-space-3)', bottom: 'auto' }
      : { top: 'auto', bottom: `calc(var(${STATUS_BAR_HEIGHT}, 0px) + var(--rf-space-3))` },
  },
}))

function covered(focused: Element): boolean {
  const box = focused.getBoundingClientRect()
  return [...document.querySelectorAll('.shell-toasts .p-toast-message')].some((message) => {
    const over = message.getBoundingClientRect()
    const across = over.left < box.right && box.left < over.right
    return across && over.top < box.bottom && box.top < over.bottom
  })
}

useEventListener(document, 'focusin', async (event: FocusEvent) => {
  const focused = event.target
  if (!(focused instanceof Element) || focused.closest('.shell-toasts') !== null) return
  aside.value = false
  if (!covered(focused)) return
  atTop.value = !atTop.value
  await nextTick()
  if (document.activeElement === focused && covered(focused)) aside.value = true
})

function closed(event: { message: ToastMessageOptions }): void {
  const id = ids.get(toRaw(event.message))
  if (id === undefined) return
  onScreen.delete(id)
  toasts.dismiss(id)
}
</script>

<template>
  <Toast
    class="shell-toasts"
    :position="atTop ? 'top-right' : 'bottom-right'"
    :pt="position"
    @close="closed"
    @life-end="closed"
  />
</template>

<!-- Not scoped: the toast is teleported to <body>, out of reach of the scope attribute. -->
<style>
.shell-toasts .p-toast-detail {
  white-space: pre-line;
  overflow-wrap: anywhere;
}

.shell-toasts--aside {
  visibility: hidden;
}

/* A note on the panel's own ground: ink text, the state told by its icon and its border colour.
   The theme's toast colours are see-through and blurred over the page. */
.shell-toasts .p-toast-message {
  --shell-toast-tone: var(--p-status-info-color);
  --shell-toast-edge: var(--p-status-info-border-color);

  border: 1px solid var(--shell-toast-edge);
  border-radius: var(--rf-radius-md);
  background: var(--rf-color-surface);
  color: var(--rf-color-text);
  box-shadow: 0 6px 20px -8px rgb(18 22 30 / 0.28);
  backdrop-filter: none;
}

.shell-toasts .p-toast-message-success {
  --shell-toast-tone: var(--p-status-ok-color);
  --shell-toast-edge: var(--p-status-ok-border-color);
}

.shell-toasts .p-toast-message-warn {
  --shell-toast-tone: var(--p-status-warn-color);
  --shell-toast-edge: var(--p-status-warn-border-color);
}

.shell-toasts .p-toast-message-error {
  --shell-toast-tone: var(--p-status-error-color);
  --shell-toast-edge: var(--p-status-error-border-color);
}

.shell-toasts .p-toast-message .p-toast-message-icon {
  color: var(--shell-toast-tone);
}

.shell-toasts .p-toast-message .p-toast-summary {
  color: var(--rf-color-text);
  font-weight: var(--rf-font-weight-bold);
}

.shell-toasts .p-toast-message .p-toast-detail {
  color: var(--rf-color-text);
}

.shell-toasts .p-toast-message .p-toast-close-button {
  color: var(--rf-color-text-muted);
}

.shell-toasts .p-toast-message .p-toast-close-button:hover {
  background: var(--rf-color-surface-hover);
  color: var(--rf-color-text);
}
</style>
