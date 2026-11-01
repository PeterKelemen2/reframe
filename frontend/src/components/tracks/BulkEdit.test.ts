import { flushPromises, type VueWrapper } from '@vue/test-utils'
import DataTable from 'primevue/datatable'
import SelectButton from 'primevue/selectbutton'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import AudioTab from '@/components/editor/tabs/AudioTab.vue'
import LanguagePicker from '@/components/language/LanguagePicker.vue'

import BulkEditDialog from './BulkEditDialog.vue'
import { mountEditor, prepareDom, unmountAll } from './editorTesting'

beforeAll(prepareDom)
afterEach(unmountAll)

const checkbox = (wrapper: VueWrapper, which: string) =>
  wrapper.find(`[data-select="${which}"] input`)

async function openDialog(wrapper: VueWrapper) {
  await wrapper.find('[data-action="bulk-edit"]').trigger('click')
  await nextTick()
  return wrapper.findComponent(BulkEditDialog)
}

function flagChoice(dialog: VueWrapper, flag: string, state: 'leave' | 'on' | 'off'): void {
  const control = dialog.findAllComponents(SelectButton).find((candidate) => {
    const labelled = String(candidate.props('ariaLabelledby'))
    return document.getElementById(labelled)?.closest(`[data-flag="${flag}"]`) !== null
  })
  control?.vm.$emit('update:modelValue', state)
}

const apply = () => document.querySelector<HTMLButtonElement>('[data-action="bulk-apply"]')!

