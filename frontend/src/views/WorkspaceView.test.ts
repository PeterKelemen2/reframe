import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, reactive, ref } from 'vue'

import type { SourceEntry, SystemInfo } from '@/api/types'
import { focusWorkspace } from '@/components/shell/focus'
import { mountShell } from '@/components/shell/testing'
import { useSystemStore } from '@/stores/system'

import WorkspaceView from './WorkspaceView.vue'

// Test doubles of the stores and composables of other tasks that the workspace places.
const entries = ref<SourceEntry[]>([])
const activeId = ref<string | null>(null)
const sources = reactive({
  entries,
  activeId,
  active: computed(() => entries.value.find((entry) => entry.id === activeId.value) ?? null),
  probing: [],
  grouping: null,
  pick: vi.fn<() => Promise<void>>(async () => {}),
})
const editor = reactive({ job: null })
const validation = reactive({
  issues: [],
  pending: false,
  counts: { error: 0, warning: 0, info: 0 },
})
const useValidation = vi.fn<() => void>()
const actions = {
  canAdd: ref(false),
  canAddAll: ref(false),
  canStart: ref(false),
  addCurrent: vi.fn<() => Promise<void>>(),
  addAll: vi.fn<() => Promise<void>>(),
  start: vi.fn<() => Promise<void>>(),
}
vi.mock('@/stores/sources', () => ({ useSourcesStore: () => sources }))
vi.mock('@/stores/editor', () => ({ useEditorStore: () => editor }))
vi.mock('@/stores/validation', () => ({ useValidationStore: () => validation }))
vi.mock('@/composables/useValidation', () => ({ useValidation: () => useValidation() }))
vi.mock('@/composables/useQueueActions', () => ({ useQueueActions: () => actions }))

const mounted: { unmount(): void }[] = []

beforeEach(() => {
  sources.entries = []
  sources.activeId = null
  vi.clearAllMocks()
  localStorage.clear()
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountWorkspace(setup?: () => void) {
  const result = await mountShell(WorkspaceView, { setup })
  mounted.push(result.wrapper)
  return result.wrapper
}

function openSource(): void {
  sources.entries = [
    {
      id: 's1',
      path: '/media/Show/Show - S01E02.mkv',
      source: { container: { duration: 3725.4 } } as SourceEntry['source'],
    },
  ]
  sources.activeId = 's1'
}

describe('the workspace', () => {
  it('shows sources, tabs and preview with the source header and the status bar, and validates the job', async () => {
    const wrapper = await mountWorkspace(openSource)
    expect(wrapper.find('[data-field="title"]').text()).toBe('Show - S01E02.mkv')
    expect(wrapper.find('[data-field="duration"]').text()).toBe('1:02:05')
    expect(wrapper.find('.sources-panel').exists()).toBe(true)
    expect(wrapper.findAll('[role="tab"]').map((tab) => tab.text())).toEqual([
      'Summary',
      'Video',
      'Audio',
      'Subtitles',
      'Chapters',
      'Tags',
    ])
    expect(wrapper.find('.preview-panel').exists()).toBe(true)
    expect(wrapper.find('.status-bar').exists()).toBe(true)
    expect(useValidation).toHaveBeenCalledTimes(1)
  })

  it('without a source, says how to open one, and the button opens files', async () => {
    const wrapper = await mountWorkspace()
    expect(wrapper.find('[data-field="title"]').text()).toBe('No source open')
    expect(wrapper.find('[role="tablist"]').exists()).toBe(false)
    expect(wrapper.find('[data-state="empty"]').text()).toContain('Ctrl+O')
    await wrapper.find('.workspace__open').trigger('click')
    expect(sources.pick).toHaveBeenCalledTimes(1)
  })

  it('moves the focus to the selected tab when the opened source replaces the Open button', async () => {
    const wrapper = await mountWorkspace()
    sources.pick.mockImplementationOnce(async () => openSource())
    const button = wrapper.find<HTMLButtonElement>('.workspace__open').element
    button.focus()
    button.click()
    await flushPromises()
    expect(document.activeElement?.getAttribute('role')).toBe('tab')
    expect(document.activeElement?.getAttribute('aria-selected')).toBe('true')
  })

  it('moves the focus to the Open button when the last source goes away', async () => {
    const wrapper = await mountWorkspace(openSource)
    wrapper.find<HTMLElement>('[role="tab"][aria-selected="true"]').element.focus()
    sources.entries = []
    sources.activeId = null
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.find('.workspace__open').element)
  })

  it('leaves the focus alone when the source changes under a control that stays', async () => {
    const wrapper = await mountWorkspace()
    const toggle = wrapper.find<HTMLButtonElement>('.preview-panel__toggle').element
    toggle.focus()
    openSource()
    await flushPromises()
    expect(document.activeElement).toBe(toggle)
  })

  it("gives other screens the workspace's place for the focus: the selected tab", async () => {
    await mountWorkspace(openSource)
    expect(focusWorkspace()).toBe(true)
    expect(document.activeElement?.textContent?.trim()).toBe('Summary')
  })

  it('starts with the preview collapsed, and keeps the user’s choice next time', async () => {
    const wrapper = await mountWorkspace(openSource)
    const toggle = () => wrapper.find('.preview-panel__toggle')
    expect(wrapper.find('.workspace__columns--preview-collapsed').exists()).toBe(true)
    expect(toggle().attributes('aria-expanded')).toBe('false')
    expect(toggle().attributes('aria-label')).toBe('Show the preview')
    await toggle().trigger('click')
    expect(wrapper.find('.workspace__columns--preview-collapsed').exists()).toBe(false)
    expect(toggle().attributes('aria-expanded')).toBe('true')

    const opened = await mountWorkspace(openSource)
    expect(opened.find('.workspace__columns--preview-collapsed').exists()).toBe(false)
    await opened.find('.preview-panel__toggle').trigger('click')
    const closed = await mountWorkspace(openSource)
    expect(closed.find('.workspace__columns--preview-collapsed').exists()).toBe(true)
  })

  it('shows the first-run screen instead while FFmpeg cannot be used', async () => {
    const wrapper = await mountWorkspace(() => {
      useSystemStore().info = {
        tools: {
          ffmpeg: { name: 'ffmpeg', status: 'too_old', reason: 'FFmpeg 4.4 is too old' },
          ffprobe: { name: 'ffprobe', status: 'found' },
        },
      } as SystemInfo
    })
    expect(wrapper.find('[data-screen="first-run"]').text()).toContain('FFmpeg 4.4 is too old')
    expect(wrapper.find('.workspace__columns').exists()).toBe(false)
    expect(wrapper.find('.status-bar').exists()).toBe(false)

    useSystemStore().info = null
    await flushPromises()
    expect(wrapper.find('.workspace__columns').exists()).toBe(true)
  })
})
