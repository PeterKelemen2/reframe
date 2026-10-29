import type { VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it } from 'vitest'
import { h, nextTick } from 'vue'

import type { Language } from '@/api/types'
import { useSystemStore } from '@/stores/system'

import Card from './Card.vue'
import CodecLabel from './CodecLabel.vue'
import KeyValue from './KeyValue.vue'
import LanguageChip from './LanguageChip.vue'
import RoleBadge from './RoleBadge.vue'
import Section from './Section.vue'
import StatusDot from './StatusDot.vue'
import { mountBase } from './testing'

afterEach(() => {
  document.body.replaceChildren()
})

/** The text of the PrimeVue tooltip the element shows on hover. */
async function tooltipOf(wrapper: VueWrapper): Promise<string | null> {
  await wrapper.trigger('mouseenter')
  // The tooltip shows after a zero delay: one timer turn.
  await new Promise((resolve) => setTimeout(resolve, 0))
  const text = document.querySelector('[role="tooltip"]')?.textContent ?? null
  await wrapper.trigger('mouseleave')
  return text
}

describe('RoleBadge', () => {
  it('is solid for a disposition flag and outlined otherwise', () => {
    const solid = mountBase(RoleBadge, {
      props: { role: { role: 'commentary', evidence: 'flag' } },
    })
    const title = mountBase(RoleBadge, {
      props: { role: { role: 'commentary', evidence: 'title' } },
    })
    const guess = mountBase(RoleBadge, {
      props: { role: { role: 'commentary', evidence: 'heuristic' } },
    })
    expect(solid.classes()).toContain('rf-role-badge--solid')
    expect(title.classes()).toContain('rf-role-badge--outlined')
    expect(guess.classes()).toContain('rf-role-badge--outlined')
  })

  it('names the evidence in its tooltip and to screen readers', async () => {
    const wrapper = mountBase(RoleBadge, {
      props: {
        role: { role: 'commentary', evidence: 'title', detail: 'title contains "Kommentar"' },
      },
    })
    expect(wrapper.text()).toBe('Commentary (Found in the track title)')
    expect(await tooltipOf(wrapper)).toBe('Found in the track title\ntitle contains "Kommentar"')
  })

  it('names a description role after the kind of track', () => {
    const role = { role: 'description', evidence: 'flag' }
    expect(mountBase(RoleBadge, { props: { role } }).text()).toMatch(/^Audio description/)
    expect(mountBase(RoleBadge, { props: { role, kind: 'subtitle' } }).text()).toMatch(
      /^Descriptions/,
    )
  })
})

describe('CodecLabel', () => {
  it('shows the commercial name, with the raw codec, long name and profile in the tooltip', async () => {
    const wrapper = mountBase(CodecLabel, {
      props: {
        stream: {
          display_codec: 'DTS-HD MA',
          codec: 'dts',
          codec_long: 'DCA',
          profile: 'DTS-HD MA',
        },
      },
    })
    expect(wrapper.text()).toBe('DTS-HD MA')
    expect(await tooltipOf(wrapper)).toBe('Codec: dts\nDCA\nProfile: DTS-HD MA')
  })

  it("falls back to FFmpeg's codec name, then to unknown", () => {
    expect(mountBase(CodecLabel, { props: { stream: { codec: 'pcm_s24le' } } }).text()).toBe(
      'pcm_s24le',
    )
    const unknown = mountBase(CodecLabel, { props: { stream: { display_codec: null } } })
    expect(unknown.text()).toBe('Unknown codec')
    expect(unknown.classes()).toContain('rf-codec-label--unknown')
  })
})

