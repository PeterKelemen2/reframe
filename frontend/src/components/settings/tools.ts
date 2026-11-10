import type { Schemas } from '@/api/types'
import type { StatusTone } from '@/components/base/types'

export type ToolInfo = Schemas['ToolInfo']
export type ToolName = ToolInfo['name']

export const TOOL_NAMES: readonly ToolName[] = ['ffmpeg', 'ffprobe', 'mkvpropedit', 'mediainfo']

/** The tools that *Use bundled FFmpeg* downloads. */
export const FFMPEG_FAMILY: readonly ToolName[] = ['ffmpeg', 'ffprobe']

/**
 * The tool's own environment variable sets it, which outranks Settings. An ffprobe found next
 * to an overridden ffmpeg has the ffmpeg's origin, but its own Settings path still wins.
 */
export function setByEnvironment(tool: ToolInfo): boolean {
  return tool.origin === 'env' && !tool.next_to_ffmpeg
}

/** A bundled FFmpeg is there (shipped with the app or downloaded before): nothing to download. */
export function hasBundledFfmpeg(set: Schemas['ToolSet'] | undefined): boolean {
  return set !== undefined && FFMPEG_FAMILY.every((name) => set[name].bundled_dir != null)
}

export function toolTone(tool: ToolInfo): StatusTone {
  if (tool.status === 'found') return 'ok'
  // MKVToolNix and MediaInfo are optional: without them some features are off.
  return FFMPEG_FAMILY.includes(tool.name) ? 'error' : 'warn'
}
