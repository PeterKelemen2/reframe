import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, reactive, ref } from 'vue'

import type { JobSettings, QueueJob, Severity, ValidationIssue } from '@/api/types'
import { useQueueStore } from '@/stores/queue'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'

import StatusBar from './StatusBar.vue'
import { mountShell } from './testing'

// Test doubles of the editor and validation stores and of the queue actions.
const editor = reactive({ job: null as JobSettings | null, applyFix: vi.fn<() => Promise<void>>() })
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
  canAddAll: ref(false),
  canStart: ref(false),
  addCurrent: vi.fn<() => Promise<void>>(async () => {}),
  addAll: vi.fn<() => Promise<void>>(async () => {}),
  start: vi.fn<() => Promise<void>>(async () => {}),
}
vi.mock('@/stores/editor', () => ({ useEditorStore: () => editor }))
vi.mock('@/stores/validation', () => ({ useValidationStore: () => validation }))
vi.mock('@/composables/useQueueActions', () => ({ useQueueActions: () => actions }))

const mounted: { unmount(): void }[] = []

beforeEach(() => {
  editor.job = {
    schema_version: 1,
    source: { path: '/m/a.mkv' },
    output: { path: '/out/a.mkv' },
  } as JobSettings
  validation.issues = []
  validation.pending = false
  for (const flag of [actions.canAdd, actions.canAddAll, actions.canStart]) flag.value = false
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
