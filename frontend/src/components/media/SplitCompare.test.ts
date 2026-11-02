import { afterEach, describe, expect, it } from 'vitest'

import type { Geometry } from '@/api/types'
import { frameLink } from '@/components/preview/testing'
import { mountShell } from '@/components/shell/testing'

import SplitCompare from './SplitCompare.vue'

function geometry(overrides: Partial<Geometry>): Geometry {
  return {
    crop: { top: 0, bottom: 0, left: 0, right: 0 },
    cropped_width: 320,
    cropped_height: 180,
    scaled_width: 320,
    scaled_height: 180,
    output_sar: { num: 1, den: 1 },
    display_aspect: 16 / 9,
    rotation: 0,
    upscaled: false,
    filter_rotation: 0,
    flip_horizontal: false,
    ...overrides,
  }
}

const before = frameLink(1)
const after = frameLink(1, 'output', { width: 640, height: 268 })
const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function compare(props: Record<string, unknown>) {
  const { wrapper } = await mountShell(SplitCompare, { props: { before, after, ...props } })
  mounted.push(wrapper)
  return wrapper
}

/** Where the transform puts a source pixel: the SVG's `transform` applied by hand. */
function place(transform: string, x: number, y: number): [number, number] {
  const steps = [...transform.matchAll(/(\w+)\(([^)]*)\)/g)].map((match) => ({
    name: match[1]!,
    args: match[2]!.split(/[\s,]+/).map(Number),
  }))
  let [px, py] = [x, y]
  for (const { name, args } of steps.toReversed()) {
    if (name === 'translate') [px, py] = [px + args[0]!, py + (args[1] ?? 0)]
    if (name === 'scale') [px, py] = [px * args[0]!, py * (args[1] ?? args[0]!)]
    if (name === 'rotate') {
      const angle = (args[0]! * Math.PI) / 180
      ;[px, py] = [
        Math.round(px * Math.cos(angle) - py * Math.sin(angle)),
        Math.round(px * Math.sin(angle) + py * Math.cos(angle)),
      ]
    }
  }
  return [px + 0, py + 0]
}

function view(wrapper: Awaited<ReturnType<typeof compare>>) {
  const svg = wrapper.find('[data-part="before"]')
  const image = svg.find('image')
  const x = Number(image.attributes('x'))
  const y = Number(image.attributes('y'))
  const transform = image.attributes('transform') ?? ''
  return {
    viewBox: svg.attributes('viewBox'),
    /** The picture point where the source pixel (`sx`, `sy`) lands. */
    at: (sx: number, sy: number) => place(transform, sx + x, sy + y),
  }
}

describe('the before / after compare', () => {
  it('shows the whole source frame without a geometry', async () => {
    const shown = view(await compare({ geometry: null }))
    expect(shown.viewBox).toBe('0 0 320 180')
    expect(shown.at(0, 0)).toEqual([0, 0])
    expect(shown.at(320, 180)).toEqual([320, 180])
  })

  it('shows the source cropped as the output is', async () => {
    const crop = { top: 22, bottom: 24, left: 10, right: 6 }
    const shown = view(await compare({ geometry: geometry({ crop }) }))
    expect(shown.viewBox).toBe('0 0 304 134')
    expect(shown.at(10, 22)).toEqual([0, 0])
    expect(shown.at(314, 156)).toEqual([304, 134])
  })

  it('turns the cropped source clockwise as the output is', async () => {
    const crop = { top: 20, bottom: 0, left: 0, right: 0 }
    const shown = view(await compare({ geometry: geometry({ crop, filter_rotation: 90 }) }))
    expect(shown.viewBox).toBe('0 0 160 320')
    // The top-left corner of the cropped picture goes to the top right.
    expect(shown.at(0, 20)).toEqual([160, 0])
    expect(shown.at(0, 180)).toEqual([0, 0])
  })

  it('flips the source after turning it', async () => {
    const shown = view(
      await compare({ geometry: geometry({ filter_rotation: 90, flip_horizontal: true }) }),
    )
    expect(shown.at(0, 0)).toEqual([0, 0])
    expect(shown.at(0, 180)).toEqual([180, 0])
  })

  it('moves the split with the keyboard', async () => {
    const wrapper = await compare({ geometry: null })
    const range = wrapper.find('input[type="range"]')
    const svg = wrapper.find('[data-part="before"]')
    expect(svg.attributes('style')).toContain('inset(0 50% 0 0)')
    await range.setValue('80')
    expect(svg.attributes('style')).toContain('inset(0 20% 0 0)')
    expect(range.attributes('aria-valuetext')).toBe('80 % source')
  })

  it('shows both pictures next to each other side by side', async () => {
    const wrapper = await compare({ geometry: null, layout: 'side' })
    expect(wrapper.find('input[type="range"]').exists()).toBe(false)
    expect(wrapper.find('[data-part="before"]').attributes('style') ?? '').not.toContain('inset')
    expect(wrapper.findAll('figcaption').map((caption) => caption.text())).toEqual([
      'Source',
      'Output',
    ])
  })

  it('reports an image that did not load', async () => {
    const wrapper = await compare({ geometry: null })
    await wrapper.find('img').trigger('error')
    await wrapper.find('image').trigger('error')
    expect(wrapper.emitted('failed')).toEqual([[after], [before]])
  })

  it.each(['split', 'side'])('reports an image that loaded (%s)', async (layout) => {
    const wrapper = await compare({ geometry: null, layout })
    await wrapper.find('img').trigger('load')
    await wrapper.find('image').trigger('load')
    expect(wrapper.emitted('loaded')).toEqual([[after], [before]])
  })
})
