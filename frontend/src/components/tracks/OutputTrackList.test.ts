import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import type { GroupScope } from '@/stores/editor'
import { templateOfPreset } from '@/stores/presets'
import { samplePreset } from '@/editor/testing/samples'
import { useDefaultsStore } from '@/stores/defaults'

import { mountEditor, prepareDom, unmountAll } from './editorTesting'
import OutputTrackList from './OutputTrackList.vue'

beforeAll(prepareDom)
afterEach(unmountAll)

/** The subtitle list of the open job, then the job shown as file `src` of group `g1`. */
async function mountInGroup(scope: GroupScope) {
  const mounted = await mountEditor(OutputTrackList, { props: { list: 'subtitles' } })
  const { editor } = mounted
  editor.target = {
    kind: 'group',
    groupId: 'g1',
    sourceId: 'src',
    job: editor.job!,
    template: templateOfPreset(samplePreset()),
    presetId: null,
    overrides: {},
    scope,
  }
  await flushPromises()
  return mounted
}

const button = (action: string) =>
  document.querySelector<HTMLButtonElement>(`.output-tracks [data-action="${action}"]`)!

/** The visible text that describes a control, as a screen reader reads it. */
function description(control: Element): string {
  return (control.getAttribute('aria-describedby') ?? '')
    .split(/\s+/)
    .map((id) => document.getElementById(id)?.textContent?.trim() ?? '')
    .join(' ')
}

const rowButtons = () =>
  [...document.querySelectorAll<HTMLButtonElement>('.track-row__buttons button')].map(
    (found) => found.disabled,
  )

describe('the output track list in a group', () => {
  it("opens the group's defaults, offers adding tracks, and no preset reload or external file", async () => {
    await mountInGroup('group')
    const open = vi.spyOn(useDefaultsStore(), 'open').mockResolvedValue()
    button('defaults').click()
    expect(open).toHaveBeenCalledWith('subtitles', { kind: 'group', groupId: 'g1' })
    expect(button('add').disabled).toBe(false)
    expect(button('reload').disabled).toBe(true)
    expect(button('add-external').disabled).toBe(true)
    expect(document.querySelector('[data-role="file-scope"]')).toBeNull()
  })

  it('says why Reload from preset rules and Add external subtitle are off, in text the buttons point to', async () => {
    await mountInGroup('group')
    expect(description(button('reload'))).toContain(
      'Reload from preset rules is not available in a group',
    )
    expect(description(button('add-external'))).toContain('belongs to one file')
  })

  it('in scope group moves and removes tracks', async () => {
    await mountInGroup('group')
    expect(rowButtons()).toContain(false)
  })

  it('in scope file offers no adding or reordering, and points to the matrix', async () => {
    const { wrapper } = await mountInGroup('file')
    expect(button('add').disabled).toBe(true)
    expect(button('add-all').disabled).toBe(true)
    expect(wrapper.find('.output-tracks__handle').exists()).toBe(false)
    expect(wrapper.get('[data-role="file-scope"]').text()).toContain('pick it in the matrix')
    expect(description(button('add'))).toContain('pick it in the matrix')
    expect(description(button('add-all'))).toContain('pick it in the matrix')
  })

  it('in scope file moves and removes no track, and says why', async () => {
    await mountInGroup('file')
    expect(rowButtons().length).toBeGreaterThan(0)
    expect(rowButtons()).not.toContain(false)
    const buttons = document.querySelector('.track-row__buttons')!
    expect(description(buttons.querySelector('[data-action="remove"]')!)).toContain(
      'pick it in the matrix',
    )
  })
})
