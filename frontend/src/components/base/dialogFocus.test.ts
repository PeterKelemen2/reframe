import { flushPromises, mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import Dialog from 'primevue/dialog'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { defineComponent, h, onMounted, ref } from 'vue'

import { installDialogFocus } from './dialogFocus'

let remove: (() => void) | undefined

beforeEach(() => {
  remove = installDialogFocus()
})

afterEach(() => {
  remove?.()
  document.body.replaceChildren()
})

/** A modal dialog opened after the mount, so that its enter transition runs. */
function openDialog(autofocus: boolean): HTMLButtonElement {
  const opener = document.createElement('button')
  document.body.append(opener)
  opener.focus()
  const Host = defineComponent({
    setup() {
      const visible = ref(false)
      onMounted(() => (visible.value = true))
      return () =>
        h(Dialog, { visible: visible.value, modal: true, header: 'Dialog' }, () => [
          h('input', { class: 'first', autofocus: autofocus || undefined }),
          h('input', { class: 'second' }),
        ])
    },
  })
  mount(Host, {
    attachTo: document.body,
    global: { plugins: [[PrimeVue, { theme: 'none' }]], stubs: { transition: false } },
  })
  return opener
}

/** Long enough for the enter transition to end in jsdom (two animation frames). */
function transitionEnd(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 100))
}

describe('installDialogFocus', () => {
  it('keeps a focus the user moved inside the dialog while it was entering', async () => {
    openDialog(true)
    await flushPromises()
    expect(document.activeElement?.className).toBe('first')
    document.querySelector<HTMLElement>('.second')?.focus()
    await transitionEnd()
    expect(document.activeElement?.className).toBe('second')
  })

  it('still brings the focus into the dialog when the transition ends outside it', async () => {
    const opener = openDialog(false)
    await flushPromises()
    expect(document.activeElement).toBe(opener)
    await transitionEnd()
    expect(document.querySelector('.p-dialog')?.contains(document.activeElement)).toBe(true)
  })
})
