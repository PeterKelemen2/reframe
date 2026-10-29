import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { deferred } from '@/api/testing/fakes'
import type { Fix, JsonPatchOp, ValidationIssue } from '@/api/types'
import { mountShell } from '@/components/shell/testing'
import { sampleJob, samplePreset } from '@/editor/testing/samples'
import { useValidationStore } from '@/stores/validation'

import EncoderBanner from './EncoderBanner.vue'
import { openJob, setUpVideo } from './testing'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

const FIX: Fix = {
  label: 'Use hevc_amf (closest match; quality CQ 22 → CQ 20, approximate)',
  target: 'job',
  patch: [
    { op: 'replace', path: '/video/encoder', value: 'hevc_amf' },
    { op: 'replace', path: '/video/rate_control/value', value: 20 },
    { op: 'replace', path: '/video/preset', value: null },
  ] as JsonPatchOp[],
}

function unavailable(fixes: Fix[] = [FIX]): ValidationIssue {
  return {
    severity: 'error',
    code: 'encoder.unavailable',
    path: 'video.encoder',
    message: 'hevc_nvenc (NVIDIA NVENC H.265) is not available: NVIDIA driver not found.',
    fixes,
  }
}

/** The sample job with `hevc_nvenc`; `fromPreset`: the preset has it too. */
async function mountBanner(options: { fromPreset?: boolean; issues?: ValidationIssue[] } = {}) {
  const job = sampleJob()
  job.video!.encoder = 'hevc_nvenc'
  const setup = setUpVideo({ job })
  if (options.fromPreset) {
    const preset = samplePreset()
    preset.video!.encoder = 'hevc_nvenc'
    preset.name = 'H.265 NVENC 1080p'
    setup.server.on(`GET /api/presets/${job.preset_id}`, preset)
  }
  await openJob()
  useValidationStore().issues = options.issues ?? [unavailable()]
  const { wrapper } = await mountShell(EncoderBanner, { pinia: setup.pinia })
  mounted.push(wrapper)
  return { ...setup, wrapper }
}

describe('the missing-encoder banner', () => {
  it("names the preset, the encoder and the detection's reason", async () => {
    const { wrapper } = await mountBanner({ fromPreset: true })
    expect(wrapper.find('.encoder-banner__message').text()).toBe(
      'Preset H.265 NVENC 1080p uses hevc_nvenc, which is not available: NVIDIA driver not found',
    )
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  })

  it('speaks of the job once its encoder is not the preset one', async () => {
    const { wrapper } = await mountBanner()
    expect(wrapper.find('.encoder-banner__message').text()).toBe(
      'This job uses hevc_nvenc, which is not available: NVIDIA driver not found',
    )
  })

  it('shows the issue message when detection gave no reason', async () => {
    const { wrapper, system } = await mountBanner()
    const encoders = { ...system.capabilities!.encoders }
    encoders.hevc_nvenc = { ...encoders.hevc_nvenc!, reason: null }
    system.capabilities = { ...system.capabilities!, encoders }
    await flushPromises()
    expect(wrapper.find('.encoder-banner__message').text()).toBe(unavailable().message)
  })

  it('is not shown for other encoder issues', async () => {
    const untested = { ...unavailable([]), code: 'encoder.untested', severity: 'warning' as const }
    const { wrapper } = await mountBanner({ issues: [untested] })
    expect(wrapper.find('.encoder-banner').exists()).toBe(false)
  })

  it("applies the issue's fix as one undo step", async () => {
    const { wrapper, editor } = await mountBanner()
    const before = JSON.stringify(editor.job)
    const button = wrapper.find('.encoder-banner__fix')
    expect(button.text()).toBe(FIX.label)
    await button.trigger('click')
    await flushPromises()
    expect(editor.job?.video).toMatchObject({
      encoder: 'hevc_amf',
      rate_control: { value: 20 },
      preset: null,
    })
    editor.undo()
    expect(JSON.stringify(editor.job)).toBe(before)
  })

  it('asks the picker to open with Choose encoder', async () => {
    const { wrapper } = await mountBanner()
    await wrapper.find('.encoder-banner__choose').trigger('click')
    expect(wrapper.emitted('choose')).toHaveLength(1)
  })

  it('detects the encoders again with Check again, busy until it ends', async () => {
    const { wrapper, system } = await mountBanner()
    const rescan = deferred()
    system.rescanEncoders = vi.fn<() => Promise<void>>(() => rescan.promise)
    await wrapper.find('.encoder-banner__check').trigger('click')
    expect(system.rescanEncoders).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.encoder-banner__check').attributes('disabled')).toBeDefined()
    rescan.resolve()
    await flushPromises()
    expect(wrapper.find('.encoder-banner__check').attributes('disabled')).toBeUndefined()
  })
})
