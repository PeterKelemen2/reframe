import type { Definitions, Schemas } from '@/api/types'

type FilterSettings = Schemas['FilterSettings']

export interface FilterChip {
  id: string
  /** The filter's name from the definitions. */
  label: string
  /** The preset's name; `null`: the filter is off. */
  value: string | null
}

/** Shown even when off: what a viewer of the output notices first. */
const ALWAYS_SHOWN = new Set(['deinterlace', 'colorspace', 'tonemap'])

/**
 * One chip per filter that is on, plus Deinterlace, Colorspace and Tone mapping when off, in the
 * filter chain's order. A filter is on when the job has it.
 */
export function filterChips(
  filters: FilterSettings | undefined,
  definitions: Definitions | null,
): FilterChip[] {
  const set = filters ?? {}
  const known = definitions?.filters ?? {}
  const order = (definitions?.filter_order ?? []).filter((id) => Object.hasOwn(known, id))
  for (const id of [...ALWAYS_SHOWN, ...Object.keys(set)]) if (!order.includes(id)) order.push(id)

  const chips: FilterChip[] = []
  for (const id of order) {
    const config = set[id]
    if (config === undefined && !ALWAYS_SHOWN.has(id)) continue
    const filter = known[id]
    const label = filter?.label ?? id
    if (config === undefined) {
      chips.push({ id, label, value: null })
      continue
    }
    const implementations = filter?.implementations ?? []
    const implementation =
      implementations.find((candidate) => candidate.id === config.implementation) ??
      implementations[0]
    const preset = implementation?.presets.find((candidate) => candidate.id === config.preset)
    chips.push({ id, label, value: preset?.label ?? config.preset })
  }
  return chips
}
