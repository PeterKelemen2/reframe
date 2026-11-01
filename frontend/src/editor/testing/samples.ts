// Test data shaped as the real server sends it (a draft of testdata's multitrack.mkv with the
// built-in H.265 MKV 1080p preset).
import type { JobDraft, JobSettings, Preset, ValidationIssue } from '@/api/types'

function metadata(language: string | null, name: string | null, flags: object = {}) {
  return {
    default: false,
    forced: false,
    commentary: false,
    hearing_impaired: false,
    visual_impaired: false,
    original: false,
    language,
    name,
    ...flags,
  }
}

function audio(stream: number, language: string, name: string, flags: object = {}) {
  return {
    action: 'encode',
    encoder: 'aac',
    mixdown: 'stereo',
    samplerate: null,
    bitrate: 160,
    quality: null,
    gain: 0,
    drc: 0,
    loudness: 'off',
    source_stream: stream,
    metadata: metadata(language, name, flags),
  }
}

const FILTER = { preset: 'default', tune: null, custom: null, implementation: null }
const TAGS = {
  title: null,
  actors: null,
  director: null,
  release_date: null,
  comment: null,
  genre: null,
  description: null,
  plot: null,
}
const DIMENSIONS = {
  rotate: 0,
  flip_horizontal: false,
  crop: { mode: 'auto', rect: null },
  size: { mode: 'fit', width: 1920, height: 1080 },
  allow_upscaling: false,
  pixel_aspect: 'square',
  custom_par: null,
  modulus: 2,
  scaler: 'lanczos',
}
const VIDEO = {
  passthrough: false,
  encoder: 'libx265',
  framerate: null,
  framerate_mode: 'variable',
  rate_control: { mode: 'quality', value: 22 },
  preset: 'slow',
  tune: null,
  profile: 'main10',
  level: null,
  bit_depth: 10,
  fast_decode: false,
  advanced: {},
  custom_params: 'strong-intra-smoothing=0:rect=0',
}

const JOB = {
  schema_version: 1,
  source: { path: '/media/multitrack.mkv', fingerprint: null },
  preset_id: 'h265-mkv-1080p',
  preset_name: 'H.265 MKV 1080p',
  range: { kind: 'full' },
  output: {
    container: 'mkv',
    web_optimized: false,
    align_av_start: false,
    passthru_metadata: true,
    path: '/output/multitrack.mkv',
    naming: {
      mode: 'template',
      manual_name: null,
      template: null,
      name_source: null,
      field_overrides: {},
    },
    edit_in_place: false,
  },
  dimensions: DIMENSIONS,
  filters: { interlace_detection: FILTER, deinterlace: FILTER },
  video: { ...VIDEO, metadata: metadata(null, null, { default: true }) },
  audio: [
    audio(1, 'ja', 'Japanese 5.1', { default: true }),
    audio(2, 'en', 'English Stereo'),
    audio(3, 'en', "Director's Commentary", { commentary: true }),
  ],
  subtitles: [
    {
      action: 'copy',
      convert_to: null,
      forced_only: false,
      source: 4,
      metadata: metadata('en', 'English', { default: true }),
    },
  ],
  chapters: { enabled: true, names: null, generate_every: null },
  tags: TAGS,
}

const PRESET = {
  schema_version: 1,
  output: {
    container: 'mkv',
    web_optimized: false,
    align_av_start: false,
    passthru_metadata: true,
  },
  dimensions: DIMENSIONS,
  crop_policy: 'detect_per_file',
  filters: { interlace_detection: FILTER, deinterlace: FILTER },
  video: { ...VIDEO, metadata: metadata(null, null) },
  audio_defaults: {
    selection: { languages: null, tracks_per_language: 'first' },
    codec_rules: [{ languages: null, codec: 'aac', mixdown: 'stereo', max_bitrate: 160 }],
    passthru: { allowed: [], fallback_encoder: 'aac' },
  },
  subtitle_defaults: { selection: { languages: null }, foreign_audio_search: true },
  audio_rules: [],
  subtitle_rules: [],
  chapters: { enabled: true, generate_every: null },
  chapter_name_policy: 'source',
  tags: TAGS,
  naming: null,
  id: 'h265-mkv-1080p',
  name: 'H.265 MKV 1080p',
  category: 'Matroska',
  description: '10-bit H.265 video and AAC stereo audio, in an MKV container.',
  built_in: true,
}

export function sampleJob(): JobSettings {
  return structuredClone(JOB) as unknown as JobSettings
}

export function samplePreset(): Preset {
  return structuredClone(PRESET) as unknown as Preset
}

export function issue(
  code: string,
  path: string,
  severity: ValidationIssue['severity'] = 'error',
  fixes: ValidationIssue['fixes'] = [],
): ValidationIssue {
  return { severity, code, path, message: `${code} at ${path}`, fixes }
}

export function sampleDraft(job = sampleJob(), issues: ValidationIssue[] = []): JobDraft {
  return {
    job,
    decisions: [],
    subtitle_decisions: [],
    naming: { path: job.output?.path ?? null } as unknown as JobDraft['naming'],
    issues,
    notes: [],
  }
}
