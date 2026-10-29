import type { CapabilitySnapshot, Definitions, EncoderStatus } from '@/api/types'
import {
  availabilityOf,
  type EncoderAvailability,
  type EncoderFamily,
} from '@/components/video/encoders'

/** `audio`, or the video encoder's family. */
export type EncoderKind = EncoderFamily | 'audio'

export interface EncoderRow {
  id: string
  label: string
  kind: EncoderKind | null
  availability: EncoderAvailability
  checkedAt: string | null
  /** The VAAPI render node the encoder works on. */
  device: string | null
}

/**
 * Every known encoder: the video encoders of the definitions, then the audio ones, then any
 * other the server reports, each with its status.
 */
export function encoderRows(
  definitions: Definitions | null,
  snapshot: CapabilitySnapshot | null,
): EncoderRow[] {
  const statuses = snapshot?.encoders ?? {}
  const row = (id: string, label: string, kind: EncoderKind | null): EncoderRow => {
    const status: EncoderStatus | undefined = statuses[id]
    return {
      id,
      label,
      kind,
      availability: availabilityOf(status, snapshot),
      checkedAt: status?.checked_at ?? null,
      device: status?.device ?? null,
    }
  }
  const rows = [
    ...Object.values(definitions?.video_encoders ?? {}).map((def) =>
      row(def.id, def.label, def.family),
    ),
    ...Object.values(definitions?.audio_encoders ?? {}).map((def) =>
      row(def.id, def.label, 'audio'),
    ),
  ]
  const known = new Set(rows.map((entry) => entry.id))
  for (const id of Object.keys(statuses)) if (!known.has(id)) rows.push(row(id, id, null))
  return rows
}

/** The render nodes where a VAAPI encoder works (the server lists no others), and `current`. */
export function vaapiNodes(rows: EncoderRow[], current: string | null | undefined): string[] {
  const nodes = new Set<string>()
  for (const entry of rows) {
    if (entry.kind === 'vaapi' && entry.device) nodes.add(entry.device)
  }
  if (current) nodes.add(current)
  return [...nodes].toSorted((a, b) => a.localeCompare(b, undefined, { numeric: true }))
}
