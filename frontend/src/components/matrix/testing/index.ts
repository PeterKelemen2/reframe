// Test data of the matrix: the real server's `batch/resolve-run` of the anime-s01 folder with
// E01's audio and subtitles derived into the default preset (A1 → Opus 5.1 448 "Japanese 5.1"):
// E05 a near member (⚠), E11 "A2 ✗" and "S1 ≈". `fixedE11` is E11's row after its fix (A2
// optional); `pickedE05` is E05's row with A2 picked as #3 and its sub title corrected.
import type { BatchResolution, JsonPatchOp, Resolution, SourceEntry } from '@/api/types'

import anime from './anime-s01.json'

// jsdom has none; PrimeVue's virtual scroller and overlays watch sizes with one.
globalThis.ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

export function animeSources(): SourceEntry[] {
  return structuredClone(anime.sources) as unknown as SourceEntry[]
}

export function animeResolution(): BatchResolution {
  return structuredClone(anime.resolution) as unknown as BatchResolution
}

/** The source id of episode `episode` (`5` → E05's). */
export function sourceIdOf(episode: number): string {
  const code = `S01E${String(episode).padStart(2, '0')}`
  const entry = anime.sources.find((source) => source.path.includes(code))
  if (entry === undefined) throw new Error(`no ${code}`)
  return entry.id
}

/** `resolution` with `row` in place of the row of the same file. */
export function withRow(resolution: BatchResolution, row: Resolution): BatchResolution {
  return {
    ...resolution,
    rows: (resolution.rows ?? []).map((other) => (other.path === row.path ? row : other)),
  }
}

export function fixedE11(): Resolution {
  return structuredClone(anime.fixed[0]) as unknown as Resolution
}

export function pickedE05(): Resolution {
  return structuredClone(anime.picked[0]) as unknown as Resolution
}

/** The overrides that gave `pickedE05`. */
export function pickedOverrides(): Record<string, JsonPatchOp[]> {
  return structuredClone(anime.pickedOverrides) as unknown as Record<string, JsonPatchOp[]>
}
