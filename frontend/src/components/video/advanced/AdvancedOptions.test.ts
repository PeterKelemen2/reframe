import { flushPromises, type VueWrapper } from '@vue/test-utils'
import InputNumber from 'primevue/inputnumber'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import ToggleSwitch from 'primevue/toggleswitch'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { deferred } from '@/api/testing/fakes'
import type { EncoderOption, JobSettings } from '@/api/types'
import { mountShell } from '@/components/shell/testing'
import type { VideoEncoderDef } from '@/components/video/encoders'
import { openJob, setUpVideo } from '@/components/video/testing'
import { sampleJob } from '@/editor/testing/samples'
import { useUiStore } from '@/stores/ui'

import AdvancedOptions from './AdvancedOptions.vue'
import CopyHdrMetadata from './CopyHdrMetadata.vue'
import CustomParams from './CustomParams.vue'
import recorded from './testing/x265-options.json'
import { panelView } from './view'

const OPTIONS = recorded as unknown as EncoderOption[]
const SEARCH = 'GET /api/definitions/encoders/libx265/options'
const SOON = { timeout: 2000, interval: 20 }

const mounted: { unmount(): void }[] = []

// jsdom has none; a reveal scrolls its field into view.
Element.prototype.scrollIntoView ??= () => undefined

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  localStorage.clear()
  Object.assign(panelView, { category: null, query: '', changedOnly: false })
})

function jobWith(video: Partial<NonNullable<JobSettings['video']>>): JobSettings {
  const job = sampleJob()
  job.video = { ...job.video!, ...video }
  return job
}

/** The server's search: the recorded options whose key holds the query. */
function searchAnswer(url: string): EncoderOption[] {
  const query = new URLSearchParams(url).get('q') ?? ''
  return OPTIONS.filter((option) => option.key.includes(query))
}

async function mountPanel(job: JobSettings = sampleJob()) {
  const setup = setUpVideo({ job })
  const encoders = setup.system.definitions!.video_encoders as Record<string, VideoEncoderDef>
  encoders.libx265!.options = OPTIONS
  setup.server.on(SEARCH, (request: { search: string }) => searchAnswer(request.search))
  await openJob()
  const { wrapper } = await mountShell(AdvancedOptions, { pinia: setup.pinia })
  mounted.push(wrapper)
  await flushPromises()
  return { ...setup, wrapper }
}

function row(wrapper: VueWrapper, key: string) {
  return wrapper.find(`.advanced-row[data-option="${key}"]`)
}

function shownKeys(wrapper: VueWrapper): string[] {
  return wrapper.findAll('.advanced-row').map((found) => found.attributes('data-option') ?? '')
}

/** The PrimeVue control of an option, with its props as plain values. */
function control(wrapper: VueWrapper, key: string, component: object) {
  const found = row(wrapper, key).findComponent(component as never) as unknown as VueWrapper
  return {
    prop: (name: string) => (found.props() as Record<string, unknown>)[name],
    emit: (value: unknown) => found.vm.$emit('update:modelValue', value),
  }
}

async function choose(wrapper: VueWrapper, category: string): Promise<void> {
  await wrapper.find(`[data-category="${category}"]`).trigger('click')
}

