import type { JobSettings, JobTemplate, NamingOptions, Preset, Schemas } from '@/api/types'

import { sameJson } from './patch'

type CropSettings = Schemas['CropSettings']
type DimensionSettings = Schemas['DimensionSettings']

/** The crop a draft gives a job from `template`: a rectangle measured on another file is not kept. */
function draftedCrop(template: JobTemplate): CropSettings | undefined {
  const crop = template.dimensions?.crop
  if (crop?.rect == null || (crop.mode !== 'auto' && crop.mode !== 'conservative')) return crop
  return template.crop_policy === 'fixed'
    ? { mode: 'manual', rect: crop.rect }
    : { mode: crop.mode, rect: null }
}

function dimensionsOf(
  job: JobSettings,
  base: JobTemplate,
): Pick<JobTemplate, 'dimensions' | 'crop_policy'> {
  const dimensions = job.dimensions
  const crop = dimensions?.crop
  if (dimensions === undefined || crop === undefined || crop.mode === 'none') {
    return { dimensions, crop_policy: base.crop_policy }
  }
  if (crop.mode === 'manual') return { dimensions, crop_policy: 'fixed' }
  if (sameJson(crop, draftedCrop(base))) {
    const own: DimensionSettings = { ...dimensions, crop: base.dimensions?.crop }
    return { dimensions: own, crop_policy: base.crop_policy }
  }
  return {
    dimensions: { ...dimensions, crop: { mode: crop.mode, rect: null } },
    crop_policy: 'detect_per_file',
  }
}

/**
 * The name the `generated` chapter name policy gives chapter `n`. It is written into the file,
 * so it is the core's name in every language of the UI.
 */
export function numberedChapterName(n: number): string {
  return `Chapter ${n}`
}

function generatedNames(names: readonly string[]): boolean {
  return names.length > 0 && names.every((name, index) => name === numberedChapterName(index + 1))
}

function namingOf(
  job: JobSettings,
  own: NamingOptions | null,
  settingsNaming: NamingOptions | null,
): NamingOptions | null {
  const naming = job.output?.naming
  const template = naming?.template ?? null
  const source = naming?.name_source ?? null
  if (template === null && source === null) return own
  const options = { ...(own ?? settingsNaming) } as NamingOptions
  if (template !== null) {
    options.movie_template = template
    options.episode_template = template
  }
  if (source !== null) options.name_source = source
  return options
}

/**
 * The preset-level settings of `job`, drafted from `preset`: the job's source, output name,
 * chapter names and video metadata are left out, and the track rules stay the preset's.
 * `settingsNaming` is the naming of Settings → Output, which a preset without its own uses.
 */
export function templateOf(
  job: JobSettings,
  preset: Preset,
  settingsNaming: NamingOptions | null,
): JobTemplate {
  const {
    id: _id,
    name: _name,
    category: _category,
    description: _description,
    built_in: _builtIn,
    ...base
  } = preset
  const template: JobTemplate = { ...base, ...dimensionsOf(job, base) }
  if (job.output !== undefined) {
    const { path: _path, naming: _naming, edit_in_place: _inPlace, ...output } = job.output
    template.output = output
  }
  if (job.filters !== undefined) template.filters = job.filters
  if (job.video !== undefined) template.video = { ...job.video, metadata: base.video?.metadata }
  if (job.chapters !== undefined) {
    const { names, ...chapters } = job.chapters
    template.chapters = chapters
    // A preset holds no names: names other than these two cases are this file's own.
    if (names == null) template.chapter_name_policy = 'source'
    else if (generatedNames(names)) template.chapter_name_policy = 'generated'
  }
  if (job.tags !== undefined) template.tags = job.tags
  template.naming = namingOf(job, base.naming ?? null, settingsNaming)
  return template
}
