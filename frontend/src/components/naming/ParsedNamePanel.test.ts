import { afterEach, describe, expect, it } from 'vitest'

import { mountBase } from '@/components/base/testing'

import ParsedNamePanel from './ParsedNamePanel.vue'
import { hacksawResult } from './testing/samples'

afterEach(() => {
  document.body.innerHTML = ''
})

function mountPanel(props: Record<string, unknown>) {
  return mountBase(ParsedNamePanel, { props: { result: hacksawResult(), ...props } })
}

describe('ParsedNamePanel', () => {
  it('names the chosen source and why, and marks its candidate', () => {
    const wrapper = mountPanel({})
    expect(wrapper.text()).toContain('Name source: Folder name')
    expect(wrapper.get('[data-testid="name-reason"]').text()).toContain('Folder name: 5 fields')
    const chosen = wrapper.get('.parsed-name__candidate--chosen')
    expect(chosen.attributes('data-kind')).toBe('folder')
  })

  it('colours each recognised part of the original name by its field', () => {
    const wrapper = mountPanel({})
    const marks = wrapper
      .get('[data-kind="folder"]')
      .findAll('mark')
      .map((mark) => [mark.attributes('data-field'), mark.classes().find((c) => c.includes('--'))])
    expect(marks).toEqual([
      ['name', 'parsed-name__span--title'],
      ['year', 'parsed-name__span--year'],
      ['resolution', 'parsed-name__span--resolution'],
      ['source_type', 'parsed-name__span--source'],
      ['release_group', 'parsed-name__span--group'],
    ])
  })

  it('lists the skipped folders the way the locale writes a list', async () => {
    const folders = ['Season 1', 'Disc 2', 'BDMV']
    const wrapper = mountPanel({ result: { ...hacksawResult(), skipped_folders: folders } })
    const skipped = () => wrapper.get('.parsed-name__skipped').text()
    expect(skipped()).toBe('Skipped generic folders: Season 1, Disc 2, BDMV')
    // Japanese joins a list without the English comma and space.
    ;(wrapper.vm as unknown as { $i18n: { locale: string } }).$i18n.locale = 'ja'
    await wrapper.vm.$nextTick()
    const japanese = new Intl.ListFormat('ja', { style: 'short', type: 'unit' }).format(folders)
    expect(japanese).not.toBe(folders.join(', '))
    expect(skipped()).toBe(`Skipped generic folders: ${japanese}`)
  })

  it('has no field inputs unless it is editable', () => {
    expect(mountPanel({}).find('input[data-field]').exists()).toBe(false)
  })

  it('shows the fields the name was made from and emits an edit as an override', async () => {
    const wrapper = mountPanel({ editable: true, overrides: { season: '2' } })
    const year = wrapper.get('input[data-field="year"]')
    expect((year.element as HTMLInputElement).value).toBe('2016')
    await year.setValue('2017')
    expect(wrapper.emitted('update:overrides')?.at(-1)).toEqual([{ season: '2', year: '2017' }])
  })

  it('shows an override instead of the parsed value and resets it to the parsed one', async () => {
    const wrapper = mountPanel({ editable: true, overrides: { name: 'Hacksaw Ridge', year: '' } })
    expect((wrapper.get('input[data-field="name"]').element as HTMLInputElement).value).toBe(
      'Hacksaw Ridge',
    )
    expect(wrapper.find('[data-reset="season"]').exists()).toBe(false)
    await wrapper.get('[data-reset="name"]').trigger('click')
    expect(wrapper.emitted('update:overrides')?.at(-1)).toEqual([{ year: '' }])
  })

  it("shows an override's issue at its field", () => {
    const wrapper = mountPanel({
      editable: true,
      overrides: { season: 'x' },
      issues: [
        {
          severity: 'warning',
          code: 'naming.bad_override',
          path: 'output.naming.field_overrides.season',
          message: "The season override 'x' is not a number",
          fixes: [],
        },
      ],
    })
    const field = wrapper.get('[data-path="output.naming.field_overrides.season"]')
    expect(field.text()).toContain("The season override 'x' is not a number")
    expect(wrapper.get('[data-path="output.naming.field_overrides.year"]').text()).not.toContain(
      'override',
    )
  })
})
