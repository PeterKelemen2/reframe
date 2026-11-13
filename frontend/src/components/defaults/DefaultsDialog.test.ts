import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { FakeServer, json } from '@/api/testing/fakes'
import type { Preset } from '@/api/types'
import { languages } from '@/components/language/testing'
import { preset, presetList, userPreset } from '@/components/presets/testing'
import { mountShell } from '@/components/shell/testing'
import { trackDefinitions } from '@/components/tracks/testing'
import { sampleDraft, sampleJob } from '@/editor/testing/samples'
import { useDefaultsStore } from '@/stores/defaults'
import { useEditorStore } from '@/stores/editor'
import { templateOfPreset } from '@/stores/presets'
import { useSourcesStore } from '@/stores/sources'
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
    .on(`GET /api/presets/${MINE}`, () => userPreset(MINE, 'Mine'))
    .on(`PUT /api/presets/${MINE}`, (request) => request.body as Preset)
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function openDialog(
  whose: 'job' | 'preset',
  presetId: string,
  kind: 'audio' | 'subtitles' = 'audio',
): Promise<void> {
  const { wrapper } = await mountShell(DefaultsDialog, {
    setup: () => {
      useSystemStore().definitions = trackDefinitions()
      useSystemStore().languages = languages()
    },
  })
  mounted.push(wrapper)
  if (whose === 'job') await useEditorStore().open('movie', presetId)
  await useDefaultsStore().open(
    kind,
    whose === 'job' ? { kind: 'job' } : { kind: 'preset', presetId },
  )
  await flushPromises()
}

