import { describe, expect, it } from 'vitest'

import { installReducedMotionScrolling } from './motion'

/** A window whose reduced-motion setting the test changes, with recording scroll methods. */
function fakeWindow() {
  const setting = { matches: true }
  const calls: unknown[][] = []
  const record =
    (name: string) =>
    (...args: unknown[]) =>
      calls.push([name, ...args])
  const prototype = {
    scrollIntoView: record('scrollIntoView'),
    scroll: record('scroll'),
    scrollTo: record('scrollTo'),
    scrollBy: record('scrollBy'),
  }
  const view = { matchMedia: () => setting, Element: { prototype } }
  return {
    view: view as unknown as Window & { Element: typeof Element },
    prototype,
    setting,
    calls,
  }
}

describe('installReducedMotionScrolling', () => {
  it('turns a smooth scroll into a jump while reduced motion is asked for', () => {
    const { view, prototype, calls } = fakeWindow()
    installReducedMotionScrolling(view)
    prototype.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    prototype.scroll({ left: 4, behavior: 'smooth' })
    prototype.scrollTo({ top: 10, behavior: 'smooth' })
    prototype.scrollBy({ top: 20, behavior: 'smooth' })
    prototype.scrollBy(0, 5)
    expect(calls).toEqual([
      ['scrollIntoView', { block: 'nearest', behavior: 'auto' }],
      ['scroll', { left: 4, behavior: 'auto' }],
      ['scrollTo', { top: 10, behavior: 'auto' }],
      ['scrollBy', { top: 20, behavior: 'auto' }],
      ['scrollBy', 0, 5],
    ])
  })

  it('leaves a smooth scroll smooth when the user has motion on, and can be removed', () => {
    const { view, prototype, setting, calls } = fakeWindow()
    const remove = installReducedMotionScrolling(view)
    setting.matches = false
    prototype.scrollIntoView({ behavior: 'smooth' })
    setting.matches = true
    remove()
    prototype.scrollIntoView({ behavior: 'smooth' })
    expect(calls).toEqual([
      ['scrollIntoView', { behavior: 'smooth' }],
      ['scrollIntoView', { behavior: 'smooth' }],
    ])
  })
})