describe('LanguageChip', () => {
  const LANGUAGES = [
    {
      tag: 'de',
      iso639_1: 'de',
      iso639_2b: 'ger',
      iso639_2t: 'deu',
      iso639_3: 'deu',
      english_name: 'German',
      native_name: 'Deutsch',
      variant: false,
    },
    {
      tag: 'pt-BR',
      iso639_1: 'pt',
      iso639_2b: 'por',
      iso639_2t: 'por',
      iso639_3: 'por',
      english_name: 'Portuguese (Brazil)',
      native_name: 'português (Brasil)',
      variant: true,
    },
    {
      tag: 'pt',
      iso639_1: 'pt',
      iso639_2b: 'por',
      iso639_2t: 'por',
      iso639_3: 'por',
      english_name: 'Portuguese',
      native_name: 'português',
      variant: false,
    },
  ] satisfies Language[]

  function chip(tag: string | null | undefined) {
    const pinia = createPinia()
    setActivePinia(pinia)
    useSystemStore().languages = LANGUAGES
    return mountBase(LanguageChip, { props: { tag }, pinia })
  }

  it('names the language of a tag or any ISO 639 code', () => {
    expect(['de', 'ger', 'DEU', 'pt-BR', 'por'].map((tag) => chip(tag).text())).toEqual([
      'German',
      'German',
      'German',
      'Portuguese (Brazil)',
      'Portuguese',
    ])
  })

  it('shows the code and the native name in the tooltip', async () => {
    expect(await tooltipOf(chip('ger'))).toBe('ger\nDeutsch')
  })

  it('shows an unknown tag as it is, and und or none as undetermined', () => {
    expect(chip('xyz').text()).toBe('xyz')
    for (const tag of ['und', '', null, undefined]) {
      const wrapper = chip(tag)
      expect(wrapper.text()).toBe('Undetermined')
      expect(wrapper.classes()).toContain('rf-language-chip--undetermined')
    }
  })

  it('names the language once the list arrives', async () => {
    setActivePinia(createPinia())
    const wrapper = mountBase(LanguageChip, { props: { tag: 'ger' } })
    expect(wrapper.text()).toBe('ger')
    useSystemStore().languages = LANGUAGES
    await nextTick()
    expect(wrapper.text()).toBe('German')
  })
})

describe('StatusDot', () => {
  it('gives its label to screen readers, or shows it', () => {
    const dot = mountBase(StatusDot, { props: { tone: 'error', label: 'Unavailable' } })
    expect(dot.attributes('role')).toBe('img')
    expect(dot.attributes('aria-label')).toBe('Unavailable')
    expect(dot.classes()).toContain('rf-status-dot--error')
    const labelled = mountBase(StatusDot, {
      props: { tone: 'ok', label: 'Available', showLabel: true },
    })
    expect(labelled.text()).toBe('Available')
    expect(labelled.attributes('role')).toBeUndefined()
  })
})

function shownValue(value: unknown): string {
  return mountBase(KeyValue, { props: { label: 'Size', value } })
    .get('dd')
    .text()
}

describe('KeyValue', () => {
  it('shows a dash for a missing value, but shows zero', () => {
    expect([null, undefined, '', 0, 'x'].map(shownValue)).toEqual(['—', '—', '—', '0', 'x'])
  })
})

describe('Section', () => {
  it('collapses and expands its body from the title button', async () => {
    const wrapper = mountBase(Section, {
      props: { title: 'Audio', collapsible: true },
      slots: { default: () => h('p', 'Body') },
    })
    const button = wrapper.get('button')
    expect(button.attributes('aria-expanded')).toBe('true')
    await button.trigger('click')
    expect(wrapper.emitted('update:collapsed')).toEqual([[true]])
    await wrapper.setProps({ collapsed: true })
    expect(button.attributes('aria-expanded')).toBe('false')
    expect(wrapper.get('.rf-section__body').isVisible()).toBe(false)
  })

  it('has no toggle when it cannot collapse', () => {
    const wrapper = mountBase(Section, { props: { title: 'Audio', collapsed: true } })
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.get('.rf-section__body').isVisible()).toBe(true)
  })
})

describe('Card', () => {
  it('has a header only with a title or a header or actions slot', () => {
    expect(
      mountBase(Card, { slots: { default: () => 'x' } })
        .find('header')
        .exists(),
    ).toBe(false)
    expect(
      mountBase(Card, { props: { title: 'Source' } })
        .get('header h3')
        .text(),
    ).toBe('Source')
    expect(
      mountBase(Card, { slots: { actions: () => 'a' } })
        .find('header')
        .exists(),
    ).toBe(true)
  })
})
