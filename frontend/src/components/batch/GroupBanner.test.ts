import { flushPromises } from '@vue/test-utils'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Ref } from 'vue'

import { configureClient } from '@/api/client'
import { deferred, FakeServer } from '@/api/testing/fakes'
import type { Schemas, SourceEntry } from '@/api/types'
import PresetNameDialog from '@/components/presets/PresetNameDialog.vue'
import { nameConflict, presetList, userPreset } from '@/components/presets/testing'
import { mountShell } from '@/components/shell/testing'
import { sampleJob, samplePreset } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { templateOfPreset } from '@/stores/presets'
import { useSourcesStore } from '@/stores/sources'
import { useToastStore } from '@/stores/toasts'
import { useUiStore } from '@/stores/ui'

import ApplyToGroupDialog from './ApplyToGroupDialog.vue'
import GroupBanner from './GroupBanner.vue'

const queue = vi.hoisted(() => ({
  queueGroup: vi.fn<(id: string) => Promise<void>>(),
  busy: { value: false } as Ref<boolean>,
}))
vi.mock('@/composables/useQueueGroup', async () => {
  const { computed, ref } = await import('vue')
  queue.busy = ref(false)
  return {
    useQueueGroup: () => ({ busy: computed(() => queue.busy.value), queueGroup: queue.queueGroup }),
  }
})

const episodes: SourceEntry[] = [1, 2, 5].map((n) => ({
  id: `e0${n}`,
  path: `/m/show/Show.S01E0${n}.mkv`,
  source: null,
}))

const grouping: Schemas['BatchGrouping'] = {
  groups: [
    {
      id: 'g1',
      name: 'Show S01',
      level: 'standard',
      representative: '/m/show/Show.S01E01.mkv',
      fingerprint: {} as Schemas['Fingerprint'],
      members: episodes.map((episode, index) => ({
        path: episode.path,
        season: 1,
        episode: [1, 2, 5][index],
        match: 'exact',
      })),
    },
  ],
  issues: [],
}

const TEMPLATE = templateOfPreset(samplePreset())

let server: FakeServer
const mounted: { unmount(): void }[] = []

beforeEach(() => {
  server = new FakeServer()
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  queue.queueGroup.mockReset().mockResolvedValue()
  queue.busy.value = false
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  vi.restoreAllMocks()
})

type Target = 'group' | 'member' | 'alone'

async function mountBanner(target: Target) {
  let stores:
    | { editor: ReturnType<typeof useEditorStore>; sources: ReturnType<typeof useSourcesStore> }
    | undefined
  const result = await mountShell(GroupBanner, {
    setup: () => {
      const sources = useSourcesStore()
      const editor = useEditorStore()
      sources.entries = [...episodes, { id: 'movie', path: '/m/movie.mkv', source: null }]
      sources.grouping = grouping
      sources.activeId = target === 'alone' ? 'movie' : 'e01'
      editor.target =
        target === 'group'
          ? {
              kind: 'group',
              groupId: 'g1',
              sourceId: 'e01',
              job: sampleJob(),
              template: TEMPLATE,
              presetId: null,
              overrides: { e02: [{ op: 'replace', path: '/job/range', value: { kind: 'full' } }] },
              scope: 'group',
            }
          : { kind: 'job', sourceId: target === 'member' ? 'e02' : 'movie', job: sampleJob() }
      stores = { editor, sources }
    },
  })
  mounted.push(result.wrapper)
  if (stores === undefined) throw new Error('no stores')
  const { editor, sources } = stores
  return {
    wrapper: result.wrapper,
    editor,
    sources,
    showFile: vi.spyOn(editor, 'showFile').mockResolvedValue(),
    setScope: vi.spyOn(editor, 'setScope').mockResolvedValue(),
    editGroup: vi.spyOn(editor, 'editGroup').mockResolvedValue(),
    applyPreset: vi.spyOn(editor, 'applyPreset').mockResolvedValue(),
    select: vi.spyOn(sources, 'select').mockResolvedValue(),
  }
}

const $ = (selector: string) => document.querySelector<HTMLElement>(selector)
const text = (element: Element | null) => element?.textContent?.replace(/\s+/g, ' ').trim()

async function click(selector: string): Promise<void> {
  const element = $(selector)
  if (element === null) throw new Error(`no ${selector}`)
  element.click()
  await flushPromises()
}

