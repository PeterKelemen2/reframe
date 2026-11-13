// Test data as the real server sends it: testdata's multitrack.mkv and hdr10.mkv as probed (trimmed),
// and the definitions trimmed to what the Summary reads.
import { createI18n } from 'vue-i18n'

import type { Definitions, MediaSource } from '@/api/types'
import { en } from '@/i18n'

import type { FormatNumber, Translate } from './format'

/**
 * `t` and `n` with the English messages in `locale`: a test in `de` shows that a number follows
 * the app's locale (a decimal comma) rather than `toFixed`'s point.
 */
export function formatters(locale = 'en'): { t: Translate; n: FormatNumber } {
  const { global } = createI18n({ legacy: false, locale, messages: { [locale]: en } })
  return {
    t: global.t as Translate,
    n: (value, options) => global.n(value, options),
  }
}

const MULTITRACK = {
  schema_version: 1,
  ref: { path: '/media/multitrack.mkv', fingerprint: null },
  container: {
    format_name: 'matroska,webm',
    display_name: 'MKV',
    duration: 4.021,
    size: 378787,
    bitrate: 753617,
    title: 'Reframe multi-track fixture',
  },
  video: [
    {
      index: 0,
      type_index: 0,
      codec: 'h264',
      codec_long: 'H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10',
      profile: 'Constrained Baseline',
      language: null,
      title: null,
      kind: 'video',
      display_codec: 'H.264 Constrained Baseline',
      width: 320,
      height: 180,
      sar: { num: 1, den: 1 },
      dar: { num: 16, den: 9 },
      pix_fmt: 'yuv420p',
      bit_depth: 8,
      frame_rate: { num: 25, den: 1 },
      avg_frame_rate: { num: 25, den: 1 },
      vfr: false,
      field_order: 'progressive',
      rotation: 0,
      color: {
        primaries: null,
        transfer: null,
        matrix: null,
        range: 'tv',
        chroma_location: 'left',
      },
      hdr: null,
      closed_captions: false,
      bitrate: { value: null, source: 'unknown' },
      disposition: { default: true },
    },
  ],
  audio: [
    {
      index: 1,
      type_index: 0,
      codec: 'ac3',
      codec_long: 'ATSC A/52A (AC-3)',
      profile: null,
      language: 'jpn',
      title: 'Japanese 5.1',
      kind: 'audio',
      display_codec: 'AC-3',
      bit_depth: null,
      bitrate: { value: 192000, source: 'stream' },
      channels: 6,
      channel_layout: '5.1(side)',
      sample_rate: 48000,
      lossless: false,
      roles: [{ role: 'main', evidence: 'flag', detail: 'disposition default' }],
      disposition: { default: true },
    },
    {
      index: 2,
      type_index: 1,
      codec: 'aac',
      codec_long: 'AAC (Advanced Audio Coding)',
      profile: 'LC',
      language: 'eng',
      title: 'English Stereo',
      kind: 'audio',
      display_codec: 'AAC-LC',
      bit_depth: null,
      bitrate: { value: null, source: 'unknown' },
      channels: 2,
      channel_layout: 'stereo',
      sample_rate: 48000,
      lossless: false,
      roles: [
        {
          role: 'main',
          evidence: 'heuristic',
          detail: 'no commentary, description or music evidence',
        },
      ],
      disposition: {},
    },
    {
      index: 3,
      type_index: 2,
      codec: 'aac',
      codec_long: 'AAC (Advanced Audio Coding)',
      profile: 'LC',
      language: 'eng',
      title: "Director's Commentary",
      kind: 'audio',
      display_codec: 'AAC-LC',
      bit_depth: null,
      bitrate: { value: null, source: 'unknown' },
      channels: 2,
      channel_layout: 'stereo',
      sample_rate: 48000,
      lossless: false,
      roles: [{ role: 'commentary', evidence: 'flag', detail: 'disposition comment' }],
      disposition: { comment: true },
    },
  ],
  subtitles: [
    {
      index: 4,
      type_index: 0,
      codec: 'subrip',
      codec_long: 'SubRip subtitle',
      profile: null,
      language: 'eng',
      title: 'English',
      kind: 'subtitle',
      display_codec: 'SRT',
      width: null,
      height: null,
      roles: [{ role: 'main', evidence: 'flag', detail: 'disposition default' }],
      subtitle_kind: 'text',
      event_count: null,
      disposition: { default: true },
    },
    {
      index: 5,
      type_index: 1,
      codec: 'subrip',
      codec_long: 'SubRip subtitle',
      profile: null,
      language: 'eng',
      title: 'English SDH',
      kind: 'subtitle',
      display_codec: 'SRT',
      width: null,
      height: null,
      roles: [{ role: 'sdh', evidence: 'flag', detail: 'disposition hearing_impaired' }],
      subtitle_kind: 'text',
      event_count: null,
      disposition: { hearing_impaired: true },
    },
    {
      index: 6,
      type_index: 2,
      codec: 'subrip',
      codec_long: 'SubRip subtitle',
      profile: null,
      language: 'eng',
      title: 'Signs & Songs',
      kind: 'subtitle',
      display_codec: 'SRT',
      width: null,
      height: null,
      roles: [
        { role: 'forced', evidence: 'flag', detail: 'disposition forced' },
        { role: 'signs', evidence: 'title', detail: 'title contains "Signs"' },
      ],
      subtitle_kind: 'text',
      event_count: null,
      disposition: { forced: true },
    },
  ],
  chapters: [],
}

