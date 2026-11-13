import { flushPromises, type VueWrapper } from '@vue/test-utils'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import ToggleSwitch from 'primevue/toggleswitch'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { problem } from '@/api/testing/fakes'
import { mountBase } from '@/components/base/testing'
import type { ValidationIssue } from '@/api/types'
import { CHECK_DELAY } from '@/components/filters/useCustomCheck'
import FilterHelp from '@/components/filters/FilterHelp.vue'
import { filterCaps, filterDefinitions, openFilters } from '@/components/filters/testing'
import { mountShell } from '@/components/shell/testing'
import { hdr10Source, multitrackSource } from '@/components/summary/testing'
import { issue } from '@/editor/testing/samples'
import { useValidationStore } from '@/stores/validation'

import FiltersTab from './FiltersTab.vue'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  vi.useRealTimers()
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountTab(options: Parameters<typeof openFilters>[0] = {}) {
  const setup = await openFilters(options)
  const { wrapper } = await mountShell(FiltersTab, { pinia: setup.pinia })
  mounted.push(wrapper)
  await flushPromises()
  return { ...setup, wrapper }
}

function field(wrapper: VueWrapper, path: string) {
  return wrapper.find(`[data-path="${path}"]`)
}

/** The PrimeVue control of a field, with its props as plain values. */
function control(wrapper: VueWrapper, path: string, component: object) {
  const found = field(wrapper, path).findComponent(component as never) as unknown as VueWrapper
  return {
    prop: (name: string) => (found.props() as Record<string, unknown>)[name],
    emit: (value: unknown) => found.vm.$emit('update:modelValue', value),
  }
}

function text(wrapper: VueWrapper, selector: string): string {
  return wrapper.find(selector).text().replace(/\s+/g, ' ').trim()
}

async function typeCustom(wrapper: VueWrapper, value: string) {
  field(wrapper, 'filters.custom.custom')
    .findComponent(InputText)
    .vm.$emit('update:modelValue', value)
  await flushPromises()
}

const SPEED = { low: 'Low', medium: 'Medium', high: 'High' }

const washedOut: ValidationIssue = {
  severity: 'warning',
  code: 'filter.hdr_without_tonemap',
  path: 'filters.colorspace',
  message:
    'Colorspace converts HDR (PQ) to SDR without tone mapping: the picture will look washed out.',
  fixes: [
    {
      label: 'Enable tone mapping',
      patch: [{ op: 'add', path: '/filters/tonemap', value: { preset: 'default' } }],
      target: 'job',
    },
  ],
}

