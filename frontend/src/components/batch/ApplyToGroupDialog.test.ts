import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { mountShell } from '@/components/shell/testing'
import { sampleJob } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { useToastStore } from '@/stores/toasts'

import ApplyToGroupDialog from './ApplyToGroupDialog.vue'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  vi.restoreAllMocks()
})

const job = sampleJob()

async function mountDialog() {
  let editor: ReturnType<typeof useEditorStore> | undefined
  const result = await mountShell(ApplyToGroupDialog, {
    props: { visible: true, groupId: 'g1', groupName: 'Show S01' },
    setup: () => {
      editor = useEditorStore()
      editor.target = { kind: 'job', sourceId: 'e02', job }
    },
  })
  mounted.push(result.wrapper)
  if (editor === undefined) throw new Error('no store')
  return {
    wrapper: result.wrapper,
    merge: vi.spyOn(editor, 'mergeIntoGroup').mockResolvedValue(),
  }
}

const $ = (selector: string) => document.querySelector<HTMLElement>(selector)

async function check(section: string): Promise<void> {
  $(`[data-section="${section}"] input`)?.click()
  await flushPromises()
}

function applyButton(): HTMLButtonElement {
  return $('[data-action="apply"]') as HTMLButtonElement
}

describe('Apply to group', () => {
  it('applies the checked sections only, in the plan’s order, and says so', async () => {
    const { wrapper, merge } = await mountDialog()
    expect(applyButton().disabled).toBe(true)
    await check('subtitles')
    await check('audio')
    await check('tags')
    await check('tags')
    applyButton().click()
    await flushPromises()
    expect(merge).toHaveBeenCalledExactlyOnceWith('g1', job, 'e02', ['audio', 'subtitles'])
    expect(useToastStore().items.map((toast) => toast.summary)).toEqual([
      'Applied to "Show S01": Audio and Subtitles',
    ])
    expect(wrapper.emitted('update:visible')).toEqual([[false]])
  })

  it('changes nothing on Cancel', async () => {
    const { wrapper, merge } = await mountDialog()
    await check('audio')
    $('[data-action="apply-cancel"]')?.click()
    await flushPromises()
    expect(merge).not.toHaveBeenCalled()
    expect(wrapper.emitted('update:visible')).toEqual([[false]])
  })

  it('changes nothing on Escape', async () => {
    const { wrapper, merge } = await mountDialog()
    await check('audio')
    $('[data-section="audio"] input')?.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }),
    )
    await flushPromises()
    expect(merge).not.toHaveBeenCalled()
    expect(wrapper.emitted('update:visible')).toEqual([[false]])
  })

  it('starts with no section checked each time it opens', async () => {
    const { wrapper } = await mountDialog()
    await check('audio')
    await wrapper.setProps({ visible: false })
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(applyButton().disabled).toBe(true)
  })

  it('stays open when the merge fails (its problem is a toast already)', async () => {
    const { wrapper, merge } = await mountDialog()
    merge.mockRejectedValue(
      new ApiError(500, { type: 'about:blank', title: 'Boom', status: 500, code: 'test.boom' }),
    )
    await check('audio')
    applyButton().click()
    await flushPromises()
    expect(wrapper.emitted('update:visible')).toBeUndefined()
    expect(applyButton().disabled).toBe(false)
  })
})