describe('the group banner', () => {
  it('names the edited group, its size and the shown file', async () => {
    await mountBanner('group')
    expect(text($('[data-state="group"] [data-field="title"]'))).toBe(
      'Editing group “Show S01” (3 files) — showing E01',
    )
    expect($('[data-state="member"]')).toBeNull()
  })

  it('shows another file of the group from the switcher, labelled as in the panel', async () => {
    const { wrapper, showFile } = await mountBanner('group')
    const switcher = wrapper.findComponent(Select)
    expect(switcher.props('options')).toEqual([
      { label: 'E01', value: 'e01' },
      { label: 'E02', value: 'e02' },
      { label: 'E05', value: 'e05' },
    ])
    switcher.vm.$emit('update:modelValue', 'e05')
    await flushPromises()
    expect(showFile).toHaveBeenCalledExactlyOnceWith('e05')
  })

  it('switches where the edits go: the group or the shown file only', async () => {
    const { wrapper, setScope } = await mountBanner('group')
    const scope = wrapper.findComponent(SelectButton)
    expect(scope.props('modelValue')).toBe('group')
    expect((scope.props('options') as { label: string }[]).map((option) => option.label)).toEqual([
      'Group',
      'This file only (E01)',
    ])
    scope.vm.$emit('update:modelValue', 'file')
    await flushPromises()
    expect(setScope).toHaveBeenCalledExactlyOnceWith('file')
  })

  it('checks the group in the matrix and queues it', async () => {
    await mountBanner('group')
    const openMatrix = vi.spyOn(useUiStore(), 'openMatrix')
    await click('[data-action="check-group"]')
    expect(openMatrix).toHaveBeenCalledOnce()
    await click('[data-action="queue-group"]')
    expect(queue.queueGroup).toHaveBeenCalledExactlyOnceWith('g1')
  })

  it('keeps Add group to queue focusable while it runs, and the focus on it after', async () => {
    await mountBanner('group')
    const done = deferred()
    queue.queueGroup.mockImplementation(async () => {
      queue.busy.value = true
      await done.promise
      queue.busy.value = false
    })
    const button = $('[data-action="queue-group"]') as HTMLButtonElement
    button.focus()
    await click('[data-action="queue-group"]')
    expect(button.disabled).toBe(false)
    expect(button.getAttribute('aria-busy')).toBe('true')
    expect(document.activeElement).toBe(button)
    done.resolve()
    await flushPromises()
    expect(button.getAttribute('aria-busy')).toBeNull()
    expect(document.activeElement).toBe(button)
  })

  it('closes the group by opening the shown file as one job', async () => {
    const { select } = await mountBanner('group')
    await click('[data-action="close-group"]')
    expect(select).toHaveBeenCalledExactlyOnceWith('e01')
  })

  it('offers Apply to group and Edit group while a file of a group is open as one job', async () => {
    const { editGroup } = await mountBanner('member')
    expect($('[data-state="group"]')).toBeNull()
    expect(text($('[data-state="member"] [data-field="title"]'))).toBe('In group “Show S01”')
    await click('[data-action="apply-to-group"]')
    expect($('[data-dialog="apply-to-group"]')).not.toBeNull()
    await click('[data-action="edit-group"]')
    expect(editGroup).toHaveBeenCalledExactlyOnceWith('g1')
  })

  it('shows nothing for a file in no group', async () => {
    await mountBanner('alone')
    expect($('.group-banner')).toBeNull()
  })

  it('gives the focus back to Apply to group when its dialog has closed', async () => {
    const { wrapper } = await mountBanner('member')
    await click('[data-action="apply-to-group"]')
    await click('[data-action="apply-cancel"]')
    const dialog = wrapper.findComponent(ApplyToGroupDialog)
    expect(dialog.props('visible')).toBe(false)
    // The focus was in the dialog, which has left the page.
    ;(document.activeElement as HTMLElement | null)?.blur()
    dialog.findComponent({ name: 'Dialog' }).vm.$emit('after-hide')
    await flushPromises()
    expect(document.activeElement).toBe($('[data-action="apply-to-group"]'))
  })
})

async function save(name: string): Promise<void> {
  await click('[data-action="save-as-preset"]')
  const input = $('.preset-name-dialog__name') as HTMLInputElement
  input.value = name
  input.dispatchEvent(new Event('input'))
  await flushPromises()
  await click('.preset-name-dialog__submit')
}

describe('Save as preset', () => {
  it('saves the template without the overrides, reads the presets again, and makes it the group’s preset', async () => {
    const saved = userPreset('u9', 'Anime BD')
    server.on('POST /api/batch/save-preset', saved).on('GET /api/presets', presetList([saved]))
    const { wrapper, applyPreset } = await mountBanner('group')
    await save('Anime BD')
    expect(
      server.requests.find((request) => request.path === '/api/batch/save-preset')?.body,
    ).toEqual({
      template: TEMPLATE,
      name: 'Anime BD',
      category: 'Custom',
      description: '',
    })
    expect(server.count('GET /api/presets')).toBe(1)
    expect(applyPreset).toHaveBeenCalledExactlyOnceWith('u9')
    expect(useToastStore().items.map((toast) => toast.summary)).toEqual(['Preset “Anime BD” saved'])
    expect(wrapper.findComponent(PresetNameDialog).props('visible')).toBe(false)
  })

  it('shows a taken name at the field and saves nothing', async () => {
    server.on('POST /api/batch/save-preset', () => nameConflict('Anime BD', 'Anime BD (2)'))
    const { applyPreset } = await mountBanner('group')
    await save('Anime BD')
    expect(text($('.preset-name-dialog'))).toContain('A preset named “Anime BD” already exists.')
    expect(applyPreset).not.toHaveBeenCalled()
    expect(useToastStore().items).toEqual([])
  })
})
