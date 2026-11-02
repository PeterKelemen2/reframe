import type {
  CapabilitySnapshot,
  Definitions,
  FilterConfig,
  FilterDef,
  JsonPatchOp,
  Schemas,
} from '@/api/types'

export type FilterImplementation = Schemas['FilterImplementation']
export type FilterPreset = Schemas['FilterPreset']

/** The filters of the definitions in the order FFmpeg applies them (crop and scale left out). */
export function filtersInOrder(definitions: Definitions | null): FilterDef[] {
  const known = definitions?.filters ?? {}
  return (definitions?.filter_order ?? []).flatMap((id) => {
    const filter = known[id]
    return filter === undefined ? [] : [filter]
  })
}

export type Availability =
  | { kind: 'available' | 'checking' }
  | { kind: 'untested'; filters: string[] }
  | { kind: 'unavailable'; filter: string; reason: string | null }

/**
 * Whether this FFmpeg build can run an implementation. `reason: null`: the filter is not in the
 * build. An untested filter (a GPU test that has not run) can still be chosen: validation warns.
 */
export function availabilityOf(
  implementation: FilterImplementation,
  capabilities: CapabilitySnapshot | null,
): Availability {
  const inBuild = capabilities?.filters ?? null
  if (capabilities === null || inBuild === null) return { kind: 'checking' }
  for (const filter of implementation.filters) {
    if (!inBuild.includes(filter)) return { kind: 'unavailable', filter, reason: null }
    const failure = capabilities.filter_failures?.[filter]
    if (failure !== undefined) return { kind: 'unavailable', filter, reason: failure }
  }
  const untested = implementation.filters.filter((filter) =>
    (capabilities.untested_filters ?? []).includes(filter),
  )
  return untested.length > 0 ? { kind: 'untested', filters: untested } : { kind: 'available' }
}

/**
 * The implementation that runs `config`. With none chosen, the server takes the first one whose
 * filters passed their test and that has the preset; an untested GPU filter does not count.
 */
export function implementationOf(
  filter: FilterDef,
  config: FilterConfig | null,
  capabilities: CapabilitySnapshot | null,
): FilterImplementation {
  const implementations = filter.implementations
  const chosen = config?.implementation
  if (chosen !== null && chosen !== undefined) {
    const found = implementations.find((implementation) => implementation.id === chosen)
    if (found !== undefined) return found
  }
  const runs = (implementation: FilterImplementation) => {
    const kind = availabilityOf(implementation, capabilities).kind
    return kind === 'available' || kind === 'checking'
  }
  const hasPreset = (implementation: FilterImplementation) =>
    config === null || implementation.presets.some((preset) => preset.id === config.preset)
  return (
    implementations.find((implementation) => runs(implementation) && hasPreset(implementation)) ??
    (implementations[0] as FilterImplementation)
  )
}

export function presetOf(
  implementation: FilterImplementation,
  config: FilterConfig,
): FilterPreset | null {
  return implementation.presets.find((preset) => preset.id === config.preset) ?? null
}

/** Turning a filter on: the default preset of the implementation the build runs. */
export function turnOnOps(
  filter: FilterDef,
  capabilities: CapabilitySnapshot | null,
): JsonPatchOp[] {
  const implementation = implementationOf(filter, null, capabilities)
  return [
    {
      op: 'add',
      path: `/filters/${filter.id}`,
      value: { preset: implementation.default_preset },
    },
  ]
}

/**
 * Another implementation: its preset and tune of the same id where it has them, else its default
 * preset and no tune. Custom parameters stay only with a custom preset.
 */
export function implementationOps(
  filter: FilterDef,
  config: FilterConfig,
  implementation: FilterImplementation,
): JsonPatchOp[] {
  const preset =
    implementation.presets.find((candidate) => candidate.id === config.preset) ??
    implementation.presets.find((candidate) => candidate.id === implementation.default_preset)
  const tune = (implementation.tunes ?? []).some((candidate) => candidate.id === config.tune)
    ? config.tune
    : null
  const value: FilterConfig = {
    ...config,
    implementation: implementation.id,
    preset: preset?.id ?? implementation.default_preset,
    tune,
    custom: preset?.custom === true ? (config.custom ?? null) : null,
  }
  return [{ op: 'replace', path: `/filters/${filter.id}`, value }]
}

/** Another preset; the custom parameters go with a custom preset. */
export function presetOps(
  filter: FilterDef,
  config: FilterConfig,
  preset: FilterPreset,
): JsonPatchOp[] {
  const base = `/filters/${filter.id}`
  const ops: JsonPatchOp[] = [{ op: 'replace', path: `${base}/preset`, value: preset.id }]
  if (!preset.custom && config.custom !== null && config.custom !== undefined) {
    ops.push({ op: 'replace', path: `${base}/custom`, value: null })
  }
  return ops
}
