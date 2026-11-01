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

  it('in scope file offers no adding or reordering, and points to the matrix', async () => {
    const { wrapper } = await mountInGroup('file')
    expect(button('add').disabled).toBe(true)
    expect(button('add-all').disabled).toBe(true)
    expect(wrapper.find('.output-tracks__handle').exists()).toBe(false)
    expect(wrapper.get('[data-role="file-scope"]').text()).toContain('pick it in the matrix')
  })
})
