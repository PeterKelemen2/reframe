<script setup lang="ts">
import Toast, { type ToastMessageOptions } from 'primevue/toast'
import { useToast } from 'primevue/usetoast'
import { onMounted, toRaw, watch } from 'vue'

import { useToastStore } from '@/stores/toasts'

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

function closed(event: { message: ToastMessageOptions }): void {
  const id = ids.get(toRaw(event.message))
  if (id === undefined) return
  onScreen.delete(id)
  toasts.dismiss(id)
}
</script>

<template>
  <Toast class="shell-toasts" @close="closed" @life-end="closed" />
</template>

<!-- Not scoped: the toast is teleported to <body>, out of reach of the scope attribute. -->
<style>
.shell-toasts .p-toast-detail {
  white-space: pre-line;
  overflow-wrap: anywhere;
}
</style>
