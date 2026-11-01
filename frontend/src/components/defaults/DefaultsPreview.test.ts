import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { TrackDecision, TrackDraft, ValidationIssue } from '@/api/types'
import { mountShell } from '@/components/shell/testing'
import { probedSource, trackDefinitions } from '@/components/tracks/testing'
import { useDefaultsStore } from '@/stores/defaults'
import { useEditorStore } from '@/stores/editor'
import { useScansStore } from '@/stores/scans'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'
import { sampleJob } from '@/editor/testing/samples'

import DefaultsPreview from './DefaultsPreview.vue'
import { completeAudio, completeSubtitles } from './model'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

function decision(overrides: Partial<TrackDecision>): TrackDecision {
  return {
    source_stream: 1,
    kind: 'audio',
    selected: true,
    selection: 'Hungarian: the first matching track',
    reason: 'Lossless source → encode at the max',
    measure: false,
    ...overrides,
  }
}

function issue(path: string, code: string): ValidationIssue {
  return { severity: 'warning', code, path, message: code, fixes: [] }
}

async function mountPreview(draft: TrackDraft | null, withSource = true): Promise<void> {
  const { wrapper } = await mountShell(DefaultsPreview, {
    setup: () => {
      useSystemStore().definitions = trackDefinitions()
      if (withSource) {
        useSourcesStore().entries = [
          { id: 'movie', path: '/media/dts-hd-ma.mkv', source: probedSource('dts-hd-ma') },
        ]
        useEditorStore().target = { kind: 'job', sourceId: 'movie', job: sampleJob() }
      }
      const defaults = useDefaultsStore()
      defaults.audio = completeAudio(undefined)
      defaults.subtitles = completeSubtitles(undefined)
      defaults.preview = draft
    },
  })
  mounted.push(wrapper)
}

const rows = () =>
  [...document.querySelectorAll<HTMLTableRowElement>('[data-role="preview"] tbody tr')].map((row) =>
    [...row.cells].map((cell) => cell.textContent?.replace(/\s+/g, ' ').trim()),
  )

describe('the live preview', () => {
  it('has one row per source track: taken or dropped and why, the rule, the output, the reason', async () => {
    await mountPreview({
      audio: [],
      subtitles: [],
      subtitle_decisions: [],
      issues: [],
      decisions: [
        decision({
          rule: 1,
          outputs: [
            {
              action: 'encode',
              encoder: 'ac3',
              mixdown: '5.1',
              bitrate: 320,
              gain: 0,
              drc: 0,
              loudness: 'off',
            },
          ],
        }),
        decision({
          source_stream: 3,
          selected: false,
          selection: 'English: dropped',
          reason: 'English: dropped',
        }),
      ],
    })
    expect(rows()).toEqual([
      [
        '1 · hun · DTS-HD MA 5.1 · DTS-HD MA 5.1 stream #1',
        'Taken Hungarian: the first matching track',
        '1',
        'AC-3 5.1 · 320 kb/s',
        'Lossless source → encode at the max',
      ],
      [
        '3 · eng · AC-3 2.0 · English Stereo stream #3',
        'Dropped English: dropped',
        '—',
        '—',
        'English: dropped',
      ],
    ])
  })

  it('offers Measure where the unknown bitrate decided the outcome, for that track', async () => {
    await mountPreview({
      audio: [],
      subtitles: [],
      subtitle_decisions: [],
      issues: [],
      decisions: [decision({ source_stream: 1, measure: true }), decision({ source_stream: 2 })],
    })
    const scans = useScansStore()
    const measure = vi.spyOn(scans, 'measureBitrate').mockResolvedValue()
    const buttons = document.querySelectorAll<HTMLButtonElement>('[data-action="start-scan"]')
    expect(buttons).toHaveLength(1)
    buttons[0]!.click()
    await flushPromises()
    expect(measure).toHaveBeenCalledWith('movie', 1)
  })

  it('lists only the issues that no rule or field shows, and counts them all', async () => {
    await mountPreview({
      audio: [],
      subtitles: [],
      decisions: [decision({})],
      subtitle_decisions: [],
      issues: [
        issue('audio_defaults.codec_rules[0]', 'defaults.rule_shadowed'),
        issue('audio_defaults', 'defaults.somewhere'),
        issue('subtitle_defaults.burn_in', 'defaults.other_kind'),
      ],
    })
    useDefaultsStore().previewKeys = [5]
    await flushPromises()
    const listed = [...document.querySelectorAll('.defaults-preview__issues [data-code]')]
    expect(listed.map((item) => item.getAttribute('data-code'))).toEqual(['defaults.somewhere'])
    expect(document.querySelector('[data-role="issue-counts"]')?.textContent?.trim()).toBe(
      '2 warnings',
    )
  })

  it('says why there is nothing to preview without an open source', async () => {
    await mountPreview(null, false)
    expect(document.querySelector('[data-state="no-source"]')?.textContent).toContain(
      'Open a source file',
    )
  })
})
