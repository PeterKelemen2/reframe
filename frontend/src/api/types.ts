import type { components, paths } from './schema'

/** Every schema of the OpenAPI document, by name. */
export type Schemas = components['schemas']
export type { paths }

export type AppSettings = Schemas['AppSettings']
export type AudioCodecRule = Schemas['AudioCodecRule']
export type AudioDefaults = Schemas['AudioDefaults']
export type AudioOutputTrack = Schemas['AudioOutputTrack']
export type AudioStream = Schemas['AudioStream']
export type AuthStatus = Schemas['AuthStatus']
export type CapabilitySnapshot = Schemas['CapabilitySnapshot']
export type Chapter = Schemas['Chapter']
export type ChapterSettings = Schemas['ChapterSettings']
export type DefaultsPreviewRequest = Schemas['DefaultsPreviewRequest']
export type Definitions = Schemas['Definitions']
export type EncoderState = Schemas['EncoderState']
export type EncoderStatus = Schemas['EncoderStatus']
export type EncodePlan = Schemas['EncodePlan']
export type ExternalSubtitle = Schemas['ExternalSubtitle']
export type FieldChange = Schemas['FieldChange']
export type Fix = Schemas['Fix']
export type FsListing = Schemas['FsListing']
export type FsRoot = Schemas['FsRoot']
export type JobDraft = Schemas['JobDraft']
export type JobLogChunk = Schemas['JobLogChunk']
export type JobNaming = Schemas['JobNaming']
export type JobProgress = Schemas['JobProgress']
export type JobSettings = Schemas['JobSettings']
export type JobState = Schemas['JobState']
export type JobTemplate = Schemas['JobTemplate']
export type JobType = EncodePlan['job_type']
/** One RFC 6902 operation, as the server's fixes and settings patches carry them. */
export type JsonPatchOp = Fix['patch'][number]
export type Language = Schemas['Language']
export type LanguageSettings = Schemas['LanguageSettings']
export type MediaSource = Schemas['MediaSource']
export type NameResult = Schemas['NameResult']
export type NamingOptions = Schemas['NamingOptions']
export type Preset = Schemas['Preset']
export type PresetCreateRequest = Schemas['PresetCreateRequest']
export type Problem = Schemas['Problem']
export type QueueJob = Schemas['QueueJob']
export type SettingsChange = Schemas['SettingsChange']
export type Severity = Schemas['Severity']
export type SourceEntry = Schemas['SourceEntry']
export type SubtitleDefaults = Schemas['SubtitleDefaults']
export type SubtitleOutputTrack = Schemas['SubtitleOutputTrack']
export type SubtitleStream = Schemas['SubtitleStream']
export type SystemInfo = Schemas['SystemInfo']
export type TagSettings = Schemas['TagSettings']
export type TaskInfo = Schemas['TaskInfo']
export type TrackDecision = Schemas['TrackDecision']
export type TrackDraft = Schemas['TrackDraft']
export type TrackFlags = Schemas['TrackFlags']
export type TrackMetadata = Schemas['TrackMetadata']
export type TrackRoleInfo = Schemas['TrackRoleInfo']
export type ValidationIssue = Schemas['ValidationIssue']
export type WhenDone = Schemas['WhenDoneSetting']['when_done']

/** A message of `WS /api/events`, server to client. */
export type ServerMessage = Schemas['ServerMessage']
/** A message of `WS /api/events`, client to server. */
export type ClientMessage = Schemas['ClientMessage']
/** One core event: the `event` of an `EventMessage`. */
export type ReframeEvent = Schemas['EventMessage']['event']
export type EventType = ReframeEvent['type']
export type EventOf<T extends EventType> = Extract<ReframeEvent, { type: T }>

/** The queue's run state changed (decision 0064): what the runner takes, and why. */
export type QueueProcessingEvent = EventOf<'queue.processing'>

// The results of the scan tasks (`TaskInfo.result`): `reframe.models.analysis`, which the
// OpenAPI document does not list because a task's result is untyped there.
type BitrateInfo = Schemas['BitrateInfo']

export interface BitrateScan {
  path: string
  stream_index: number
  /** `measured`, or `unknown` when the stream has no packets with a size and a time. */
  bitrate: BitrateInfo
  packets: number
  bytes: number
  duration?: number | null
}

export interface SubtitleScanTrack {
  stream_index: number
  event_count?: number | null
  /** PGS and VobSub only. */
  forced_event_count?: number | null
}

export interface SubtitleScan {
  path: string
  tracks: SubtitleScanTrack[]
}

/** EBU R128 values of one audio track; `null` where FFmpeg prints `-inf` / `inf`. */
export interface LoudnessMeasurement {
  path: string
  stream_index: number
  integrated?: number | null
  true_peak?: number | null
  lra?: number | null
  threshold?: number | null
  start?: number | null
  duration?: number | null
}

// Written by hand until S6's routes are in the schema (m6-breakdown.md, "Contracts"); then
// each becomes `Schemas['…']` with the same name.
export type ChapterFormat = 'csv' | 'ogm' | 'xml'
export type TagName = keyof TagSettings

/** `POST /api/jobs/type`: the job type the job gets, and why. */
export interface JobTypeInfo {
  job_type: JobType
  /** One sentence; two when *Edit in place* is chosen but not possible. */
  reason: string
  /** Why this job could not be edited in place; empty when it could. */
  in_place_blockers: string[]
}

/** One chapter of the output, in output time. */
export interface OutputChapter {
  /** 1-based. */
  number: number
  start: number
  end: number
  /** What is written. */
  name: string
  /** The source chapter's title; `null` for a generated chapter or a source chapter without one. */
  source_name: string | null
}

/** `POST /api/jobs/chapters`: the chapters the output gets. */
export interface OutputChapters {
  origin: 'source' | 'generated' | 'none'
  chapters: OutputChapter[]
  /** Why there are none (`origin` `none`); empty otherwise. */
  reason: string
}

export interface ChapterImportRequest {
  path: string
  /** `null`: from the file's content. */
  format?: ChapterFormat | null
}

export interface ImportedChapter {
  /** Seconds; `null` for a format without times (CSV). */
  start: number | null
  name: string
}

/** `POST /api/chapters/import`. */
export interface ChapterImport {
  format: ChapterFormat
  chapters: ImportedChapter[]
  issues: ValidationIssue[]
}

export interface ChapterExportRequest {
  job: JobSettings
  format: ChapterFormat
}

/** `POST /api/jobs/chapters/export`: the output's chapters as a file's text. */
export interface ChapterExport {
  format: ChapterFormat
  /** A suggested file name: the output's stem and the format's extension. */
  file_name: string
  content: string
}

/** `POST /api/jobs/tags`: each tag as it will be written, and the source's value. */
export interface RenderedTags {
  /** The template filled in; `null` when the tag is not set. */
  values: Record<TagName, string | null>
  /** The source file's value (what *Passthru common metadata* copies); `null` when it has none. */
  source: Record<TagName, string | null>
  /** Template errors, at `tags.<name>`. */
  issues: ValidationIssue[]
}

export interface SubtitleInspectRequest {
  path: string
}

/** `POST /api/subtitles/inspect`: an external subtitle file before it is added. */
export interface SubtitleFileInfo {
  path: string
  /** FFmpeg's codec name: `subrip`, `ass`, `ssa`, `webvtt`, `hdmv_pgs_subtitle`. */
  format: string
  bitmap: boolean
  /** From a byte order mark or valid UTF-8; `null`: not detected. */
  charset: string | null
  events: number | null
  issues: ValidationIssue[]
}
