import type { JsonPatchOp, Schemas } from '@/api/types'
import type { StatusTone } from '@/components/base/types'

export type ToolInfo = Schemas['ToolInfo']
export type ToolName = ToolInfo['name']

export const TOOL_NAMES: readonly ToolName[] = ['ffmpeg', 'ffprobe', 'mkvpropedit', 'mediainfo']

/** The tools that *Use bundled FFmpeg* downloads. */
export const FFMPEG_FAMILY: readonly ToolName[] = ['ffmpeg', 'ffprobe']

/** The tools that one bundled build provides: FFmpeg's two, else the tool alone. */
export function familyOf(name: ToolName): readonly ToolName[] {
  return FFMPEG_FAMILY.includes(name) ? FFMPEG_FAMILY : [name]
}

/** Removes the Settings paths of `names` that are set: each would win over a bundled build. */
export function resetOps(
  names: readonly ToolName[],
  paths: Partial<Record<ToolName, string | null>> | undefined,
): JsonPatchOp[] {
  return names
    .filter((name) => paths?.[name])
    .map((name) => ({ op: 'replace', path: `/tools/${name}`, value: null }))
}

/**
 * The tool's own environment variable sets it, which outranks Settings. An ffprobe found next
 * to an overridden ffmpeg has the ffmpeg's origin, but its own Settings path still wins.
 */
export function setByEnvironment(tool: ToolInfo): boolean {
  return tool.origin === 'env' && !tool.next_to_ffmpeg
}

export function toolTone(tool: ToolInfo): StatusTone {
  if (tool.status === 'found') return 'ok'
  // MKVToolNix and MediaInfo are optional: without them some features are off.
  return FFMPEG_FAMILY.includes(tool.name) ? 'error' : 'warn'
}
