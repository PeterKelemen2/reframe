import { flushPromises, mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import Dialog from 'primevue/dialog'
import Menu from 'primevue/menu'
import Select from 'primevue/select'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, onMounted, ref } from 'vue'

import { installKeyboardFixes } from './keyboard'

/** Mounts with PrimeVue's transitions running: a dialog binds its Escape key when it enters. */
function mountWithTransitions(component: ReturnType<typeof defineComponent>) {
  return mount(component, {
    attachTo: document.body,
    global: { plugins: [[PrimeVue, { theme: 'none' }]], stubs: { transition: false } },
  })
}

async function settle(): Promise<void> {
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 20))
  await flushPromises()
}

let remove: (() => void) | undefined

beforeEach(() => {
  remove = installKeyboardFixes()
})

afterEach(() => {
  remove?.()
  document.body.replaceChildren()
})

function escape(target: Element): void {
  target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }))
}

const DialogWithSelect = defineComponent({
  setup() {
    // Opened after the mount, so that its enter transition runs.
    const visible = ref(false)
    onMounted(() => (visible.value = true))
    const value = ref('a')
    return () => [
      h('output', { class: 'state' }, String(visible.value)),
      h(
        Dialog,
        {
          visible: visible.value,
          'onUpdate:visible': (next: boolean) => (visible.value = next),
          modal: true,
          header: 'Dialog',
          'data-open': String(visible.value),
        },
        () => [
          h(Select, {
            modelValue: value.value,
            options: ['a', 'b'],
            appendTo: 'self',
            'onUpdate:modelValue': (next: string) => (value.value = next),
          }),
        ],
      ),
    ]
  },
})

describe('installKeyboardFixes', () => {
  it('lets Escape on a closed Select close its dialog', async () => {
    mountWithTransitions(DialogWithSelect)
    await settle()
    const label = document.querySelector('.p-select-label') as HTMLElement
    expect(label.getAttribute('aria-expanded')).toBe('false')
    escape(label)
    await vi.waitFor(() => expect(document.querySelector('.state')?.textContent).toBe('false'))
  })

  it('leaves Escape to an open Select, which closes only its list', async () => {
    mountWithTransitions(DialogWithSelect)
    await settle()
    const label = document.querySelector('.p-select-label') as HTMLElement
    label.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', code: 'ArrowDown', bubbles: true }))
    await flushPromises()
    expect(label.getAttribute('aria-expanded')).toBe('true')
    escape(label)
    await flushPromises()
    await vi.waitFor(() => expect(label.getAttribute('aria-expanded')).toBe('false'))
    expect(document.querySelector('.state')?.textContent).toBe('true')
  })

  it('puts the first item of a popup menu in focus when the menu opens', async () => {
    const Host = defineComponent({
      setup(_, { expose }) {
        const menu = ref<InstanceType<typeof Menu> | null>(null)
        expose({ open: (event: Event) => menu.value?.show(event) })
        return () =>
          h(Menu, {
            ref: menu,
            popup: true,
            model: [{ label: 'One' }, { label: 'Two' }],
          })
      },
    })
    const wrapper = mountWithTransitions(Host)
    const button = document.createElement('button')
    document.body.append(button)
    button.addEventListener('click', (event) =>
      (wrapper.vm as unknown as { open(event: Event): void }).open(event),
    )
    button.click()
    await settle()
    const list = document.querySelector<HTMLElement>('.p-menu-list') as HTMLElement
    // What the menu does as it opens in a browser.
    list.focus()
    await flushPromises()
    const active = list.getAttribute('aria-activedescendant')
    expect(active).toBeTruthy()
    expect(document.getElementById(active as string)?.textContent).toContain('One')
  })
})