const HDR10 = {
  schema_version: 1,
  ref: { path: '/media/hdr10.mkv', fingerprint: null },
  container: {
    format_name: 'matroska,webm',
    display_name: 'MKV',
    duration: 2.0,
    size: 48309,
    bitrate: 193236,
    title: null,
  },
  video: [
    {
      index: 0,
      type_index: 0,
      codec: 'hevc',
      codec_long: 'H.265 / HEVC (High Efficiency Video Coding)',
      profile: 'Main 10',
      language: null,
      title: null,
      kind: 'video',
      display_codec: 'HEVC Main 10',
      width: 320,
      height: 180,
      sar: { num: 1, den: 1 },
      dar: { num: 16, den: 9 },
      pix_fmt: 'yuv420p10le',
      bit_depth: 10,
      frame_rate: { num: 25, den: 1 },
      avg_frame_rate: { num: 25, den: 1 },
      vfr: false,
      field_order: 'progressive',
      rotation: 0,
      color: {
        primaries: 'bt2020',
        transfer: 'smpte2084',
        matrix: 'bt2020nc',
        range: 'tv',
        chroma_location: 'left',
      },
      hdr: {
        formats: ['hdr10'],
        mastering_display: {
          red_x: 0.68,
          red_y: 0.32,
          green_x: 0.265,
          green_y: 0.69,
          blue_x: 0.15,
          blue_y: 0.06,
          white_x: 0.3127,
          white_y: 0.329,
          min_luminance: 0.0001,
          max_luminance: 1000.0,
        },
        content_light: { max_cll: 1000, max_fall: 400 },
        dolby_vision: null,
        source: 'stream',
      },
      closed_captions: false,
      bitrate: { value: 189391, source: 'mediainfo' },
      disposition: {},
    },
  ],
  audio: [],
  subtitles: [],
  chapters: [],
}

