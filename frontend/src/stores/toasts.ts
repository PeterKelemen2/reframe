import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastSeverity = 'success' | 'info' | 'warn' | 'error' | 'secondary'

export interface Toast {
  id: number
  severity: ToastSeverity
  /** Already translated. */
  summary: string
  detail?: string
  /** Milliseconds; none: stays until closed. */
  life?: number
}

/**
 * Toasts from code that is not a component (the API client, event handlers). The shell shows
 * each one with PrimeVue's toast and then calls `dismiss`.
 */
export const useToastStore = defineStore('toasts', () => {
  const items = ref<Toast[]>([])
  let next = 1

  function push(toast: Omit<Toast, 'id'>): number {
    const id = next++
    items.value.push({ ...toast, id })
    return id
  }

  function dismiss(id: number): void {
    items.value = items.value.filter((toast) => toast.id !== id)
  }

  return { items, push, dismiss }
})
