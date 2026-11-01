import { describe, expect, it } from 'vitest'

import type { JobSettings, NamingOptions, Preset } from '@/api/types'

import { templateOf } from './template'
import { sampleJob, samplePreset } from './testing/samples'

const SETTINGS_NAMING = {
  movie_template: '{main_title}',
  episode_template: '{main_title}',
  name_source: 'auto',
  output_folder_mode: 'fixed',
  output_folder: '/output',
} as NamingOptions

function presetPart(preset: Preset): Record<string, unknown> {
  const { id: _id, name: _n, category: _c, description: _d, built_in: _b, ...template } = preset
  return template
}

function edited(change: (job: JobSettings) => void): JobSettings {
  const job = sampleJob()
  change(job)
  return job
}

describe('the template of a job', () => {
  it('is the preset itself for a job as the preset drafted it', () => {
    const preset = samplePreset()
    expect(templateOf(sampleJob(), preset, SETTINGS_NAMING)).toEqual(presetPart(preset))
  })

  it("takes the preset-level edits and leaves the job's own parts out", () => {
    const job = edited((j) => {
      Object.assign(j.output ?? {}, {
        container: 'mp4',
        path: '/elsewhere.mp4',
        edit_in_place: true,
      })
      Object.assign(j.video ?? {}, { encoder: 'libx264' })
      j.video!.metadata = { ...j.video!.metadata!, language: 'ja', name: 'Main' }
      j.filters = { denoise: { preset: 'light', tune: null, custom: null, implementation: null } }
      j.tags = { ...j.tags, title: '{title}' }
      j.chapters = { enabled: false, names: null, generate_every: 5 }
      j.audio = []
    })
    const preset = samplePreset()
    const template = templateOf(job, preset, SETTINGS_NAMING)
    expect(template.output).toEqual({ ...preset.output, container: 'mp4' })
    expect(template.video?.encoder).toBe('libx264')
    expect(template.video?.metadata).toEqual(preset.video?.metadata)
    expect(template.filters).toEqual(job.filters)
    expect(template.tags?.title).toBe('{title}')
    expect(template.chapters).toEqual({ enabled: false, generate_every: 5 })
    expect(template.audio_rules).toEqual(preset.audio_rules)
    expect(template.audio_defaults).toEqual(preset.audio_defaults)
    expect(template).not.toHaveProperty('id')
    expect(template).not.toHaveProperty('built_in')
  })
})

describe('the crop of the template', () => {
  it('fixes a manual crop for every file', () => {
    const rect = { top: 4, bottom: 4, left: 0, right: 0 }
    const job = edited((j) => {
      j.dimensions!.crop = { mode: 'manual', rect }
    })
    const template = templateOf(job, samplePreset(), null)
    expect(template.crop_policy).toBe('fixed')
    expect(template.dimensions?.crop).toEqual({ mode: 'manual', rect })
  })

  it('detects an automatic crop per file and drops the rectangle measured on this one', () => {
    const job = edited((j) => {
      j.dimensions!.crop = { mode: 'conservative', rect: { top: 2, bottom: 2, left: 0, right: 0 } }
    })
    const template = templateOf(job, samplePreset(), null)
    expect(template.crop_policy).toBe('detect_per_file')
    expect(template.dimensions?.crop).toEqual({ mode: 'conservative', rect: null })
  })

  it("keeps the preset's crop and policy where the draft changed them", () => {
    const rect = { top: 8, bottom: 8, left: 0, right: 0 }
    const preset = samplePreset()
    preset.crop_policy = 'fixed'
    preset.dimensions!.crop = { mode: 'auto', rect }
    const job = edited((j) => {
      j.dimensions!.crop = { mode: 'manual', rect }
    })
    const fixed = templateOf(job, preset, null)
    expect(fixed.crop_policy).toBe('fixed')
    expect(fixed.dimensions?.crop).toEqual({ mode: 'manual', rect })

    preset.crop_policy = 'detect_per_file'
    const perFile = templateOf(
      edited((j) => {
        j.dimensions!.crop = { mode: 'auto', rect: null }
      }),
      preset,
      null,
    )
    expect(perFile.crop_policy).toBe('detect_per_file')
    expect(perFile.dimensions?.crop).toEqual({ mode: 'auto', rect })
  })

  it("keeps the preset's policy without a crop", () => {
    const preset = samplePreset()
    preset.crop_policy = 'fixed'
    const job = edited((j) => {
      j.dimensions!.crop = { mode: 'none', rect: null }
      j.dimensions!.scaler = 'bicubic'
    })
    const template = templateOf(job, preset, null)
    expect(template.crop_policy).toBe('fixed')
    expect(template.dimensions?.scaler).toBe('bicubic')
  })
})

describe('the chapter name policy of the template', () => {
  it.each([
    [['Chapter 1', 'Chapter 2', 'Chapter 3'], 'source', 'generated'],
    [['Chapter 1'], 'source', 'generated'],
    [['Chapter 1', 'Chapter 2', 'Chapter 3'], 'generated', 'generated'],
    // The output gets the source's names: *To the source names* under a numbering preset.
    [null, 'generated', 'source'],
    [null, 'source', 'source'],
    // One file's own names are no preset setting: the preset's policy stays.
    [['Chapter 1', 'Chapter 2', 'End credits'], 'generated', 'generated'],
    [['Intro', 'Chapter 2'], 'source', 'source'],
    [['Chapter 2', 'Chapter 1'], 'source', 'source'],
    [['', 'Chapter 2'], 'generated', 'generated'],
    [[], 'source', 'source'],
  ] as const)('names %j over the policy %s give %s', (names, policy, expected) => {
    const preset = samplePreset()
    preset.chapter_name_policy = policy
    const job = edited((j) => {
      j.chapters = {
        enabled: true,
        names: names === null ? null : [...names],
        generate_every: null,
      }
    })
    expect(templateOf(job, preset, null).chapter_name_policy).toBe(expected)
  })
})

describe('the naming of the template', () => {
  it("is the preset's own (none: Settings → Output) without a template of the job", () => {
    expect(templateOf(sampleJob(), samplePreset(), SETTINGS_NAMING).naming).toBeNull()
  })

  it("puts the job's template and name source over the settings' naming", () => {
    const job = edited((j) => {
      Object.assign(j.output!.naming!, { template: '{title} ({year})', name_source: 'folder' })
    })
    expect(templateOf(job, samplePreset(), SETTINGS_NAMING).naming).toEqual({
      ...SETTINGS_NAMING,
      movie_template: '{title} ({year})',
      episode_template: '{title} ({year})',
      name_source: 'folder',
    })
  })

  it("puts the job's template over the preset's own naming", () => {
    const preset = samplePreset()
    preset.naming = { ...SETTINGS_NAMING, output_folder: '/presets-folder', name_source: 'file' }
    const job = edited((j) => {
      j.output!.naming!.template = '{title}'
    })
    expect(templateOf(job, preset, SETTINGS_NAMING).naming).toEqual({
      ...preset.naming,
      movie_template: '{title}',
      episode_template: '{title}',
    })
  })
})