describe('the Filters tab', () => {
  it('lists the filters in the order they apply', async () => {
    const { wrapper } = await mountTab()
    const definitions = filterDefinitions()
    const ids = wrapper.findAll('[data-filter]').map((row) => row.attributes('data-filter'))
    expect(ids).toEqual(
      (definitions.filter_order ?? []).filter((id) => id in (definitions.filters ?? {})),
    )
  })

  it('shows every filter’s help from the definitions', () => {
    for (const filter of Object.values(filterDefinitions().filters ?? {})) {
      const help = mountBase(FilterHelp, { props: { filter } })
      mounted.push(help)
      const part = (name: string) => help.find(`[data-help-part="${name}"]`).text()
      expect(part('what')).toBe(filter.help.what)
      expect(part('use-when')).toBe(filter.help.use_when)
      expect(part('avoid-when')).toBe(filter.help.avoid_when)
      expect(part('speed-cost')).toBe(SPEED[filter.help.speed_cost])
      expect(part('settings')).toBe(filter.help.settings)
      const tunes = filter.implementations.flatMap((impl) => impl.tunes ?? [])
      const missing = tunes.filter((tune) => !help.text().includes(`${tune.label} · ${tune.help}`))
      expect(missing.filter((tune) => tune.help !== '')).toEqual([])
    }
  })

  it('shows the help of the filter whose row was clicked or has the focus', async () => {
    const { wrapper } = await mountTab()
    expect(wrapper.find('[data-help]').attributes('data-help')).toBe('detelecine')
    await wrapper.find('[data-filter="denoise"]').trigger('click')
    expect(wrapper.find('[data-help]').attributes('data-help')).toBe('denoise')
    await wrapper.find('[data-filter="sharpen"] input').trigger('focusin')
    expect(wrapper.find('[data-help]').attributes('data-help')).toBe('sharpen')
  })

  it('turns a filter on with its default preset and off again, one undo step each', async () => {
    const { wrapper, editor } = await mountTab({ filters: { deinterlace: { preset: 'bob' } } })
    control(wrapper, 'filters.denoise', ToggleSwitch).emit(true)
    expect(editor.job?.filters).toEqual({
      deinterlace: { preset: 'bob' },
      denoise: { preset: 'light' },
    })
    control(wrapper, 'filters.deinterlace', ToggleSwitch).emit(false)
    expect(editor.job?.filters).toEqual({ denoise: { preset: 'light' } })
    editor.undo()
    expect(editor.job?.filters?.deinterlace).toEqual({ preset: 'bob' })
    editor.undo()
    expect(editor.job?.filters).toEqual({ deinterlace: { preset: 'bob' } })
    expect(editor.canUndo).toBe(false)
  })

  it('changes the tune, preset and implementation, one undo step each', async () => {
    const { wrapper, editor } = await mountTab({ filters: { denoise: { preset: 'light' } } })
    control(wrapper, 'filters.denoise.tune', Select).emit('film')
    await flushPromises()
    control(wrapper, 'filters.denoise.preset', Select).emit('strong')
    await flushPromises()
    control(wrapper, 'filters.denoise.implementation', Select).emit('hqdn3d')
    await flushPromises()
    // HQDN3D has a Strong preset and no tunes.
    expect(editor.job?.filters?.denoise).toEqual({
      preset: 'strong',
      tune: null,
      custom: null,
      implementation: 'hqdn3d',
    })
    expect(field(wrapper, 'filters.denoise.tune').exists()).toBe(false)
    editor.undo()
    expect(editor.job?.filters?.denoise).toEqual({ preset: 'strong', tune: 'film' })
    editor.undo()
    expect(editor.job?.filters?.denoise).toEqual({ preset: 'light', tune: 'film' })
    editor.undo()
    expect(editor.job?.filters?.denoise).toEqual({ preset: 'light' })
  })

  it('takes the default preset of an implementation that lacks the chosen one', async () => {
    const { wrapper, editor } = await mountTab({
      filters: { deinterlace: { preset: 'skip-spatial', implementation: 'yadif' } },
    })
    control(wrapper, 'filters.deinterlace.implementation', Select).emit('bwdif')
    expect(editor.job?.filters?.deinterlace).toMatchObject({
      implementation: 'bwdif',
      preset: 'default',
    })
  })

  it('shows the preset’s own chain as the tune Default, a value Select can show', async () => {
    const { wrapper, editor } = await mountTab({ filters: { denoise: { preset: 'light' } } })
    const tune = () => control(wrapper, 'filters.denoise.tune', Select)
    const shown = () => {
      const options = tune().prop('options') as { id: string; label: string }[]
      return options.find((option) => option.id === tune().prop('modelValue'))
    }
    // Select shows its empty placeholder for `null` and `''`.
    expect(tune().prop('modelValue')).not.toBe('')
    expect(shown()?.label).toBe('Default')
    const none = shown()?.id
    tune().emit('film')
    await flushPromises()
    expect(editor.job?.filters?.denoise).toEqual({ preset: 'light', tune: 'film' })
    expect(shown()?.label).toBe('Film')
    tune().emit(none)
    expect(editor.job?.filters?.denoise).toEqual({ preset: 'light', tune: null })
  })

  it('drops the custom parameters with the custom preset', async () => {
    const { wrapper, editor } = await mountTab({
      filters: { sharpen: { preset: 'custom', custom: 'la=2' } },
    })
    expect(field(wrapper, 'filters.sharpen.custom').find('input').element.value).toBe('la=2')
    control(wrapper, 'filters.sharpen.preset', Select).emit('medium')
    await flushPromises()
    expect(editor.job?.filters?.sharpen).toEqual({ preset: 'medium', custom: null })
    expect(field(wrapper, 'filters.sharpen.custom').exists()).toBe(false)
  })

  it('shows an implementation the build cannot run, and it cannot be chosen', async () => {
    const caps = filterCaps({
      filters: ['zscale', 'tonemap', 'libplacebo', 'unsharp'],
      filter_failures: { libplacebo: 'No working Vulkan driver (VK_ERROR_INCOMPATIBLE_DRIVER)' },
      untested_filters: [],
    })
    const { wrapper } = await mountTab({
      caps,
      filters: { tonemap: { preset: 'default' }, sharpen: { preset: 'light' } },
    })
    const options = (path: string) =>
      control(wrapper, path, Select).prop('options') as {
        id: string
        text: string
        disabled: boolean
      }[]
    expect(options('filters.tonemap.implementation')).toEqual([
      {
        id: 'libplacebo',
        text: 'libplacebo (cannot run: No working Vulkan driver (VK_ERROR_INCOMPATIBLE_DRIVER))',
        disabled: true,
      },
      { id: 'zscale', text: 'zscale + tonemap', disabled: false },
    ])
    expect(options('filters.sharpen.implementation')[1]).toEqual({
      id: 'cas',
      text: 'CAS (cannot run: cas is not in this FFmpeg build)',
      disabled: true,
    })
    // With libplacebo out, the server runs zscale: that is the one shown.
    expect(control(wrapper, 'filters.tonemap.implementation', Select).prop('modelValue')).toBe(
      'zscale',
    )
  })

  it('shows an untested GPU implementation as one that can be chosen, and runs the CPU one', async () => {
    const { wrapper, editor } = await mountTab()
    control(wrapper, 'filters.tonemap', ToggleSwitch).emit(true)
    await flushPromises()
    expect(editor.job?.filters?.tonemap).toEqual({ preset: 'default' })
    const select = control(wrapper, 'filters.tonemap.implementation', Select)
    expect(select.prop('modelValue')).toBe('zscale')
    expect((select.prop('options') as { disabled: boolean; text: string }[])[0]).toEqual({
      id: 'libplacebo',
      text: 'libplacebo (needs Vulkan, not tested on this computer: the test runs with the hardware tests)',
      disabled: false,
    })
    select.emit('libplacebo')
    expect(editor.job?.filters?.tonemap).toMatchObject({
      implementation: 'libplacebo',
      preset: 'default',
    })
  })

  it('shows each validation issue at the field of its path', async () => {
    const { wrapper } = await mountTab({
      filters: { denoise: { preset: 'light', implementation: 'nlmeans' } },
    })
    useValidationStore().issues = [
      issue('filter.preset_unknown', 'filters.denoise.preset'),
      issue('filter.implementation_untested', 'filters.denoise.implementation', 'warning'),
      issue('filter.unknown', 'filters.denoise'),
    ]
    await flushPromises()
    expect(field(wrapper, 'filters.denoise.preset').text()).toContain('filter.preset_unknown')
    expect(field(wrapper, 'filters.denoise.implementation').text()).toContain(
      'filter.implementation_untested',
    )
    expect(field(wrapper, 'filters.denoise').find('.rf-field__issues').text()).toContain(
      'filter.unknown',
    )
  })

  it('turns every control off for video passthrough, with a note', async () => {
    const { wrapper } = await mountTab({
      passthrough: true,
      filters: { denoise: { preset: 'light' } },
    })
    expect(wrapper.find('[data-note="passthrough"]').exists()).toBe(true)
    expect(control(wrapper, 'filters.denoise', ToggleSwitch).prop('disabled')).toBe(true)
    expect(control(wrapper, 'filters.denoise.preset', Select).prop('disabled')).toBe(true)
  })

  it('keeps every row reachable by the keyboard for its help while the controls are off', async () => {
    const { wrapper } = await mountTab({ passthrough: true })
    const rows = wrapper.findAll('[data-filter]')
    expect(rows.map((row) => row.attributes('tabindex'))).toEqual(rows.map(() => '0'))
    ;(wrapper.find('[data-filter="sharpen"]').element as HTMLElement).focus()
    await flushPromises()
    expect(wrapper.find('[data-help]').attributes('data-help')).toBe('sharpen')
  })

  it('leaves the rows out of the tab order while their controls work', async () => {
    const { wrapper } = await mountTab()
    expect(wrapper.find('[data-filter="sharpen"]').attributes('tabindex')).toBeUndefined()
  })

  it('turns every control off for a file without video, and says so', async () => {
    const { wrapper } = await mountTab({ source: { ...multitrackSource(), video: [] } })
    expect(wrapper.find('[data-note="no-video"]').text()).toBe(
      'This file has no video: the filters do not apply.',
    )
    expect(wrapper.find('[data-note="passthrough"]').exists()).toBe(false)
    expect(control(wrapper, 'filters.denoise', ToggleSwitch).prop('disabled')).toBe(true)
    expect(text(wrapper, '.colour-box__empty')).toBe('This file has no video.')
  })
})

