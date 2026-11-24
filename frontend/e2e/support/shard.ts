/**
 * `E2E_SHARD=k/n` (CI): a run takes every n-th spec file and every n-th screen of the
 * accessibility gate, in every browser. Playwright's own `--shard` splits browser by browser,
 * and each browser runs its tests one at a time on its own server.
 */
import { readdirSync } from 'node:fs'

export interface Shard {
  /** 0-based. */
  index: number
  count: number
}

export function shardOf(value: string | undefined = process.env.E2E_SHARD): Shard | null {
  if (!value) return null
  const match = /^(\d+)\/(\d+)$/.exec(value)
  const index = Number(match?.[1])
  const count = Number(match?.[2])
  if (!match || count < 1 || index < 1 || index > count) {
    throw new Error(`E2E_SHARD must be k/n with 1 <= k <= n, not ${value}`)
  }
  return { index: index - 1, count }
}

/** Whether item `position` of a list is the shard's (every item without a shard). */
export function inShard(position: number, shard: Shard | null = shardOf()): boolean {
  return shard === null || position % shard.count === shard.index
}

/** It splits its screens itself, so every shard runs it. */
const SPLIT_INSIDE = 'a11y/gate.spec.ts'

/** The spec files under `dir` that `shard` runs, as paths relative to `dir`. */
export function specFiles(dir: string, shard: Shard | null = shardOf()): string[] {
  const files = readdirSync(dir, { recursive: true })
    .map((path) => String(path).replaceAll('\\', '/'))
    .filter((path) => path.endsWith('.spec.ts'))
    .toSorted()
  const others = files.filter((path) => path !== SPLIT_INSIDE)
  return [
    ...files.filter((path) => path === SPLIT_INSIDE),
    ...others.filter((_, position) => inShard(position, shard)),
  ]
}