function pause(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function search(wrapper: VueWrapper, text: string): Promise<void> {
  await wrapper.find('[data-role="search"]').setValue(text)
}

function count(wrapper: VueWrapper, category: string): string | undefined {
  return wrapper.find(`[data-category="${category}"]`).attributes('data-count')
}

describe('the advanced options panel', () => {
  it('lists the categories in panel order with their changed counts', async () => {
    const { wrapper } = await mountPanel(
      jobWith({ advanced: { bframes: 6, 'b-intra': true, 'psy-rd': 1 } }),
    )
    const categories = wrapper.findAll('[data-category]')
    expect(categories.map((found) => found.find('.advanced-options__name').text())).toEqual([
      'Rate control',
      'Frame types / GOP',
      'Psycho-visual',
      'HDR / colour',
      'Performance',
      'Custom parameters',
    ])
    expect(categories.map((found) => found.attributes('data-count'))).toEqual([
      '0',
      '2',
      '1',
      '0',
      '0',
      '0',
    ])
    expect(shownKeys(wrapper)).toEqual(['aq-strength'])
    await choose(wrapper, 'Frame types / GOP')
    expect(shownKeys(wrapper)).toEqual(['bframes', 'b-adapt', 'keyint', 'min-keyint', 'b-intra'])
  })

  it('searches once the typing stops, with each match in its category', async () => {
    const { wrapper, server } = await mountPanel()
    await search(wrapper, 'b')
    await pause(50)
    await search(wrapper, 'bf')
    await pause(50)
    await search(wrapper, 'bfr')
    await vi.waitFor(() => expect(shownKeys(wrapper)).toEqual(['bframes']), SOON)
    expect(server.count(SEARCH)).toBe(1)
    expect(row(wrapper, 'bframes').find('.advanced-row__category').text()).toBe('Frame types / GOP')
    await search(wrapper, '')
    expect(shownKeys(wrapper)).toEqual(['aq-strength'])
  })

  it("shows only the newest query's matches", async () => {
    const { wrapper, server } = await mountPanel()
    const slow = deferred<EncoderOption[]>()
    server.on(SEARCH, (request: { search: string }) =>
      request.search.includes('psy') ? slow.promise : searchAnswer(request.search),
    )
    await search(wrapper, 'psy')
    await vi.waitFor(() => expect(server.count(SEARCH)).toBe(1), SOON)
    await search(wrapper, 'pools')
    await vi.waitFor(() => expect(shownKeys(wrapper)).toEqual(['pools']), SOON)
    slow.resolve(searchAnswer('?q=psy'))
    await flushPromises()
    expect(shownKeys(wrapper)).toEqual(['pools'])
  })

  it('shows the custom parameters in a search for their category, not in others', async () => {
    const { wrapper } = await mountPanel()
    await search(wrapper, 'custom')
    await vi.waitFor(() => expect(wrapper.find('[data-state="no-match"]').exists()).toBe(false))
    expect(wrapper.findComponent(CustomParams).exists()).toBe(true)
    await search(wrapper, 'psy')
    await vi.waitFor(() => expect(shownKeys(wrapper)).toEqual(['psy-rd']), SOON)
    expect(wrapper.findComponent(CustomParams).exists()).toBe(false)
  })

  it('shows only changed options, and the custom parameters while they are set', async () => {
    const { wrapper, editor } = await mountPanel(jobWith({ advanced: { bframes: 6 } }))
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await choose(wrapper, 'Frame types / GOP')
    expect(shownKeys(wrapper)).toEqual(['bframes'])
    await choose(wrapper, 'Rate control')
    expect(shownKeys(wrapper)).toEqual([])
    expect(wrapper.find('[data-state="none-changed"]').exists()).toBe(true)
    await choose(wrapper, '(custom)')
    expect(wrapper.findComponent(CustomParams).exists()).toBe(true)
    editor.set('/video/custom_params', '')
    await flushPromises()
    expect(wrapper.findComponent(CustomParams).exists()).toBe(false)
  })

  it('writes each committed number in one undo step, highlights and counts it, and resets it', async () => {
    const { wrapper, editor } = await mountPanel()
    await choose(wrapper, 'Frame types / GOP')
    control(wrapper, 'bframes', InputNumber).emit(5)
    control(wrapper, 'bframes', InputNumber).emit(6)
    await flushPromises()
    expect(editor.job?.video?.advanced).toEqual({ bframes: 6 })
    expect(row(wrapper, 'bframes').attributes('data-changed')).toBe('true')
    expect(count(wrapper, 'Frame types / GOP')).toBe('1')
    await row(wrapper, 'bframes').find('[data-action="reset"]').trigger('click')
    await flushPromises()
    expect(editor.job?.video?.advanced).toEqual({})
    expect(row(wrapper, 'bframes').attributes('data-changed')).toBe('false')
    expect(count(wrapper, 'Frame types / GOP')).toBe('0')
    editor.undo()
    expect(editor.job?.video?.advanced).toEqual({ bframes: 6 })
    editor.undo()
    expect(editor.job?.video?.advanced).toEqual({ bframes: 5 })
    editor.undo()
    expect(editor.job?.video?.advanced).toEqual({})
    expect(editor.canUndo).toBe(false)
  })

  it('removes an option whose field is emptied or set to the default choice', async () => {
    const { wrapper, editor } = await mountPanel(
      jobWith({ advanced: { bframes: 6, 'b-adapt': '0' } }),
    )
    await choose(wrapper, 'Frame types / GOP')
    control(wrapper, 'bframes', InputNumber).emit(null)
    await flushPromises()
    expect(editor.job?.video?.advanced).toEqual({ 'b-adapt': '0' })
    const select = control(wrapper, 'b-adapt', Select)
    const options = select.prop('options') as { value: string; label: string }[]
    expect(options[0]?.label).toBe('Default: Full (preset Slow)')
    select.emit(options[0]?.value)
    await flushPromises()
    expect(editor.job?.video?.advanced).toEqual({})
    select.emit('1')
    await flushPromises()
    expect(editor.job?.video?.advanced).toEqual({ 'b-adapt': '1' })
  })

  it('shows a switch at its default and stores the other value', async () => {
    const { wrapper, editor } = await mountPanel()
    await choose(wrapper, 'Frame types / GOP')
    const toggle = control(wrapper, 'b-intra', ToggleSwitch)
    // Off at preset slow.
    expect(toggle.prop('modelValue')).toBe(false)
    expect(row(wrapper, 'b-intra').find('[data-role="default"]').text()).toBe(
      'default: off (preset Slow)',
    )
    toggle.emit(true)
    await flushPromises()
    expect(editor.job?.video?.advanced).toEqual({ 'b-intra': true })
    expect(control(wrapper, 'b-intra', ToggleSwitch).prop('modelValue')).toBe(true)
    // On at preset slower: switching it off stores `false`.
    editor.patch([
      { op: 'remove', path: '/video/advanced/b-intra' },
      { op: 'replace', path: '/video/preset', value: 'slower' },
    ])
    await flushPromises()
    expect(control(wrapper, 'b-intra', ToggleSwitch).prop('modelValue')).toBe(true)
    control(wrapper, 'b-intra', ToggleSwitch).emit(false)
    await flushPromises()
    expect(editor.job?.video?.advanced).toEqual({ 'b-intra': false })
  })

  it('makes one undo step of a typing run in a text option', async () => {
    const { wrapper, editor } = await mountPanel()
    await choose(wrapper, 'Performance')
    const field = control(wrapper, 'pools', InputText)
    for (const text of ['1', '12', '12,']) field.emit(text)
    await row(wrapper, 'pools').find('input').trigger('blur')
    expect(editor.job?.video?.advanced).toEqual({ pools: '12,' })
    editor.undo()
    expect(editor.job?.video?.advanced).toEqual({})
  })

  it('shows the default as placeholder text that follows the speed preset', async () => {
    const { wrapper, editor } = await mountPanel()
    await choose(wrapper, 'Frame types / GOP')
    const placeholder = () => row(wrapper, 'bframes').find('input').attributes('placeholder')
    expect(placeholder()).toBe('4 frames (preset Slow)')
    editor.set('/video/preset', 'slower')
    await flushPromises()
    expect(placeholder()).toBe('8 frames (preset Slower)')
    expect(row(wrapper, 'min-keyint').find('input').attributes('placeholder')).toBe(
      'the encoder decides (auto, from the frame rate)',
    )
  })

  it('turns every option control off for passthrough', async () => {
    const { wrapper } = await mountPanel(
      jobWith({ passthrough: true, advanced: { bframes: 6, pools: '2' } }),
    )
    await choose(wrapper, 'Frame types / GOP')
    expect(control(wrapper, 'bframes', InputNumber).prop('disabled')).toBe(true)
    expect(control(wrapper, 'b-adapt', Select).prop('disabled')).toBe(true)
    expect(control(wrapper, 'b-intra', ToggleSwitch).prop('disabled')).toBe(true)
    expect(row(wrapper, 'bframes').find('[data-action="reset"]').attributes()).toHaveProperty(
      'disabled',
    )
    await choose(wrapper, 'Performance')
    expect(control(wrapper, 'pools', InputText).prop('disabled')).toBe(true)
  })

  it('shows a revealed option in its category, without the search or filter that hid it', async () => {
    const { wrapper } = await mountPanel()
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await search(wrapper, 'pools')
    await vi.waitFor(() => expect(shownKeys(wrapper)).toEqual([]), SOON)
    useUiStore().reveal('video.advanced.psy-rd')
    await flushPromises()
    expect(wrapper.find('[data-role="search"]').element).toHaveProperty('value', '')
    expect(wrapper.find('input[type="checkbox"]').element).toHaveProperty('checked', false)
    expect(wrapper.find('[aria-current="true"]').text()).toBe('Psycho-visual')
    expect(shownKeys(wrapper)).toEqual(['psy-rd'])
    useUiStore().reveal('video.custom_params')
    await flushPromises()
    expect(wrapper.find('[aria-current="true"]').text()).toBe('Custom parameters')
    expect(wrapper.findComponent(CustomParams).exists()).toBe(true)
  })

  it('keeps a search that shows the revealed option', async () => {
    const { wrapper } = await mountPanel()
    await search(wrapper, 'psy')
    await vi.waitFor(() => expect(shownKeys(wrapper)).toEqual(['psy-rd']), SOON)
    useUiStore().reveal('video.advanced.psy-rd')
    await flushPromises()
    expect(wrapper.find('[data-role="search"]').element).toHaveProperty('value', 'psy')
  })

  it('shows a key the encoder does not define, and removes it on reset', async () => {
    const { wrapper, editor } = await mountPanel(jobWith({ advanced: { nosuch: 1, bframes: 6 } }))
    const unknown = wrapper.find('[data-role="unknown"]')
    expect(unknown.find('[data-path="video.advanced.nosuch"]').text()).toContain('1')
    await unknown.find('[data-action="reset"]').trigger('click')
    expect(editor.job?.video?.advanced).toEqual({ bframes: 6 })
    expect(wrapper.find('[data-role="unknown"]').exists()).toBe(false)
  })

  it('offers Copy HDR metadata in the HDR / colour category only', async () => {
    const { wrapper } = await mountPanel()
    expect(wrapper.findComponent(CopyHdrMetadata).exists()).toBe(false)
    await choose(wrapper, 'HDR / colour')
    expect(wrapper.findComponent(CopyHdrMetadata).exists()).toBe(true)
    expect(shownKeys(wrapper)).toEqual(['master-display'])
  })
})

describe('a number option', () => {
  it('keeps every decimal entered, whatever its step', async () => {
    const { wrapper, editor } = await mountPanel()
    await choose(wrapper, 'Psycho-visual')
    const input = row(wrapper, 'psy-rd').find('input')
    ;(input.element as HTMLInputElement).focus()
    const paste = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(paste, 'clipboardData', { value: { getData: () => '1.75' } })
    input.element.dispatchEvent(paste)
    await input.trigger('keydown', { key: 'Enter', code: 'Enter' })
    expect(editor.job?.video?.advanced).toEqual({ 'psy-rd': 1.75 })
  })

  it('shows a stored value with all its decimals', async () => {
    const { wrapper } = await mountPanel(jobWith({ advanced: { 'psy-rd': 1.75 } }))
    await choose(wrapper, 'Psycho-visual')
    expect(row(wrapper, 'psy-rd').find('input').element).toHaveProperty('value', '1.75')
  })

  it('writes nothing when the focus passes through without a change', async () => {
    const { wrapper, editor } = await mountPanel(jobWith({ advanced: { bframes: 99 } }))
    await choose(wrapper, 'Frame types / GOP')
    const input = row(wrapper, 'bframes').find('input')
    ;(input.element as HTMLInputElement).focus()
    await input.trigger('keydown', { key: 'Tab', code: 'Tab' })
    await input.trigger('blur')
    ;(input.element as HTMLInputElement).focus()
    await input.trigger('keydown', { key: 'Enter', code: 'Enter' })
    await flushPromises()
    expect(editor.job?.video?.advanced).toEqual({ bframes: 99 })
    expect(editor.canUndo).toBe(false)
    expect(input.element).toHaveProperty('value', '99 frames')
  })
})

describe('the focus', () => {
  it('stays in the panel when a reset under "Show only changed" takes its row away', async () => {
    const { wrapper } = await mountPanel(jobWith({ advanced: { bframes: 6 } }))
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await choose(wrapper, 'Frame types / GOP')
    const reset = row(wrapper, 'bframes').find<HTMLButtonElement>('[data-action="reset"]')
    reset.element.focus()
    await reset.trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.find('[aria-current="true"]').element)
  })

  it('stays in the panel when an emptied text field under "Show only changed" goes', async () => {
    const { wrapper } = await mountPanel(jobWith({ advanced: { pools: '4' } }))
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await choose(wrapper, 'Performance')
    const text = row(wrapper, 'pools').findComponent(InputText)
    ;(text.element as HTMLInputElement).focus()
    // Chromium blurs a focused element as it is removed (jsdom does not); the field's blur
    // handler then runs in the middle of the panel's update.
    const original = Node.prototype.removeChild
    const removeChild = vi.spyOn(Node.prototype, 'removeChild').mockImplementation(function <
      T extends Node,
    >(this: Node, child: T): T {
      if (child.contains(document.activeElement)) (document.activeElement as HTMLElement).blur()
      return original.call(this, child) as T
    })
    try {
      text.vm.$emit('update:modelValue', '')
      await flushPromises()
    } finally {
      removeChild.mockRestore()
    }
    expect(document.activeElement).toBe(wrapper.find('[aria-current="true"]').element)
  })

  it('goes to the search when a reset takes a search result away', async () => {
    const { wrapper } = await mountPanel(jobWith({ advanced: { bframes: 6 } }))
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await search(wrapper, 'bfr')
    await vi.waitFor(() => expect(shownKeys(wrapper)).toEqual(['bframes']), SOON)
    const reset = row(wrapper, 'bframes').find<HTMLButtonElement>('[data-action="reset"]')
    reset.element.focus()
    await reset.trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.find('[data-role="search"]').element)
  })
})

