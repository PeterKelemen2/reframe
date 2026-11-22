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
export type BatchGroup = Schemas['BatchGroup']
export type BatchGrouping = Schemas['BatchGrouping']
export type BatchResolution = Schemas['BatchResolution']
export type BatchRun = Schemas['BatchRun']
export type BatchRunRequest = Schemas['BatchRunRequest']
export type CapabilitySnapshot = Schemas['CapabilitySnapshot']
export type Chapter = Schemas['Chapter']
export type ChapterSettings = Schemas['ChapterSettings']
export type ColorInfo = Schemas['ColorInfo']
export type CropRect = Schemas['CropRect']
export type CropSettings = Schemas['CropSettings']
export type DefaultsPreviewRequest = Schemas['DefaultsPreviewRequest']
export type Definitions = Schemas['Definitions']
export type DimensionSettings = Schemas['DimensionSettings']
export type EncoderOption = Schemas['EncoderOption']
export type EncoderState = Schemas['EncoderState']
export type EncoderStatus = Schemas['EncoderStatus']
export type EncodePlan = Schemas['EncodePlan']
export type ExternalSubtitle = Schemas['ExternalSubtitle']
export type FieldChange = Schemas['FieldChange']
export type FilterConfig = Schemas['FilterConfig']
export type FilterDef = Schemas['FilterDef']
export type FilterSettings = Schemas['FilterSettings']
export type Fix = Schemas['Fix']
/** One PNG frame: a signed URL that works for a few minutes. */
export type FrameLink = Schemas['FrameLink']
export type Frames = Schemas['Frames']
export type Geometry = Schemas['Geometry']
export type HdrInfo = Schemas['HdrInfo']
export type FsListing = Schemas['FsListing']
export type FsRoot = Schemas['FsRoot']
export type GroupMember = Schemas['GroupMember']
export type JobDraft = Schemas['JobDraft']
/** `jobs/geometry`: the source picture and the geometry the command builder uses. */
export type JobGeometry = Schemas['JobGeometry']
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
export type MatchLevel = Schemas['BatchGroupRequest']['level']
export type MatrixColumn = Schemas['MatrixColumn']
export type MediaSource = Schemas['MediaSource']
export type NameResult = Schemas['NameResult']
export type NamingOptions = Schemas['NamingOptions']
export type Preset = Schemas['Preset']
export type PreviewSettings = Schemas['PreviewSettings']
export type PresetCreateRequest = Schemas['PresetCreateRequest']
export type Problem = Schemas['Problem']
export type QueueJob = Schemas['QueueJob']
/** One row of the resolution matrix: the template applied to one file. */
export type Resolution = Schemas['Resolution']
export type SettingsChange = Schemas['SettingsChange']
export type Severity = Schemas['Severity']
export type SourceEntry = Schemas['SourceEntry']
export type SourceGeometry = Schemas['SourceGeometry']
export type SubtitleDefaults = Schemas['SubtitleDefaults']
export type SubtitleOutputTrack = Schemas['SubtitleOutputTrack']
export type SubtitleStream = Schemas['SubtitleStream']
export type SystemInfo = Schemas['SystemInfo']
export type TagSettings = Schemas['TagSettings']
export type TaskInfo = Schemas['TaskInfo']
/** A section of *Apply to group* and of copy / paste. */
export type TemplateSection = Schemas['BatchDeriveRequest']['sections'][number]
export type TrackDecision = Schemas['TrackDecision']
export type TrackDraft = Schemas['TrackDraft']
export type TrackFlags = Schemas['TrackFlags']
export type TrackMatch = Schemas['TrackMatch']
export type TrackMetadata = Schemas['TrackMetadata']
export type TrackRoleInfo = Schemas['TrackRoleInfo']
export type ValidationIssue = Schemas['ValidationIssue']
export type VideoStream = Schemas['VideoStream']
export type WhenDone = Schemas['WhenDoneSetting']['when_done']

/** A message of `WS /api/events`, server to client. */
export type ServerMessage = Schemas['ServerMessage']
/** A message of `WS /api/events`, client to server. */
export type ClientMessage = Schemas['ClientMessage']
/** One core event: the `event` of an `EventMessage`. */
export type ReframeEvent = Schemas['EventMessage']['event']
export type EventType = ReframeEvent['type']
export type EventOf<T extends EventType> = Extract<ReframeEvent, { type: T }>

/**
 * The runner's state changed: which jobs it takes, and why. Clients need not infer it from the
 * jobs.
 */
export type QueueProcessingEvent = EventOf<'queue.processing'>

// The scan results (`TaskInfo.result`) are written by hand: the OpenAPI document leaves a
// task's result untyped.
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

/** `cropdetect` on one sample frame; `crop` is `null` where the frame gave no result (black). */
export interface CropSample {
  timestamp: number
  crop?: CropRect | null
}

/** The result of a `cropdetect` task, on the frame strip's sample times. */
export interface CropDetection {
  samples: CropSample[]
  /** The most common result: automatic crop. */
  auto: CropRect
  /** Samples that gave `auto`: `Detected … on 9 of 10 frames`. */
  auto_frames: number
  /** Only what is black on every sample: conservative crop. */
  conservative: CropRect
  notes: string[]
}

/** The result of a `preview_clip` task (its `path` is the server's; the client uses `id`). */
export interface PreviewClip {
  id: string
  /** Seconds from the start of the source: the clip's frame at `t` is the source's at `start + t`. */
  start: number
  duration: number
  container: string
  /** `h264`, `hevc`, `av1`, …, or `null` for a job without video. */
  video_codec?: string | null
  size: number
}

export type ChapterExport = Schemas['ChapterExport']
export type ChapterExportRequest = Schemas['ChapterExportRequest']
export type ChapterFormat = ChapterExport['format']
export type ChapterImport = Schemas['ChapterImport']
export type ChapterImportRequest = Schemas['ChapterImportRequest']
export type ImportedChapter = Schemas['ImportedChapter']
export type JobTypeInfo = Schemas['JobTypeInfo']
export type OutputChapter = Schemas['OutputChapter']
export type OutputChapters = Schemas['OutputChapters']
export type RenderedTags = Schemas['RenderedTags']
export type SubtitleFileInfo = Schemas['SubtitleFileInfo']
export type SubtitleInspectRequest = Schemas['SubtitleInspectRequest']
export type TagName = keyof TagSettings
export type TagValues = Schemas['TagValues']
