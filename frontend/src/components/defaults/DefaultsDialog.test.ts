import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { configureClient } from '@/api/client'
import { FakeServer, json } from '@/api/testing/fakes'
import type { Preset } from '@/api/types'
import { preset, presetList, userPreset } from '@/components/presets/testing'
import { mountShell } from '@/components/shell/testing'
import { trackDefinitions } from '@/components/tracks/testing'
import { sampleDraft, sampleJob } from '@/editor/testing/samples'
import { useDefaultsStore } from '@/stores/defaults'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'

import DefaultsDialog from './DefaultsDialog.vue'

const BUILT_IN = 'h265-mkv-1080p'
const MINE = 'mine'

const mounted: VueWrapper[] = []
let server: FakeServer

beforeEach(() => {
  server = new FakeServer()
    .on(
      'GET /api/presets',
      presetList([preset(BUILT_IN, 'H.265 MKV 1080p'), userPreset(MINE, 'Mine')]),
    )
    .on('POST /api/jobs/draft', (request) => {
      const job = sampleJob()
      job.preset_id = (request.body as { preset_id: string }).preset_id
      return sampleDraft(job)
    })
    .on('POST /api/presets/diff', [])
    .on('POST /api/presets/defaults/preview', () => json([]))
    .on(`PUT /api/presets/${MINE}`, (request) => request.body as Preset)
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function openDialog(whose: 'job' | 'preset', presetId: string): Promise<void> {
  const { wrapper } = await mountShell(DefaultsDialog, {
    setup: () => {
      useSystemStore().definitions = trackDefinitions()
    },
  })
  mounted.push(wrapper)
  if (whose === 'job') await useEditorStore().open('movie', presetId)
  await useDefaultsStore().open(
    'audio',
    whose === 'job' ? { kind: 'job' } : { kind: 'preset', presetId },
  )
  await flushPromises()
}

const footer = () =>
  [...document.querySelectorAll<HTMLButtonElement>('.defaults-dialog__footer button')].map(
    (button) => button.dataset.action,
  )
const action = (name: string) =>
  document.querySelector<HTMLButtonElement>(`[data-action="${name}"]`)!
const puts = () => server.requests.filter((request) => request.method === 'PUT')

function escape(target: Element): void {
  target.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }),
  )
}

describe('the defaults dialog', () => {
  it('closes on Escape when the focus is on no control, unless a dialog of its own is above it', async () => {
    await openDialog('job', MINE)
    action('save-to-preset').click()
    await flushPromises()
    escape(document.body)
    await flushPromises()
    expect(useDefaultsStore().visible).toBe(true)
    for (const wrapper of mounted.splice(0)) wrapper.unmount()
    document.body.replaceChildren()
    await openDialog('job', MINE)
    escape(document.body)
    await flushPromises()
    expect(useDefaultsStore().visible).toBe(false)
  })

  it('offers a job with a built-in preset Apply and Save as new preset…', async () => {
    await openDialog('job', BUILT_IN)
    expect(footer()).toEqual(['cancel', 'save-as-new', 'apply'])
  })

  it("asks before it saves into the job's user preset, then saves into it", async () => {
    await openDialog('job', MINE)
    expect(footer()).toEqual(['cancel', 'save-to-preset', 'apply'])
    action('save-to-preset').click()
    await flushPromises()
    expect(puts()).toHaveLength(0)
    expect(document.querySelector('.defaults-confirm')?.textContent).toContain('“Mine”')
    action('confirm-save').click()
    await flushPromises()
    expect(puts().map((request) => request.path)).toEqual([`/api/presets/${MINE}`])
  })

  it("offers a user preset's defaults Save once they are edited", async () => {
    await openDialog('preset', MINE)
    expect(footer()).toEqual(['cancel', 'save'])
    expect(action('save').disabled).toBe(true)
    const defaults = useDefaultsStore()
    defaults.setAudio({
      ...defaults.audio!,
      passthru: { allowed: ['ac3'], fallback_encoder: 'aac' },
    })
    await flushPromises()
    expect(action('save').disabled).toBe(false)
  })

  it("shows a built-in preset's defaults with Close only", async () => {
    await openDialog('preset', BUILT_IN)
    expect(footer()).toEqual(['close'])
    expect(document.querySelector('[data-role="whose"]')?.textContent).toContain('read-only')
  })

  it('closes on Escape; in the confirmation, Escape closes only the confirmation', async () => {
    await openDialog('job', MINE)
    action('save-to-preset').click()
    await flushPromises()
    escape(document.querySelector('.defaults-confirm [data-action="confirm-save"]')!)
    await flushPromises()
    // jsdom runs no leave transition: the confirmation's mask is left leaving.
    const mask = document.querySelector('.defaults-confirm')?.closest('.p-dialog-mask')
    expect(mask?.classList.contains('p-overlay-mask-leave-active')).toBe(true)
    expect(useDefaultsStore().visible).toBe(true)
    escape(action('apply'))
    await flushPromises()
    expect(useDefaultsStore().visible).toBe(false)
    expect(useEditorStore().job?.audio).toEqual(sampleJob().audio)
  })
})