const DEFINITIONS = {
  video_encoders: {
    libx265: {
      id: 'libx265',
      label: 'x265',
      codec: 'hevc',
      codec_label: 'H.265',
      family: 'software',
      rate_control: {
        quality: {
          kind: 'crf',
          label: 'RF',
          min: 0.0,
          max: 51.0,
          step: 0.1,
          default: 22.0,
          direction: 'lower_is_better',
        },
        bitrate: { min_kbps: 100, max_kbps: 200000 },
      },
      presets: {
        choices: [
          { value: 'ultrafast', label: 'Ultrafast' },
          { value: 'superfast', label: 'Superfast' },
          { value: 'veryfast', label: 'Very fast' },
          { value: 'faster', label: 'Faster' },
          { value: 'fast', label: 'Fast' },
          { value: 'medium', label: 'Medium' },
          { value: 'slow', label: 'Slow' },
          { value: 'slower', label: 'Slower' },
          { value: 'veryslow', label: 'Very slow' },
          { value: 'placebo', label: 'Placebo' },
        ],
        default: 'medium',
      },
    },
    libx264: {
      id: 'libx264',
      label: 'x264',
      codec: 'h264',
      codec_label: 'H.264',
      family: 'software',
      rate_control: {
        quality: {
          kind: 'crf',
          label: 'RF',
          min: 0.0,
          max: 51.0,
          step: 0.1,
          default: 22.0,
          direction: 'lower_is_better',
        },
        bitrate: { min_kbps: 100, max_kbps: 200000 },
      },
      presets: {
        choices: [
          { value: 'ultrafast', label: 'Ultrafast' },
          { value: 'superfast', label: 'Superfast' },
          { value: 'veryfast', label: 'Very fast' },
          { value: 'faster', label: 'Faster' },
          { value: 'fast', label: 'Fast' },
          { value: 'medium', label: 'Medium' },
          { value: 'slow', label: 'Slow' },
          { value: 'slower', label: 'Slower' },
          { value: 'veryslow', label: 'Very slow' },
          { value: 'placebo', label: 'Placebo' },
        ],
        default: 'medium',
      },
    },
    hevc_nvenc: {
      id: 'hevc_nvenc',
      label: 'NVIDIA NVENC H.265',
      codec: 'hevc',
      codec_label: 'H.265',
      family: 'nvenc',
      rate_control: {
        quality: {
          kind: 'cq',
          label: 'CQ',
          min: 1.0,
          max: 51.0,
          step: 0.1,
          default: 27.0,
          direction: 'lower_is_better',
        },
        bitrate: { min_kbps: 100, max_kbps: 200000 },
      },
      presets: {
        choices: [
          { value: 'p1', label: 'P1 (fastest)' },
          { value: 'p2', label: 'P2 (faster)' },
          { value: 'p3', label: 'P3 (fast)' },
          { value: 'p4', label: 'P4 (medium)' },
          { value: 'p5', label: 'P5 (slow)' },
          { value: 'p6', label: 'P6 (slower)' },
          { value: 'p7', label: 'P7 (slowest)' },
        ],
        default: 'p4',
      },
    },
  },
  audio_encoders: {
    aac: {
      id: 'aac',
      label: 'AAC',
      codec: 'aac',
      lossless: false,
      bitrate: {
        by_mixdown: {
          mono: { min: 32, max: 256, default: 80 },
          stereo: { min: 64, max: 512, default: 160 },
          dpl2: { min: 64, max: 512, default: 160 },
          '5.1': { min: 192, max: 1536, default: 384 },
          '7.1': { min: 256, max: 2048, default: 512 },
        },
        allowed: null,
      },
    },
    ac3: {
      id: 'ac3',
      label: 'AC-3',
      codec: 'ac3',
      lossless: false,
      bitrate: {
        by_mixdown: {
          mono: { min: 48, max: 640, default: 96 },
          stereo: { min: 96, max: 640, default: 224 },
          dpl2: { min: 96, max: 640, default: 224 },
          '5.1': { min: 224, max: 640, default: 640 },
        },
        allowed: [
          32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 448, 512, 576, 640,
        ],
      },
    },
    flac: { id: 'flac', label: 'FLAC', codec: 'flac', lossless: true, bitrate: null },
  },
  mixdowns: {
    mono: { label: 'Mono', channels: 1 },
    stereo: { label: 'Stereo', channels: 2 },
    dpl2: { label: 'Dolby Pro Logic II', channels: 2 },
    '5.1': { label: '5.1', channels: 6 },
    '7.1': { label: '7.1', channels: 8 },
  },
  containers: {
    mkv: { id: 'mkv', label: 'Matroska (MKV)', format_flags: {} },
    mp4: { id: 'mp4', label: 'MP4', format_flags: { web_optimized: ['-movflags', '+faststart'] } },
    webm: { id: 'webm', label: 'WebM', format_flags: {} },
  },
  filters: {
    interlace_detection: {
      id: 'interlace_detection',
      label: 'Interlace detection',
      implementations: [
        {
          id: 'idet',
          label: 'idet',
          default_preset: 'default',
          presets: [
            { id: 'default', label: 'Default' },
            { id: 'permissive', label: 'Less sensitive' },
            { id: 'fast', label: 'Fast' },
            { id: 'custom', label: 'Custom' },
          ],
        },
      ],
    },
    deinterlace: {
      id: 'deinterlace',
      label: 'Deinterlace',
      implementations: [
        {
          id: 'bwdif',
          label: 'Bwdif',
          default_preset: 'default',
          presets: [
            { id: 'default', label: 'Default' },
            { id: 'bob', label: 'Bob' },
            { id: 'custom', label: 'Custom' },
          ],
        },
        {
          id: 'yadif',
          label: 'Yadif',
          default_preset: 'default',
          presets: [
            { id: 'default', label: 'Default' },
            { id: 'skip-spatial', label: 'Skip spatial check' },
            { id: 'bob', label: 'Bob' },
            { id: 'custom', label: 'Custom' },
          ],
        },
      ],
    },
    denoise: {
      id: 'denoise',
      label: 'Denoise',
      implementations: [
        {
          id: 'nlmeans',
          label: 'NLMeans',
          default_preset: 'light',
          presets: [
            { id: 'ultralight', label: 'Ultralight' },
            { id: 'light', label: 'Light' },
            { id: 'medium', label: 'Medium' },
            { id: 'strong', label: 'Strong' },
            { id: 'custom', label: 'Custom' },
          ],
        },
        {
          id: 'hqdn3d',
          label: 'HQDN3D',
          default_preset: 'light',
          presets: [
            { id: 'ultralight', label: 'Ultralight' },
            { id: 'light', label: 'Light' },
            { id: 'medium', label: 'Medium' },
            { id: 'strong', label: 'Strong' },
            { id: 'custom', label: 'Custom' },
          ],
        },
      ],
    },
    tonemap: {
      id: 'tonemap',
      label: 'HDR \u2192 SDR tone mapping',
      implementations: [
        {
          id: 'libplacebo',
          label: 'libplacebo',
          default_preset: 'default',
          presets: [
            { id: 'default', label: 'On' },
            { id: 'static', label: 'On, no peak detection' },
          ],
        },
        {
          id: 'zscale',
          label: 'zscale + tonemap',
          default_preset: 'default',
          presets: [{ id: 'default', label: 'On' }],
        },
      ],
    },
    colorspace: {
      id: 'colorspace',
      label: 'Colorspace',
      implementations: [
        {
          id: 'zscale',
          label: 'zscale',
          default_preset: 'bt709',
          presets: [
            { id: 'bt709', label: 'BT.709' },
            { id: 'bt2020', label: 'BT.2020' },
            { id: 'bt601-6-525', label: 'BT.601 SMPTE-C (NTSC)' },
            { id: 'bt601-6-625', label: 'BT.601 EBU (PAL)' },
            { id: 'custom', label: 'Custom' },
          ],
        },
        {
          id: 'libplacebo',
          label: 'libplacebo',
          default_preset: 'bt709',
          presets: [
            { id: 'bt709', label: 'BT.709' },
            { id: 'bt2020', label: 'BT.2020' },
            { id: 'bt601-6-525', label: 'BT.601 SMPTE-C (NTSC)' },
            { id: 'bt601-6-625', label: 'BT.601 EBU (PAL)' },
            { id: 'custom', label: 'Custom' },
          ],
        },
      ],
    },
  },
  filter_order: [
    'detelecine',
    'interlace_detection',
    'deinterlace',
    'denoise',
    'deblock',
    'crop',
    'custom',
    'scale',
    'tonemap',
    'colorspace',
    'sharpen',
    'chroma_smooth',
    'grayscale',
    'format',
  ],
}

export function multitrackSource(): MediaSource {
  return structuredClone(MULTITRACK) as unknown as MediaSource
}

export function hdr10Source(): MediaSource {
  return structuredClone(HDR10) as unknown as MediaSource
}

export function sampleDefinitions(): Definitions {
  return structuredClone(DEFINITIONS) as unknown as Definitions
}
