import { flushPromises } from '@vue/test-utils'
import { getActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, reactive, ref } from 'vue'

import type { SourceEntry, SystemInfo } from '@/api/types'
import type { EditorTabId } from '@/components/editor/tabs/registry'
import { FIRST_RUN_KEY } from '@/components/shell/firstRun'
import { focusWorkspace } from '@/components/shell/focus'
import { mountShell } from '@/components/shell/testing'
import { platform } from '@/platform'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'

import WorkspaceView from './WorkspaceView.vue'

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
  addLocal: () => {},
})
const useValidation = vi.fn<() => void>()
const actions = {
  canAdd: ref(false),
  canAddOnly: ref(false),
  canAddAll: ref(false),
  canStart: ref(false),
  activeGroup: ref(null),
  changes: ref(null),
  dismissChanges: vi.fn<() => void>(),
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
  Object.assign(platform, { kind: 'web' })
})

function bundledTool(name: string) {
  return { name, status: 'found', origin: 'bundled', path: `/app/${name}` }
}

/** Every tool found, bundled with the desktop app. */
function working(): SystemInfo {
  return {
    mode: 'desktop',
    tools: {
      ffmpeg: bundledTool('ffmpeg'),
      ffprobe: bundledTool('ffprobe'),
    },
  } as SystemInfo
}

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
      'Dimensions',
      'Filters',
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

  it('starts with the preview shown, and keeps the user’s choice next time', async () => {
    const wrapper = await mountWorkspace(openSource)
    const toggle = () => wrapper.find('.preview-panel__toggle')
    expect(wrapper.find('.workspace__columns--preview-collapsed').exists()).toBe(false)
    expect(toggle().attributes('aria-expanded')).toBe('true')
    expect(toggle().attributes('aria-label')).toBe('Hide the preview')
    await toggle().trigger('click')
    expect(wrapper.find('.workspace__columns--preview-collapsed').exists()).toBe(true)
    expect(toggle().attributes('aria-expanded')).toBe('false')

    const closed = await mountWorkspace(openSource)
    expect(closed.find('.workspace__columns--preview-collapsed').exists()).toBe(true)
    await closed.find('.preview-panel__toggle').trigger('click')
    const opened = await mountWorkspace(openSource)
    expect(opened.find('.workspace__columns--preview-collapsed').exists()).toBe(false)
  })

  it('hides the preview on the tabs without the picture, and keeps a choice for each kind of tab', async () => {
    const wrapper = await mountWorkspace(openSource)
    const ui = useUiStore()
    const collapsed = () => wrapper.find('.workspace__columns--preview-collapsed').exists()
    const toggle = () => wrapper.find('.preview-panel__toggle')
    async function show(tab: EditorTabId): Promise<void> {
      ui.activeTab = tab
      await flushPromises()
    }

    expect(collapsed()).toBe(false)
    await show('audio')
    expect(collapsed()).toBe(true)
    expect(toggle().text()).toBe('Preview')
    expect(toggle().attributes('aria-label')).toBe('Show the preview')
    await toggle().trigger('click')
    expect(collapsed()).toBe(false)
    await show('tags')
    expect(collapsed()).toBe(false)
    await show('dimensions')
    await toggle().trigger('click')
    expect(collapsed()).toBe(true)
    await show('chapters')
    expect(collapsed()).toBe(false)

    const again = await mountWorkspace(openSource)
    expect(again.find('.workspace__columns--preview-collapsed').exists()).toBe(true)
    useUiStore().activeTab = 'subtitles'
    await flushPromises()
    expect(again.find('.workspace__columns--preview-collapsed').exists()).toBe(false)
  })

  it('starts the crop store, which detects the crop whichever tab is shown', async () => {
    await mountWorkspace()
    expect(getActivePinia()?.state.value.crop).toBeDefined()
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

  describe('the first start', () => {
    it('in the desktop app shows the tools before the workspace, once', async () => {
      Object.assign(platform, { kind: 'desktop' })
      const first = await mountWorkspace(() => {
        useSystemStore().info = working()
      })
      expect(first.find('[data-screen="first-run"]').exists()).toBe(true)
      expect(first.find('.workspace__columns').exists()).toBe(false)

      await first.find('.first-run__continue').trigger('click')
      await flushPromises()
      expect(first.find('.workspace__columns').exists()).toBe(true)
      expect(document.activeElement).toBe(first.find('.workspace__open').element)

      first.unmount()
      const second = await mountWorkspace(() => {
        useSystemStore().info = working()
      })
      expect(second.find('[data-screen="first-run"]').exists()).toBe(false)
      expect(second.find('.workspace__columns').exists()).toBe(true)
    })

    it('after the first start comes back only while FFmpeg cannot be used', async () => {
      Object.assign(platform, { kind: 'desktop' })
      localStorage.setItem(FIRST_RUN_KEY, 'true')
      const wrapper = await mountWorkspace(() => {
        useSystemStore().info = working()
      })
      expect(wrapper.find('.workspace__columns').exists()).toBe(true)

      const broken = working()
      broken.tools.ffmpeg = { ...broken.tools.ffmpeg, status: 'missing', reason: 'gone' }
      useSystemStore().info = broken
      await flushPromises()
      expect(wrapper.find('[data-screen="first-run"]').exists()).toBe(true)
      expect(wrapper.find('.first-run__continue').exists()).toBe(false)
    })

    it('in a browser goes straight to the workspace', async () => {
      const wrapper = await mountWorkspace(() => {
        useSystemStore().info = working()
      })
      expect(wrapper.find('[data-screen="first-run"]').exists()).toBe(false)
      expect(wrapper.find('.workspace__columns').exists()).toBe(true)
    })
  })
})