describe('the source colour box', () => {
  it('shows the colours, HDR format and mastering values of an HDR10 source', async () => {
    const { wrapper } = await mountTab({ source: hdr10Source() })
    const value = (key: string) => text(wrapper, `[data-colour="${key}"] dd`)
    expect(value('primaries')).toBe('BT.2020 (bt2020)')
    expect(value('transfer')).toBe('PQ (smpte2084)')
    expect(value('matrix')).toBe('bt2020nc')
    expect(value('range')).toBe('Limited (tv)')
    expect(value('bitDepth')).toBe('10-bit')
    expect(value('hdr')).toBe('HDR10')
    expect(value('mastering')).toBe(
      'R 0.68, 0.32 · G 0.265, 0.69 · B 0.15, 0.06 · WP 0.3127, 0.329',
    )
    expect(value('luminance')).toBe('0.0001–1,000 cd/m²')
    expect(value('contentLight')).toBe('1,000 / 400 cd/m²')
    expect(text(wrapper, '[data-colour-sentence]')).toBe(
      "Off: the output keeps the source's colours (BT.2020 PQ (HDR10)).",
    )
  })

  it('says HDR to SDR needs tone mapping and offers the server’s fix, one undo step', async () => {
    const { wrapper, editor } = await mountTab({
      source: hdr10Source(),
      filters: { colorspace: { preset: 'bt709' } },
    })
    useValidationStore().issues = [washedOut]
    await flushPromises()
    expect(text(wrapper, '[data-colour-sentence]')).toBe(
      'Converts BT.2020 PQ (HDR10) to BT.709 SDR. Without tone mapping, the picture will look washed out.→Enable tone mapping',
    )
    // Said once, in the sentence with its fix.
    expect(field(wrapper, 'filters.colorspace').find('.rf-field__issues').exists()).toBe(false)
    await wrapper.find('[data-colour-sentence] [data-action="fix"]').trigger('click')
    await flushPromises()
    expect(editor.job?.filters?.tonemap).toEqual({ preset: 'default' })
    useValidationStore().issues = []
    await flushPromises()
    expect(text(wrapper, '[data-colour-sentence]')).toBe(
      'Converts BT.2020 PQ (HDR10) to BT.709 SDR, with tone mapping.',
    )
    editor.undo()
    expect(editor.job?.filters?.tonemap).toBeUndefined()
  })

  it('moves the focus to the sentence when the fix button it pressed goes away', async () => {
    const { wrapper } = await mountTab({
      source: hdr10Source(),
      filters: { colorspace: { preset: 'bt709' } },
    })
    useValidationStore().issues = [washedOut]
    await flushPromises()
    const fix = wrapper.find('[data-colour-sentence] [data-action="fix"]')
    ;(fix.element as HTMLElement).focus()
    await fix.trigger('click')
    useValidationStore().issues = []
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.find('[data-colour-sentence]').element)
  })

  it('says plainly that an untagged source keeps its colours', async () => {
    const { wrapper } = await mountTab({ source: multitrackSource() })
    expect(text(wrapper, '[data-colour-sentence]')).toBe(
      "Off: the output keeps the source's colours.",
    )
  })

  it('says the colours are not known before the file is probed', async () => {
    const { wrapper } = await mountTab()
    expect(text(wrapper, '.colour-box__empty')).toBe(
      "The source's colours are known once the file is probed.",
    )
  })

  it('offers no fix while the server does not ask for tone mapping', async () => {
    const { wrapper } = await mountTab({
      source: hdr10Source(),
      filters: { colorspace: { preset: 'bt709' } },
    })
    expect(text(wrapper, '[data-colour-sentence]')).toBe(
      'Converts BT.2020 PQ (HDR10) to BT.709 SDR.',
    )
    expect(wrapper.find('[data-colour-sentence] [data-action="fix"]').exists()).toBe(false)
  })

  it('names what tone mapping alone and custom parameters do', async () => {
    const { wrapper, editor } = await mountTab({
      source: hdr10Source(),
      filters: { tonemap: { preset: 'default' } },
    })
    expect(text(wrapper, '[data-colour-sentence]')).toBe(
      'Tone mapping converts BT.2020 PQ (HDR10) to BT.709 SDR.',
    )
    editor.set('/filters/colorspace', { preset: 'custom', custom: 'p=bt709' })
    await flushPromises()
    expect(text(wrapper, '[data-colour-sentence]')).toBe(
      'Converts BT.2020 PQ (HDR10) with your parameters.',
    )
  })

  it('converts an untagged SDR source without calling it SDR to SDR', async () => {
    const { wrapper } = await mountTab({
      source: multitrackSource(),
      filters: { colorspace: { preset: 'bt601-6-625' } },
    })
    expect(text(wrapper, '[data-colour="primaries"] dd')).toBe('Not tagged')
    expect(text(wrapper, '[data-colour="hdr"] dd')).toBe('None (SDR)')
    expect(wrapper.find('[data-colour="mastering"]').exists()).toBe(false)
    expect(text(wrapper, '[data-colour-sentence]')).toBe(
      'Converts the untagged source colours to BT.601 EBU (PAL).',
    )
  })
})

