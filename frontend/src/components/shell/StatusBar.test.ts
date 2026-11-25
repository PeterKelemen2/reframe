import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, reactive, ref } from 'vue'

import { deferred } from '@/api/testing/fakes'
import type { JobSettings, QueueJob, Severity, ValidationIssue } from '@/api/types'
import type { ActiveGroup, ChangesQuestion } from '@/composables/useQueueActions'
import type { EditorTarget } from '@/stores/editor'
import { useQueueStore } from '@/stores/queue'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'

import StatusBar from './StatusBar.vue'
import { mountShell } from './testing'

// Test doubles of the editor and validation stores and of the queue actions.
const editor = reactive({
  job: null as JobSettings | null,
  target: null as EditorTarget | null,
  session: 0,
  applyFix: vi.fn<() => Promise<void>>(),
})
const validation = reactive({
  issues: [] as ValidationIssue[],
  pending: false,
  counts: computed(() => {
    const counts: Record<Severity, number> = { error: 0, warning: 0, info: 0 }
    for (const found of validation.issues) counts[found.severity] += 1
    return counts
  }),
})
const actions = {
  canAdd: ref(false),
  canAddOnly: ref(false),
  canAddAll: ref(false),
  canStart: ref(false),
  busy: ref(false),
  activeGroup: ref<ActiveGroup | null>(null),
  changes: ref<ChangesQuestion | null>(null),
  addCurrent: vi.fn<() => Promise<void>>(async () => {}),
  addGroup: vi.fn<() => Promise<void>>(async () => {}),
  dismissChanges: vi.fn<() => void>(() => {
    actions.changes.value = null
  }),
  addOnly: vi.fn<() => Promise<void>>(async () => {}),
  addAll: vi.fn<() => Promise<void>>(async () => {}),
  start: vi.fn<() => Promise<void>>(async () => {}),
}
vi.mock('@/stores/editor', () => ({ useEditorStore: () => editor }))
vi.mock('@/stores/validation', () => ({ useValidationStore: () => validation }))
vi.mock('@/composables/useQueueActions', () => ({ useQueueActions: () => actions }))

const mounted: { unmount(): void }[] = []

