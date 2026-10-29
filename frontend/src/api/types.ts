import type { components, paths } from './schema'

/** Every schema of the OpenAPI document, by name. */
export type Schemas = components['schemas']
export type { paths }

export type AppSettings = Schemas['AppSettings']
export type AudioOutputTrack = Schemas['AudioOutputTrack']
export type AudioStream = Schemas['AudioStream']
export type AuthStatus = Schemas['AuthStatus']
export type CapabilitySnapshot = Schemas['CapabilitySnapshot']
export type Definitions = Schemas['Definitions']
export type EncoderState = Schemas['EncoderState']
export type EncoderStatus = Schemas['EncoderStatus']
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
/** One RFC 6902 operation, as the server's fixes and settings patches carry them. */
export type JsonPatchOp = Fix['patch'][number]
export type Language = Schemas['Language']
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
export type SubtitleOutputTrack = Schemas['SubtitleOutputTrack']
export type SubtitleStream = Schemas['SubtitleStream']
export type SystemInfo = Schemas['SystemInfo']
export type TaskInfo = Schemas['TaskInfo']
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

/**
 * The queue's run state changed (decision 0042 open question 5). Written by hand until the
 * server publishes it; then it becomes `Schemas['QueueProcessingEvent']` and joins
 * `ReframeEvent`.
 */
export interface QueueProcessingEvent {
  type: 'queue.processing'
  /** The runner takes waiting jobs. */
  processing: boolean
  /** It takes only these jobs (a `start` with `job_ids`); `null`: every waiting job. */
  only: string[] | null
  /** `start` and `stop` are calls; `idle`: the jobs a `start` named have all ended. */
  reason: 'start' | 'stop' | 'idle'
}