describe('the custom filter check', () => {
  it('runs one dry run of the job once the typing stops, and shows FFmpeg’s refusal', async () => {
    vi.useFakeTimers()
    const { wrapper, server, editor } = await mountTab({
      filters: { custom: { preset: 'default' } },
    })
    server.on('POST /api/jobs/dry-run', [
      {
        severity: 'error',
        code: 'encoder.dry_run_failed',
        path: 'video.custom_params',
        message:
          "The test encode of one frame failed: Error applying option 'nosuch' to filter 'eq': Option not found",
      },
    ])
    await typeCustom(wrapper, 'eq=nosu')
    await typeCustom(wrapper, 'eq=nosuch=1')
    expect(text(wrapper, '[data-check]')).toBe('Checking with a one-frame test…')
    await vi.advanceTimersByTimeAsync(CHECK_DELAY - 1)
    expect(server.count('POST /api/jobs/dry-run')).toBe(0)
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()
    expect(server.count('POST /api/jobs/dry-run')).toBe(1)
    const sent = server.requests.find((request) => request.path === '/api/jobs/dry-run')?.body as {
      job: { filters: unknown }
    }
    expect(sent.job.filters).toEqual({ custom: { preset: 'default', custom: 'eq=nosuch=1' } })
    const shown = field(wrapper, 'filters.custom.custom')
    expect(shown.find('.rf-field__issues').text()).toContain("Error applying option 'nosuch'")
    expect(shown.classes()).toContain('rf-field--error')
    // The typing is one undo step.
    editor.undo()
    await flushPromises()
    expect(editor.job?.filters?.custom).toEqual({ preset: 'default' })
    expect(field(wrapper, 'filters.custom.custom').find('.rf-field__issues').exists()).toBe(false)
  })

  it('says FFmpeg accepts a filter it ran', async () => {
    vi.useFakeTimers()
    const { wrapper } = await mountTab({ filters: { custom: { preset: 'default' } } })
    await typeCustom(wrapper, 'hflip')
    await vi.advanceTimersByTimeAsync(CHECK_DELAY)
    await flushPromises()
    expect(text(wrapper, '[data-check]')).toBe('FFmpeg accepts it (one-frame test).')
  })

  it('shows a filter web mode does not allow as an error at the field', async () => {
    vi.useFakeTimers()
    const { wrapper, server } = await mountTab({ filters: { custom: { preset: 'default' } } })
    server.on('POST /api/jobs/dry-run', () =>
      problem(
        403,
        'filter.not_allowed',
        'The free filter text is not allowed',
        "filters.custom: the FFmpeg filter 'nosuchfilter' is not allowed",
      ),
    )
    await typeCustom(wrapper, 'nosuchfilter')
    await vi.advanceTimersByTimeAsync(CHECK_DELAY)
    await flushPromises()
    expect(field(wrapper, 'filters.custom.custom').find('.rf-field__issues').text()).toContain(
      "the FFmpeg filter 'nosuchfilter' is not allowed",
    )
  })

  it('checks nothing for an empty text', async () => {
    vi.useFakeTimers()
    const { wrapper, server } = await mountTab({
      filters: { custom: { preset: 'default', custom: 'hflip' } },
    })
    await typeCustom(wrapper, '')
    await vi.advanceTimersByTimeAsync(CHECK_DELAY)
    expect(server.count('POST /api/jobs/dry-run')).toBe(0)
    expect(wrapper.find('[data-check]').exists()).toBe(false)
  })
})
