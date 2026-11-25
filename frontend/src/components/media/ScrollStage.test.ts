import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ScrollStage from './ScrollStage.vue'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

/** jsdom lays nothing out: the stage's scroll size and position are set by hand. */
async function stage(options: { scrolls?: boolean } = {}) {
  const wrapper = mount(ScrollStage, {
    attachTo: document.body,
    slots: { default: '<button class="inner" type="button">picture</button>' },
  })
  mounted.push(wrapper)
  const element = wrapper.element as HTMLElement
  const sizes = { scrollWidth: options.scrolls === false ? 100 : 800, clientWidth: 100 }
  Object.defineProperties(element, {
    scrollWidth: { value: sizes.scrollWidth },
    clientWidth: { value: sizes.clientWidth },
    scrollHeight: { value: 100 },
    clientHeight: { value: 100 },
    scrollLeft: { value: 100, writable: true },
    scrollTop: { value: 40, writable: true },
  })
  await wrapper.vm.$nextTick()
  return { wrapper, element }
}

function space(type: 'keydown' | 'keyup', target: EventTarget = window): KeyboardEvent {
  const event = new KeyboardEvent(type, { code: 'Space', bubbles: true, cancelable: true })
  target.dispatchEvent(event)
  return event
}

// jsdom has no PointerEvent; a MouseEvent of the same type carries what the stage reads.
function pointer(target: Element, type: string, clientX = 0, clientY = 0): void {
  target.dispatchEvent(new MouseEvent(type, { button: 0, clientX, clientY, bubbles: true }))
}

const hover = (element: Element) => element.dispatchEvent(new MouseEvent('pointerenter'))

describe('the scroll stage', () => {
  it('turns a drag into a scroll while Space is held, and gives the cursor to the drag', async () => {
    const { wrapper, element } = await stage()
    hover(element)
    expect(space('keydown').defaultPrevented).toBe(true)
    await wrapper.vm.$nextTick()
    expect(element.dataset.pan).toBe('ready')

    pointer(element, 'pointerdown', 200, 100)
    await wrapper.vm.$nextTick()
    expect(element.dataset.pan).toBe('dragging')
    pointer(element, 'pointermove', 150, 80)
    expect([element.scrollLeft, element.scrollTop]).toEqual([150, 60])
    pointer(element, 'pointermove', 260, 130)
    expect([element.scrollLeft, element.scrollTop]).toEqual([40, 10])
    pointer(element, 'pointerup')
    await wrapper.vm.$nextTick()
    expect(element.dataset.pan).toBe('ready')

    pointer(element, 'pointermove', 0, 0)
    expect([element.scrollLeft, element.scrollTop]).toEqual([40, 10])
    space('keyup')
    await wrapper.vm.$nextTick()
    expect(element.dataset.pan).toBeUndefined()
  })

  it('does not scroll on a drag without Space', async () => {
    const { element } = await stage()
    hover(element)
    pointer(element, 'pointerdown', 200, 100)
    pointer(element, 'pointermove', 150, 80)
    expect([element.scrollLeft, element.scrollTop]).toEqual([100, 40])
  })

  it('keeps the press from the picture inside while it pans', async () => {
    const { wrapper, element } = await stage()
    const inner = wrapper.find('.inner').element
    const pressed = vi.fn<() => void>()
    inner.addEventListener('pointerdown', pressed)
    hover(element)
    space('keydown')
    pointer(inner, 'pointerdown', 10, 10)
    expect(pressed).not.toHaveBeenCalled()
    pointer(element, 'pointerup')
    space('keyup')
    pointer(inner, 'pointerdown', 10, 10)
    expect(pressed).toHaveBeenCalledTimes(1)
  })

  it('leaves Space alone when there is nothing to scroll', async () => {
    const { element } = await stage({ scrolls: false })
    hover(element)
    expect(space('keydown').defaultPrevented).toBe(false)
    expect(element.dataset.pan).toBeUndefined()
  })

  it('leaves Space alone when the pointer is elsewhere', async () => {
    await stage()
    expect(space('keydown').defaultPrevented).toBe(false)
  })

  it('takes Space from a button that has the focus while the pointer is over the stage', async () => {
    const { element } = await stage()
    const outside = document.createElement('button')
    document.body.append(outside)
    outside.focus()
    expect(space('keydown', outside).defaultPrevented).toBe(false)
    hover(element)
    expect(space('keydown', outside).defaultPrevented).toBe(true)
    expect(space('keyup', outside).defaultPrevented).toBe(true)
    expect(space('keyup', outside).defaultPrevented).toBe(false)
  })

  it('leaves Space to a text field', async () => {
    const { element } = await stage()
    const field = document.createElement('input')
    document.body.append(field)
    hover(element)
    expect(space('keydown', field).defaultPrevented).toBe(false)
  })

  it('takes Space from the stage with the focus in it, and not with a modifier', async () => {
    const { element } = await stage()
    element.setAttribute('tabindex', '0')
    element.focus()
    expect(space('keydown', element).defaultPrevented).toBe(true)
    const withControl = new KeyboardEvent('keydown', {
      code: 'Space',
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    })
    element.dispatchEvent(withControl)
    expect(withControl.defaultPrevented).toBe(false)
  })

  it('stops panning when the window loses the focus', async () => {
    const { wrapper, element } = await stage()
    hover(element)
    space('keydown')
    pointer(element, 'pointerdown', 200, 100)
    window.dispatchEvent(new Event('blur'))
    await wrapper.vm.$nextTick()
    expect(element.dataset.pan).toBeUndefined()
    pointer(element, 'pointermove', 150, 80)
    expect([element.scrollLeft, element.scrollTop]).toEqual([100, 40])
  })
})