beforeEach(() => {
  editor.target = null
  editor.job = {
    schema_version: 1,
    source: { path: '/m/a.mkv' },
    output: { path: '/out/a.mkv' },
  } as JobSettings
  validation.issues = []
  validation.pending = false
  for (const flag of [
    actions.canAdd,
    actions.canAddOnly,
    actions.canAddAll,
    actions.canStart,
    actions.busy,
  ]) {
    flag.value = false
  }
  actions.activeGroup.value = null
  actions.changes.value = null
  vi.clearAllMocks()
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountBar() {
  const result = await mountShell(StatusBar)
  mounted.push(result.wrapper)
  return result.wrapper
}

function list(): Element | null {
  return document.querySelector('.validation-summary__list')
}

function job(id: string, state: QueueJob['state']): QueueJob {
  return { id, state } as QueueJob
}

function issue(severity: Severity, message: string, path = 'video.encoder'): ValidationIssue {
  return { severity, code: 'test', path, message }
}

describe('the status bar', () => {
  it("shows the job's output path, or that there is none", async () => {
    const wrapper = await mountBar()
    expect(wrapper.find('[data-field="output-path"]').text()).toBe('/out/a.mkv')
    editor.job = null
    await flushPromises()
    expect(wrapper.find('[data-field="output"]').text()).toContain('No output path yet')
  })

  it('sums up the issues by severity, and says when there are none or a check runs', async () => {
    validation.issues = [
      issue('error', 'a'),
      issue('warning', 'b'),
      issue('warning', 'c'),
      issue('info', 'd'),
    ]
    const wrapper = await mountBar()
    const summary = () => wrapper.find('.validation-summary').text().replace(/\s+/g, ' ')
    expect(summary()).toBe('1 error 2 warnings 1 note')
    validation.issues = []
    await flushPromises()
    expect(summary()).toBe('No issues')
    validation.pending = true
    await flushPromises()
    expect(summary()).toBe('Checking…')
  })

  it('opens the list of issues on a click and closes it when an issue shows its field', async () => {
    validation.issues = [issue('warning', 'The bitrate is high', 'audio[0].bitrate')]
    const wrapper = await mountBar()
    await wrapper.find('.validation-summary').trigger('click')
    await flushPromises()
    expect(list()?.textContent).toContain('The bitrate is high')
    await vi.waitFor(() =>
      expect(wrapper.find('.validation-summary').attributes('aria-expanded')).toBe('true'),
    )

    document.querySelector<HTMLButtonElement>('.rf-issue__reveal')?.click()
    await flushPromises()
    expect(useUiStore().activeTab).toBe('audio')
    await vi.waitFor(() => expect(list()).toBeNull())
  })

  it('takes the focus into the list of issues when it opens: its first control, else the list', async () => {
    validation.issues = [issue('warning', 'The bitrate is high', 'audio[0].bitrate')]
    const wrapper = await mountBar()
    const summary = wrapper.find<HTMLButtonElement>('.validation-summary').element
    summary.focus()
    summary.click()
    await vi.waitFor(() => expect(list()?.contains(document.activeElement)).toBe(true))
    expect(document.activeElement?.classList.contains('rf-issue__reveal')).toBe(true)
    summary.click()
    await vi.waitFor(() => expect(list()).toBeNull())

    validation.issues = []
    await flushPromises()
    summary.click()
    await vi.waitFor(() => expect(document.activeElement).toBe(list()))
  })

  it('keeps the focus on an empty list of issues as Tab goes round, and Escape gives it back', async () => {
    const wrapper = await mountBar()
    const summary = wrapper.find<HTMLButtonElement>('.validation-summary').element
    summary.focus()
    summary.click()
    await vi.waitFor(() => expect(document.activeElement).toBe(list()))
    // Tab from the list reaches the popover's focus guard after it, which sends it round.
    const guards = document.querySelectorAll<HTMLElement>('.p-popover .p-hidden-focusable')
    guards[guards.length - 1]?.focus()
    expect(document.activeElement).toBe(list())
    document.activeElement?.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }),
    )
    await vi.waitFor(() => expect(list()).toBeNull())
    expect(document.activeElement).toBe(summary)
  })

  it('shows the wait of an add on the button that started it', async () => {
    actions.canAdd.value = true
    actions.canAddAll.value = true
    const wrapper = await mountBar()
    const busyOf = () =>
      ['add', 'add-all'].filter(
        (name) => wrapper.find(`.status-bar__${name}`).attributes('aria-busy') === 'true',
      )
    // Ctrl+Enter or the button: the add waits for the job's check.
    actions.busy.value = true
    await flushPromises()
    expect(busyOf()).toEqual(['add'])
    actions.busy.value = false

    const drafts = deferred()
    actions.addAll.mockImplementationOnce(async () => {
      actions.busy.value = true
      await drafts.promise
      actions.busy.value = false
    })
    await wrapper.find('.status-bar__add-all').trigger('click')
    await flushPromises()
    expect(busyOf()).toEqual(['add-all'])
    drafts.resolve()
    await flushPromises()
    expect(busyOf()).toEqual([])
    // A later Ctrl+Enter waits on Add to queue again.
    actions.busy.value = true
    await flushPromises()
    expect(busyOf()).toEqual(['add'])
  })

  it('publishes its height for the toasts while it is shown', async () => {
    const observed: ResizeObserverCallback[] = []
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(callback: ResizeObserverCallback) {
          observed.push(callback)
        }
        observe(): void {}
        disconnect(): void {}
      },
    )
    try {
      const wrapper = await mountBar()
      const entry = { borderBoxSize: [{ blockSize: 48.4, inlineSize: 900 }] }
      for (const callback of observed) callback([entry] as never, {} as ResizeObserver)
      const root = document.documentElement.style
      expect(root.getPropertyValue('--shell-status-bar-height')).toBe('49px')
      wrapper.unmount()
      mounted.splice(0)
      expect(root.getPropertyValue('--shell-status-bar-height')).toBe('')
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('shows a lost connection in words', async () => {
    const wrapper = await mountBar()
    const system = useSystemStore()
    system.connection = 'open'
    await flushPromises()
    expect(wrapper.find('.connection-status').text()).toBe('')
    system.connection = 'reconnecting'
    await flushPromises()
    expect(wrapper.find('.connection-status').text()).toBe('Connection lost, reconnecting…')
    system.connection = 'unauthorized'
    await flushPromises()
    expect(wrapper.find('.connection-status').text()).toBe('Signed out by the server')
  })

  it('sums up the queue', async () => {
    const wrapper = await mountBar()
    expect(wrapper.find('[data-field="queue"]').text()).toBe('Queue: nothing waiting')
    useQueueStore().jobs = [
      job('a', 'running'),
      job('b', 'waiting'),
      job('c', 'waiting'),
      job('d', 'done'),
      job('e', 'paused'),
    ]
    await flushPromises()
    expect(wrapper.find('[data-field="queue"]').text()).toBe(
      'Queue: 1 running · 1 paused · 2 waiting',
    )
  })

  it('enables each queue action when it can run, and runs it', async () => {
    const wrapper = await mountBar()
    const enabled = () =>
      ['add', 'add-all', 'start'].filter(
        (name) => wrapper.find(`.status-bar__${name}`).attributes('disabled') === undefined,
      )
    expect(enabled()).toEqual([])
    actions.canAdd.value = true
    await flushPromises()
    expect(enabled()).toEqual(['add'])
    actions.canAdd.value = false
    actions.canAddAll.value = true
    await flushPromises()
    expect(enabled()).toEqual(['add-all'])
    actions.canAddAll.value = false
    actions.canStart.value = true
    await flushPromises()
    expect(enabled()).toEqual(['start'])

    actions.canAdd.value = true
    actions.canAddAll.value = true
    await flushPromises()
    await wrapper.find('.status-bar__add').trigger('click')
    await wrapper.find('.status-bar__add-all').trigger('click')
    await wrapper.find('.status-bar__start').trigger('click')
    expect(actions.addCurrent).toHaveBeenCalledTimes(1)
    expect(actions.addAll).toHaveBeenCalledTimes(1)
    expect(actions.start).toHaveBeenCalledTimes(1)
  })

  it('names the add after the active group, with the shown file alone beside it', async () => {
    const wrapper = await mountBar()
    const add = () => wrapper.find('.status-bar__add')
    const only = () => wrapper.find('.status-bar__only')
    expect(add().text()).toBe('Add to queue')
    expect(only().exists()).toBe(false)
    expect(add().attributes('aria-keyshortcuts')).toBe('Control+Enter')

    actions.activeGroup.value = { groupId: 'g', count: 12, episodes: true, label: 'E01' }
    await flushPromises()
    expect(add().text()).toBe('Add 12 episodes to queue')
    expect(only().text()).toBe('Only E01')
    expect(only().attributes('aria-label')).toBe('Add only E01 to queue')

    actions.activeGroup.value = { groupId: 'g', count: 3, episodes: false, label: null }
    await flushPromises()
    expect(add().text()).toBe('Add 3 files to queue')
    expect(only().text()).toBe('Only this file')

    actions.canAddOnly.value = true
    await flushPromises()
    await only().trigger('click')
    expect(actions.addOnly).toHaveBeenCalledTimes(1)
    expect(actions.addCurrent).not.toHaveBeenCalled()
  })

  it('names Add all open files apart from the Audio tab’s Add all', async () => {
    const wrapper = await mountBar()
    expect(wrapper.find('.status-bar__add-all').text()).toBe('Add all open files')
  })

  it('asks before the group is queued without the open file’s own changes', async () => {
    actions.activeGroup.value = { groupId: 'g', count: 12, episodes: true, label: 'E01' }
    const wrapper = await mountBar()
    expect(wrapper.find('[data-state="changes"]').exists()).toBe(false)
    actions.changes.value = { groupId: 'g', label: 'E01' }
    await flushPromises()
    const question = wrapper.find('[data-state="changes"]')
    expect(question.attributes('role')).toBe('alertdialog')
    expect(question.find('p').text()).toBe(
      "Your changes to E01 are not in the group's settings. The group is queued without them.",
    )
    expect(document.activeElement).toBe(question.find('[data-action="changes-apply"]').element)

    await question.find('[data-action="changes-queue"]').trigger('click')
    expect(actions.addGroup).toHaveBeenCalledTimes(1)

    actions.changes.value = { groupId: 'g', label: 'E01' }
    await flushPromises()
    await wrapper.find('[data-action="changes-cancel"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-state="changes"]').exists()).toBe(false)
    expect(actions.addGroup).toHaveBeenCalledTimes(1)

    actions.changes.value = { groupId: 'g', label: 'E01' }
    await flushPromises()
    await wrapper.find('[data-action="changes-apply"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-state="changes"]').exists()).toBe(false)
    expect(document.querySelector('[data-dialog="apply-to-group"]')).not.toBeNull()
  })

  it('drops the question when another file opens', async () => {
    const wrapper = await mountBar()
    actions.changes.value = { groupId: 'g', label: 'E01' }
    await flushPromises()
    editor.session += 1
    await flushPromises()
    expect(wrapper.find('[data-state="changes"]').exists()).toBe(false)
  })

  // A browser moves the focus of a button that turns disabled to the page.
  it.each([
    ['add', actions.canAdd, actions.addCurrent],
    ['add-all', actions.canAddAll, actions.addAll],
    ['start', actions.canStart, actions.start],
  ] as const)(
    'the %s button keeps the focus while its action makes it unavailable',
    async (name, flag, run) => {
      flag.value = true
      const wrapper = await mountBar()
      run.mockImplementationOnce(async () => {
        flag.value = false
      })
      const button = wrapper.find<HTMLButtonElement>(`.status-bar__${name}`).element
      button.focus()
      button.click()
      await flushPromises()
      expect(run).toHaveBeenCalledTimes(1)
      expect(document.activeElement).toBe(button)
      expect(button.disabled).toBe(false)
      expect(button.getAttribute('aria-disabled')).toBe('true')
      // Unavailable: Enter on it does nothing.
      button.click()
      await flushPromises()
      expect(run).toHaveBeenCalledTimes(1)
      // Once the focus has left, it is disabled for real (out of the tab order).
      button.blur()
      await flushPromises()
      expect(button.disabled).toBe(true)
      flag.value = true
      await flushPromises()
      expect(button.disabled).toBe(false)
      expect(button.hasAttribute('aria-disabled')).toBe(false)
    },
  )
})