/** The text of the read-only value at `selector` (on it, or in it). */
function shown(selector: string): string | undefined {
  return document
    .querySelector(
      `[data-role="edit"] :is(${selector} [data-role="shown-value"], ${selector}[data-role="shown-value"])`,
    )
    ?.textContent?.trim()
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

  it('closes on Escape on a closed drop-down; on an open one, Escape closes only its list', async () => {
    await openDialog('job', MINE)
    const select = document.querySelector<HTMLElement>(
      '.defaults-dialog [data-field="tie_break"] [role="combobox"]',
    )!
    document.querySelector<HTMLElement>('.defaults-dialog [data-field="tie_break"]')!.click()
    await flushPromises()
    expect(select.getAttribute('aria-expanded')).toBe('true')
    escape(select)
    await vi.waitFor(() => expect(document.querySelector('.p-select-option')).toBeNull())
    expect(useDefaultsStore().visible).toBe(true)
    select.focus()
    escape(select)
    await flushPromises()
    expect(useDefaultsStore().visible).toBe(false)
  })

  it('offers a job with a built-in preset Apply and Save as new preset…', async () => {
    await openDialog('job', BUILT_IN)
    expect(footer()).toEqual(['cancel', 'save-as-new', 'apply'])
  })

  it("edits a group's defaults with Apply only, and says that Apply replaces the group's rules", async () => {
    const { wrapper } = await mountShell(DefaultsDialog, {
      setup: () => {
        useSystemStore().definitions = trackDefinitions()
        useSystemStore().languages = languages()
        const sources = useSourcesStore()
        sources.entries = [{ id: 'e1', path: '/media/e1.mkv', source: null }]
        sources.grouping = {
          groups: [
            {
              id: 'g1',
              name: 'Show S01',
              level: 'standard',
              representative: '/media/e1.mkv',
              fingerprint: { level: 'standard', tracks: [], digest: 'd' },
              members: [{ path: '/media/e1.mkv', match: 'exact', episode: 1 }],
            },
          ],
        }
      },
    })
    mounted.push(wrapper)
    useEditorStore().target = {
      kind: 'group',
      groupId: 'g1',
      sourceId: 'e1',
      job: sampleJob(),
      template: {
        ...templateOfPreset(userPreset(MINE, 'Mine')),
        audio_rules: [{ selector: { kind: 'audio', languages: ['jpn'] } }] as Preset['audio_rules'],
      },
      presetId: MINE,
      overrides: {},
      scope: 'group',
    }
    await useDefaultsStore().open('audio', { kind: 'group', groupId: 'g1' })
    await flushPromises()
    expect(footer()).toEqual(['cancel', 'apply'])
    expect(action('apply').textContent).toContain('Apply to the group')
    expect(document.querySelector('.defaults-dialog .p-dialog-title')?.textContent).toBe(
      'Audio defaults · Show S01',
    )
    expect(document.querySelector('[data-role="ruled"]')?.textContent).toContain(
      'Apply removes them',
    )
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
    expect(shown('[data-field="allowed"]')).toBe('None')
  })

  it("shows a built-in preset's audio values as whole text, not as faded disabled controls", async () => {
    const builtIn = preset(BUILT_IN, 'H.265 MKV 1080p')
    builtIn.audio_defaults = {
      ...builtIn.audio_defaults,
      selection: { ...builtIn.audio_defaults!.selection!, languages: ['hu', 'en'] },
      codec_rules: [
        {
          languages: ['hu', 'en'],
          source_channels: '5.1_or_more',
          codec: 'ac3',
          mixdown: '5.1',
          extras: {
            samplerate: 48000,
            gain: -3,
            drc: 2,
            loudness: 'ebu_r128',
            name_template: '{lang_native} {channels}',
            first_track_of_language_only: true,
            extra_outputs: [
              { codec: 'aac', mixdown: 'stereo', bitrate: null },
              { codec: 'ac3', mixdown: '5.1', bitrate: 448 },
            ],
          },
        },
        ...builtIn.audio_defaults!.codec_rules!,
      ],
      passthru: { allowed: ['ac3', 'eac3'], fallback_encoder: 'aac' },
    } as Preset['audio_defaults']
    server.on('GET /api/presets', presetList([builtIn, userPreset(MINE, 'Mine')]))
    await openDialog('preset', BUILT_IN)
    const edit = document.querySelector('[data-role="edit"]')!
    expect(edit.querySelectorAll('input:disabled, .p-disabled, button:disabled')).toHaveLength(0)
    expect(shown('[data-path="audio_defaults.selection.languages"]')).toBe('Hungarian, English')
    expect(shown('[data-field="undetermined"]')).toBe('Treat as another language')
    expect(shown('[data-field="no_match"]')).toBe('Take the default-flagged track')
    expect(shown('tbody[data-index="0"] [data-field="language"]')).toBe('Hungarian, English')
    expect(shown('tbody[data-index="0"] [data-field="channels"]')).toBe('5.1 or more')
    expect(shown('tbody[data-index="0"] [data-field="max_bitrate"]')).toBe('None')
    expect(shown('tbody[data-index="1"] [data-field="codec"]')).toBe('AAC')
    expect(shown('tbody[data-index="1"] [data-field="mixdown"]')).toBe('Stereo')
    expect(shown('tbody[data-index="1"] [data-field="max_bitrate"]')).toBe('160 kb/s')
    expect(shown('tbody[data-index="1"] [data-field="if_fits"]')).toBe('Passthru')
    expect(shown('[data-field="allowed"]')).toBe('AC-3, E-AC-3')
    expect(shown('[data-field="fallback"]')).toBe('AAC')
    expect(edit.querySelector('[data-action="add-rule"], [data-action="remove"]')).toBeNull()
    for (const index of ['0', '1']) {
      document
        .querySelector<HTMLButtonElement>(`tbody[data-index="${index}"] [data-action="expand"]`)!
        .click()
    }
    await flushPromises()
    const extras = (index: string) =>
      [
        ...edit.querySelectorAll(
          `tbody[data-index="${index}"] [data-rule-extras] .rule-extras__pair`,
        ),
      ].map((pair) => {
        const values = [...pair.querySelectorAll('[data-role="shown-value"]')]
        const text = values.map((value) => value.textContent?.trim()).join(' | ')
        return `${pair.querySelector('dt')?.textContent?.trim()}: ${text}`
      })
    expect(extras('0')).toEqual([
      'Languages of rule 1: Hungarian, English',
      'Sample rate: 48 kHz',
      'Gain: -3 dB',
      'Dynamic range compression: 2',
      'Normalise loudness: EBU R128 (−23 LUFS)',
      'Track name: {lang_native} {channels}',
      'Only for the first track of this language: Yes',
      'Extra outputs: AAC, Stereo, Encoder default | AC-3, 5.1, 448 kb/s',
    ])
    // The catch-all takes any language; its settings are the model's defaults.
    expect(extras('1')).toEqual([
      'Sample rate: Same as source',
      'Gain: 0 dB',
      'Dynamic range compression: Off',
      'Normalise loudness: Off',
      "Track name: The source track's name",
      'Only for the first track of this language: No',
      'Extra outputs: None',
    ])
  })

  // Only English ships; a German locale shows the values that `String` would write the English
  // way.
  it("writes a built-in preset's numbers in the app's locale", async () => {
    const builtIn = preset(BUILT_IN, 'H.265 MKV 1080p')
    const rules = builtIn.audio_defaults!.codec_rules!
    builtIn.audio_defaults = {
      ...builtIn.audio_defaults,
      codec_rules: [
        {
          ...rules[0]!,
          max_bitrate: 1536,
          extras: {
            samplerate: 44100,
            gain: -1.5,
            drc: 2.5,
            extra_outputs: [{ codec: 'ac3', mixdown: '5.1', bitrate: 1536 }],
          },
        },
        ...rules.slice(1),
      ],
    } as Preset['audio_defaults']
    server.on('GET /api/presets', presetList([builtIn, userPreset(MINE, 'Mine')]))
    await openDialog('preset', BUILT_IN)
    ;(mounted[0]!.vm as unknown as { $i18n: { locale: string } }).$i18n.locale = 'de'
    document
      .querySelector<HTMLButtonElement>('tbody[data-index="0"] [data-action="expand"]')!
      .click()
    await flushPromises()
    expect(shown('tbody[data-index="0"] [data-field="max_bitrate"]')).toBe('1.536 kb/s')
    const pairs = [
      ...document.querySelectorAll('tbody[data-index="0"] [data-rule-extras] .rule-extras__pair'),
    ].map((pair) => pair.querySelector('[data-role="shown-value"]')?.textContent?.trim())
    expect(pairs).toEqual(expect.arrayContaining(['44,1 kHz', '-1,5 dB', '2,5']))
    expect(pairs.at(-1)).toBe('AC-3, 5.1, 1.536 kb/s')
  })

  it("shows a built-in preset's subtitle values as text", async () => {
    await openDialog('preset', BUILT_IN, 'subtitles')
    expect(document.querySelectorAll('[data-role="edit"] :is(input, .p-select)')).toHaveLength(0)
    expect(shown('[data-path="subtitle_defaults.selection.languages"]')).toBe(
      'The preferred subtitle languages of Settings → Languages',
    )
    expect(shown('[data-field="foreign_audio_search"]')).toBe('On')
    expect(shown('[data-field="burn_in"]')).toBe('None')
  })

  it("says when the preset's own track rules of this kind decide the tracks instead", async () => {
    await openDialog('job', MINE)
    expect(document.querySelector('[data-role="ruled"]')).toBeNull()
    for (const wrapper of mounted.splice(0)) wrapper.unmount()
    document.body.replaceChildren()
    server.on(
      'GET /api/presets',
      presetList([
        preset(BUILT_IN, 'H.265 MKV 1080p'),
        userPreset(MINE, 'Mine', {
          audio_rules: [
            {
              selector: { kind: 'audio', nth: 0, sort: 'source_order' },
              multiple: true,
              required: true,
              settings: { kind: 'audio', action: 'passthru', encoder: null },
            },
          ] as Preset['audio_rules'],
        }),
      ]),
    )
    await openDialog('job', MINE)
    expect(document.querySelector('[data-role="ruled"]')?.textContent).toContain(
      '“Mine” has its own audio track rules',
    )
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