describe('bulk edit of the selected output tracks', () => {
  it('sets language and flags of the selected tracks only, as one undo step', async () => {
    const { wrapper, editor } = await mountEditor(AudioTab)
    await checkbox(wrapper, '0').setValue(true)
    await checkbox(wrapper, '2').setValue(true)
    expect(wrapper.find('[data-role="selection"]').text()).toContain('2 tracks selected')
    const dialog = await openDialog(wrapper)
    expect(apply().disabled).toBe(true)
    const setLanguage = document.querySelector<HTMLInputElement>('.bulk-edit__check input')!
    setLanguage.checked = true
    setLanguage.dispatchEvent(new Event('change'))
    dialog.findComponent(LanguagePicker).vm.$emit('update:modelValue', 'hu')
    flagChoice(dialog as unknown as VueWrapper, 'commentary', 'on')
    flagChoice(dialog as unknown as VueWrapper, 'default', 'off')
    await nextTick()
    apply().click()
    await flushPromises()
    const metadata = editor.job?.audio?.map((track) => track.metadata)
    expect(metadata?.[0]).toMatchObject({ language: 'hu', commentary: true, default: false })
    expect(metadata?.[1]).toMatchObject({ language: 'en', commentary: false })
    expect(metadata?.[2]).toMatchObject({ language: 'hu', commentary: true })
    expect(metadata?.[0]?.name).toBe('Japanese 5.1')
    expect(wrapper.find('[data-action="bulk-edit"]').exists()).toBe(false)
    editor.undo()
    expect(editor.job?.audio?.[0]?.metadata).toMatchObject({ language: 'ja', default: true })
    expect(editor.job?.audio?.[2]?.metadata).toMatchObject({ language: 'en' })
  })

  it('leaves the language alone unless it is chosen to be set', async () => {
    const { wrapper, editor } = await mountEditor(AudioTab)
    await checkbox(wrapper, '1').setValue(true)
    const dialog = await openDialog(wrapper)
    dialog.findComponent(LanguagePicker).vm.$emit('update:modelValue', 'hu')
    flagChoice(dialog as unknown as VueWrapper, 'original', 'on')
    await nextTick()
    apply().click()
    await flushPromises()
    expect(editor.job?.audio?.[1]?.metadata).toMatchObject({ language: 'en', original: true })
  })

  it('selects every track with Select all, and none with it again', async () => {
    const { wrapper } = await mountEditor(AudioTab)
    await checkbox(wrapper, 'all').setValue(true)
    expect(wrapper.find('[data-role="selection"]').text()).toContain('3 tracks selected')
    await checkbox(wrapper, 'all').setValue(false)
    expect(wrapper.find('[data-action="bulk-edit"]').exists()).toBe(false)
  })

  it('edits only the selected track after it changed place with another output of its stream', async () => {
    const { wrapper, editor } = await mountEditor(AudioTab, {
      job(job) {
        const first = job.audio![0]!
        const copy = { ...first, encoder: 'ac3', metadata: { ...first.metadata!, name: 'AC-3' } }
        job.audio!.splice(1, 0, copy)
      },
    })
    await checkbox(wrapper, '0').setValue(true)
    wrapper.findComponent(DataTable).vm.$emit('row-reorder', { dragIndex: 1, dropIndex: 0 })
    await nextTick()
    expect((checkbox(wrapper, '0').element as HTMLInputElement).checked).toBe(false)
    expect((checkbox(wrapper, '1').element as HTMLInputElement).checked).toBe(true)
    const before = editor.job?.audio ?? []
    expect(before[1]?.metadata?.original).not.toBe(true)
    const dialog = await openDialog(wrapper)
    flagChoice(dialog as unknown as VueWrapper, 'original', 'on')
    await nextTick()
    apply().click()
    await flushPromises()
    const audio = editor.job?.audio ?? []
    expect(audio[0]).toEqual(before[0])
    expect(audio[0]?.encoder).toBe('ac3')
    expect(audio[1]?.metadata?.original).toBe(true)
    expect(audio.slice(2)).toEqual(before.slice(2))
  })

  it('offers no selection for a single track, where it would do nothing', async () => {
    const { wrapper } = await mountEditor(AudioTab, {
      job(job) {
        job.audio!.splice(1)
      },
    })
    expect(wrapper.find('[data-path="audio[0]"]').exists()).toBe(true)
    expect(wrapper.find('[data-select]').exists()).toBe(false)
  })

  it('leaves the focus in the selection bar when Clear the selection removes its button', async () => {
    const { wrapper } = await mountEditor(AudioTab)
    await checkbox(wrapper, '1').setValue(true)
    const clear = wrapper.find<HTMLButtonElement>('[data-action="bulk-clear"]')
    clear.element.focus()
    await clear.trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(checkbox(wrapper, 'all').element)
  })

  it('leaves the focus in the selection bar after Apply', async () => {
    const { wrapper } = await mountEditor(AudioTab)
    await checkbox(wrapper, '1').setValue(true)
    const dialog = await openDialog(wrapper)
    flagChoice(dialog as unknown as VueWrapper, 'forced', 'on')
    await nextTick()
    apply().focus()
    apply().click()
    await flushPromises()
    dialog.findComponent({ name: 'Dialog' }).vm.$emit('after-hide')
    await flushPromises()
    expect(document.activeElement).toBe(checkbox(wrapper, 'all').element)
  })

  it('keeps the selection while a selected track is edited', async () => {
    const { wrapper, editor } = await mountEditor(AudioTab)
    await checkbox(wrapper, '1').setValue(true)
    editor.set('/audio/1/metadata/forced', true)
    await nextTick()
    expect(wrapper.find('[data-role="selection"]').text()).toContain('1 track selected')
  })

  it('starts each opening of the dialog from "change nothing"', async () => {
    const { wrapper } = await mountEditor(AudioTab)
    await checkbox(wrapper, '1').setValue(true)
    let dialog = await openDialog(wrapper)
    flagChoice(dialog as unknown as VueWrapper, 'forced', 'on')
    await nextTick()
    expect(apply().disabled).toBe(false)
    document.querySelector<HTMLButtonElement>('[data-action="bulk-cancel"]')!.click()
    await nextTick()
    dialog = await openDialog(wrapper)
    expect(apply().disabled).toBe(true)
  })
})
