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
