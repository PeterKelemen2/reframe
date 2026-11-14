import Dialog from 'primevue/dialog'

interface DialogInstance {
  container: HTMLElement | null
}

type Hook = (this: DialogInstance, ...args: unknown[]) => void

/**
 * Keeps the focus where it is when a PrimeVue Dialog's enter transition ends, if it is inside
 * the dialog already. A modal dialog's focus trap focuses `[autofocus]` as the dialog mounts;
 * the dialog focuses it again once the transition ends, which took back a Tab pressed in the
 * meantime. Call it before the first Dialog is created; returns the function that removes it.
 */
export function installDialogFocus(): () => void {
  const methods = (Dialog as unknown as { methods: { onAfterEnter: Hook } }).methods
  const { onAfterEnter } = methods
  methods.onAfterEnter = function (this: DialogInstance, ...args: unknown[]) {
    if (this.container?.contains(document.activeElement) === true) return
    onAfterEnter.apply(this, args)
  }
  return () => {
    methods.onAfterEnter = onAfterEnter
  }
}
