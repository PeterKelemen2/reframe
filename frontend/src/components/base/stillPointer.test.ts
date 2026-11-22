import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { installStillPointerFilter } from './stillPointer'

let remove = () => {}
let target: HTMLElement
/** What the page's own listeners saw: `type@x,y` per event. */
let seen: string[]

const record = (event: Event) => {
  const { clientX, clientY } = event as MouseEvent
  seen.push(`${event.type}@${clientX},${clientY}`)
}
const onDocument = () => seen.push('document')
const onWindow = () => seen.push('window')

beforeEach(() => {
  remove = installStillPointerFilter()
  target = document.body.appendChild(document.createElement('div'))
  seen = []
  // As the app's and PrimeVue's listeners are: on elements, the document, and the window
  // after the filter.
  target.addEventListener('mousemove', record)
  document.addEventListener('mousemove', onDocument)
  window.addEventListener('mousemove', onWindow, true)
})

afterEach(() => {
  remove()
  document.removeEventListener('mousemove', onDocument)
  window.removeEventListener('mousemove', onWindow, true)
  document.body.replaceChildren()
})

function move(x: number, y: number, buttons = 0): void {
  target.dispatchEvent(
    new MouseEvent('mousemove', { bubbles: true, clientX: x, clientY: y, buttons }),
  )
}

function onTarget(): string[] {
  return seen.filter((entry) => entry.includes('@'))
}

describe('installStillPointerFilter', () => {
  it('lets the first move through, stops one at the same point, and lets a move elsewhere through at once', () => {
    move(10, 20)
    expect(seen).toEqual(['window', 'mousemove@10,20', 'document'])
    seen = []
    move(10, 20)
    expect(seen).toEqual([])
    move(11, 20)
    move(11, 21)
    move(11, 20)
    move(11, 20)
    expect(onTarget()).toEqual(['mousemove@11,20', 'mousemove@11,21', 'mousemove@11,20'])
  })

  it('never stops a drag: every move with a button down goes on, a still one too', () => {
    move(5, 5)
    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: 5, clientY: 5 }))
    move(5, 5, 1)
    move(8, 5, 1)
    move(8, 5, 1)
    target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: 8, clientY: 5 }))
    move(8, 5)
    expect(onTarget()).toEqual(['mousemove@5,5', 'mousemove@5,5', 'mousemove@8,5', 'mousemove@8,5'])
  })

  it('stops only mousemove: pointer events and the presses and clicks of a tap go on', () => {
    for (const type of ['pointermove', 'mouseover', 'mousedown', 'mouseup', 'click']) {
      target.addEventListener(type, record)
    }
    const tap = () => {
      target.dispatchEvent(
        new PointerEvent('pointermove', { bubbles: true, clientX: 7, clientY: 7 }),
      )
      move(7, 7)
      for (const type of ['mousedown', 'mouseup', 'click']) {
        target.dispatchEvent(new MouseEvent(type, { bubbles: true, clientX: 7, clientY: 7 }))
      }
    }
    tap()
    tap()
    target.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, clientX: 7, clientY: 7 }))
    expect(onTarget()).toEqual([
      'pointermove@7,7',
      'mousemove@7,7',
      'mousedown@7,7',
      'mouseup@7,7',
      'click@7,7',
      'pointermove@7,7',
      'mousedown@7,7',
      'mouseup@7,7',
      'click@7,7',
      'mouseover@7,7',
    ])
  })

  it('can be removed', () => {
    remove()
    move(3, 3)
    move(3, 3)
    expect(onTarget()).toEqual(['mousemove@3,3', 'mousemove@3,3'])
  })
})
