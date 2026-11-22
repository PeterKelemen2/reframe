import type { JsonPatchOp, Schemas } from '@/api/types'
import type { StatusTone } from '@/components/base/types'
import type { Translate } from '@/components/summary/format'

export type ToolInfo = Schemas['ToolInfo']
export type ToolName = ToolInfo['name']

/** The tools Reframe runs. One bundled FFmpeg build provides both. */
export const TOOL_NAMES: readonly ToolName[] = ['ffmpeg', 'ffprobe']

/** The bundled FFmpeg is in use and one of its two tools fails: a file is gone or damaged. */
export function bundledFfmpegDamaged(set: Record<ToolName, ToolInfo>): boolean {
  return TOOL_NAMES.some((name) => set[name].origin === 'bundled' && set[name].status !== 'found')
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

/** Where the tool's path comes from, as Settings → Tools names it. */
export function originText(tool: ToolInfo, t: Translate): string {
  switch (tool.origin) {
    case 'env':
      return t('settings.tools.origin.env', { variable: tool.env_var ?? '' })
    case 'settings':
      return t('settings.tools.origin.settings')
    case 'bundled':
      return t('settings.tools.origin.bundled')
    case 'path':
      return t('settings.tools.origin.path')
    default:
      return t('settings.tools.origin.none')
  }
}

/** Both tools are required: Reframe cannot read or encode without either. */
export function toolTone(tool: ToolInfo): StatusTone {
  return tool.status === 'found' ? 'ok' : 'error'
}