function status(wrapper: VueWrapper): string {
  return wrapper.find('[data-role="search-status"]').text()
}

describe('the search status', () => {
  it('counts the custom parameters field when it is the match', async () => {
    const { wrapper } = await mountPanel()
    await search(wrapper, 'custom')
    await vi.waitFor(() => expect(status(wrapper)).toBe('1 option matches'), SOON)
    expect(wrapper.find('[data-state="no-match"]').exists()).toBe(false)
  })

  it('says that the matches are not changed when "Show only changed" hides them', async () => {
    const { wrapper } = await mountPanel()
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await search(wrapper, 'psy')
    await vi.waitFor(() => expect(status(wrapper)).toBe('1 option matches'), SOON)
    expect(wrapper.find('[data-state="no-match"]').exists()).toBe(false)
    expect(wrapper.find('[data-state="none-changed"]').text()).toBe(
      'No matching option is changed.',
    )
  })
})

describe('the panel', () => {
  it('keeps its category, search and "Show only changed" when it is mounted again', async () => {
    const { wrapper, pinia } = await mountPanel()
    await choose(wrapper, 'Performance')
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await search(wrapper, 'psy')
    wrapper.unmount()
    mounted.splice(0)
    const { wrapper: again } = await mountShell(AdvancedOptions, { pinia })
    mounted.push(again)
    await flushPromises()
    expect(again.find('[data-role="search"]').element).toHaveProperty('value', 'psy')
    expect(again.find('input[type="checkbox"]').element).toHaveProperty('checked', true)
    await search(again, '')
    expect(again.find('[aria-current="true"]').text()).toBe('Performance')
  })

  it('does not repeat the custom parameters field label as a heading', async () => {
    const { wrapper } = await mountPanel()
    await choose(wrapper, '(custom)')
    expect(wrapper.findAll('h3').map((heading) => heading.text())).not.toContain(
      'Custom parameters',
    )
  })

  it("describes a changed option's control with its default", async () => {
    const { wrapper } = await mountPanel(jobWith({ advanced: { bframes: 6 } }))
    await choose(wrapper, 'Frame types / GOP')
    const described = row(wrapper, 'bframes').find('input').attributes('aria-describedby') ?? ''
    const line = row(wrapper, 'bframes').find('[data-role="default"]')
    expect(described.split(' ')).toContain(line.attributes('id'))
    expect(line.text()).toBe('default: 4 frames (preset Slow)')
  })
})
