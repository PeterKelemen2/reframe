import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import type { AudioCodecRule } from '@/api/types'
import { languages } from '@/components/language/testing'
import { mountShell } from '@/components/shell/testing'
import { trackDefinitions } from '@/components/tracks/testing'
import { useDefaultsStore } from '@/stores/defaults'
import { useSystemStore } from '@/stores/system'

import CodecRuleTable from './CodecRuleTable.vue'
import { completeAudio } from './model'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

function rule(tags: string[] | null, source_channels: AudioCodecRule['source_channels']) {
  return {
    languages: tags,
    source_channels,
    codec: 'ac3',
    mixdown: '5.1',
    max_bitrate: 320,
  } as const
}

async function mountTable(): Promise<void> {
  const { wrapper } = await mountShell(CodecRuleTable, {
    setup: () => {
      const system = useSystemStore()
      system.languages = languages()
      system.definitions = trackDefinitions()
      const defaults = useDefaultsStore()
      defaults.audio = completeAudio({
        codec_rules: [
          rule(['hu'], '5.1_or_more'),
          rule(['en'], '5.1_or_more'),
          { ...rule(null, 'any'), codec: 'aac', mixdown: 'stereo', max_bitrate: 160 },
        ] as AudioCodecRule[],
      })
      defaults.ruleKeys = [11, 12, 13]
    },
  })
  mounted.push(wrapper)
}

const rules = () => useDefaultsStore().audio!.codec_rules!.map((each) => each.languages?.[0] ?? '*')
const body = (index: number) => document.querySelector<HTMLElement>(`tbody[data-index="${index}"]`)!
const button = (index: number, selector: string) =>
  body(index).querySelector<HTMLButtonElement>(selector)!

async function click(target: HTMLElement): Promise<void> {
  target.focus()
  target.click()
  await flushPromises()
}

function dragEvent(type: string, target: HTMLElement): void {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'dataTransfer', {
    value: { setData() {}, setDragImage() {}, effectAllowed: '', dropEffect: '' },
  })
  target.dispatchEvent(event)
}

async function drag(from: number, to: number): Promise<void> {
  dragEvent('dragstart', button(from, '[data-role="drag"]'))
  dragEvent('dragover', body(to))
  dragEvent('drop', body(to))
  await flushPromises()
}

describe('the codec rule table', () => {
  it('locks the catch-all: no drag handle, no move, no remove', async () => {
    await mountTable()
    expect(button(2, '[data-role="drag"]')).toBeNull()
    expect(button(2, '[data-role="locked"]')).not.toBeNull()
    expect(button(2, '[data-move="up"]').disabled).toBe(true)
    expect(button(2, '[data-action="remove"]').disabled).toBe(true)
    // The rule above it cannot go below it either.
    expect(button(1, '[data-move="down"]').disabled).toBe(true)
    expect(body(2).querySelector('[data-field="language"]')!.textContent).toContain('Any language')
  })

  it('moves a rule with the keyboard and keeps the focus on its button', async () => {
    await mountTable()
    await click(button(1, '[data-move="up"]'))
    expect(rules()).toEqual(['en', 'hu', '*'])
    const focused = document.activeElement as HTMLElement
    expect(focused.dataset.move).toBe('down')
    expect(focused.closest('tbody')?.dataset.ruleKey).toBe('12')
  })

  it('moves a dragged rule onto another, and not onto the catch-all', async () => {
    await mountTable()
    await drag(0, 1)
    expect(rules()).toEqual(['en', 'hu', '*'])
    await drag(0, 2)
    expect(rules()).toEqual(['en', 'hu', '*'])
  })

  it('removes a rule and gives the focus to the next one', async () => {
    await mountTable()
    await click(button(0, '[data-action="remove"]'))
    expect(rules()).toEqual(['en', '*'])
    const focused = document.activeElement as HTMLElement
    expect(focused.dataset.action).toBe('remove')
    expect(focused.closest('tbody')?.dataset.ruleKey).toBe('12')
  })

  it('adds a rule above the catch-all and focuses its language', async () => {
    await mountTable()
    await click(document.querySelector<HTMLElement>('[data-action="add-rule"]')!)
    expect(rules()).toEqual(['hu', 'en', '*', '*'])
    expect(useDefaultsStore().audio!.codec_rules![2]!.source_channels).toBe('5.1_or_more')
    expect(document.activeElement?.closest('tbody')?.getAttribute('data-index')).toBe('2')
    expect(document.activeElement?.closest('[data-field="language"]')).not.toBeNull()
  })

  it('expands a rule to its optional settings, where several languages are edited', async () => {
    await mountTable()
    useDefaultsStore().setRule(0, {
      ...useDefaultsStore().audio!.codec_rules![0]!,
      languages: ['hu', 'en'],
    })
    await flushPromises()
    const names = body(0).querySelector<HTMLElement>('[data-field="language"] button')!
    expect(names.textContent).toContain('Hungarian, English')
    await click(names)
    const extras = body(0).querySelector('[data-rule-extras]')
    expect(extras).not.toBeNull()
    expect(
      [...extras!.querySelectorAll('[data-role="item"]')].map((item) =>
        item.getAttribute('data-tag'),
      ),
    ).toEqual(['hu', 'en'])
    expect(button(0, '[data-action="expand"]').getAttribute('aria-expanded')).toBe('true')
  })
})
