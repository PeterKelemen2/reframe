import type { CropRect, SourceGeometry } from '@/api/types'

export type Edge = 'top' | 'bottom' | 'left' | 'right'

export const EDGES: readonly Edge[] = ['top', 'bottom', 'left', 'right']

export const NO_CROP: CropRect = { top: 0, bottom: 0, left: 0, right: 0 }

/** The picture a crop is measured on (the display matrix applied) and its chroma grid. */
export interface CropGrid {
  width: number
  height: number
  /** Pixels per chroma sample across and down; interlaced sources double the vertical one. */
  stepX: number
  stepY: number
  /** `4:2:0`, `4:2:2`, … or `3×1` for a grid without a name. */
  subsampling: string
  interlaced: boolean
}

const SUBSAMPLING: Record<string, string> = {
  '2x2': '4:2:0',
  '2x1': '4:2:2',
  '1x1': '4:4:4',
  '4x1': '4:1:1',
  '4x4': '4:1:0',
  '1x2': '4:4:0',
}

export function gridOf(source: SourceGeometry): CropGrid {
  const x = source.chroma_step_x
  const y = source.chroma_step_y * (source.interlaced ? 2 : 1)
  const subsampling =
    SUBSAMPLING[`${source.chroma_step_x}x${source.chroma_step_y}`] ??
    `${source.chroma_step_x}×${source.chroma_step_y}`
  const named = { subsampling, interlaced: source.interlaced }
  return source.rotation === 90 || source.rotation === 270
    ? { width: source.height, height: source.width, stepX: y, stepY: x, ...named }
    : { width: source.width, height: source.height, stepX: x, stepY: y, ...named }
}

interface Axis {
  size: number
  step: number
}

function axesOf(grid: CropGrid): [Axis, Axis] {
  return [
    { size: grid.width, step: grid.stepX },
    { size: grid.height, step: grid.stepY },
  ]
}

function down(value: number, step: number): number {
  return Math.floor(value / step) * step
}

/** The far edge that puts the cropped size on the grid; `null` when less than one step is left. */
function onGrid(axis: Axis, near: number, far: number): number | null {
  const remaining = axis.size - near - far
  const extra = remaining % axis.step
  return remaining - extra < axis.step ? null : far + extra
}

type Pairs = [[number, number], [number, number]]

function rectOf([[left, right], [top, bottom]]: Pairs): CropRect {
  return { top, bottom, left, right }
}

/**
 * The crop that the server's geometry applies for `requested`: every edge snapped down to the
 * grid, the right or bottom edge grown so that an off-grid frame is cropped exactly, and no crop
 * on an axis that would be removed or left with less than one step.
 */
export function appliedCrop(requested: CropRect, grid: CropGrid): CropRect {
  const axes = axesOf(grid)
  const asked: [number, number][] = [
    [Math.max(0, requested.left), Math.max(0, requested.right)],
    [Math.max(0, requested.top), Math.max(0, requested.bottom)],
  ]
  const snapped = asked.map(([near, far], index): [number, number] => {
    const axis = axes[index] as Axis
    if (near + far >= axis.size) return [0, 0]
    const next: [number, number] = [down(near, axis.step), down(far, axis.step)]
    return (next[0] > 0 || next[1] > 0) && onGrid(axis, ...next) === null ? [0, 0] : next
  })
  if (snapped.flat().every((value) => value === 0)) return { ...NO_CROP }
  const final: [number, number][] = []
  for (const [index, [near, far]] of snapped.entries()) {
    const grown = onGrid(axes[index] as Axis, near, far)
    if (grown === null) return { ...NO_CROP }
    final.push([near, grown])
  }
  return rectOf(final as Pairs)
}

/**
 * Pulls the edges in so that each axis keeps at least one grid step of picture. The edge that
 * moved since `previous` gives way, so a dragged edge stops at the other one.
 */
function keepInside(requested: CropRect, previous: CropRect, grid: CropGrid): CropRect {
  const axes = axesOf(grid)
  const pairs: [Edge, Edge][] = [
    ['left', 'right'],
    ['top', 'bottom'],
  ]
  const result = pairs.map(([nearEdge, farEdge], index): [number, number] => {
    const { size, step } = axes[index] as Axis
    const near = Math.max(0, requested[nearEdge])
    const far = Math.max(0, requested[farEdge])
    const room = Math.max(0, size - step)
    const [n, f] = [down(near, step), down(far, step)]
    if (n + f <= room) return [near, far]
    if (requested[nearEdge] !== previous[nearEdge]) {
      const kept = Math.min(f, down(room, step))
      return [Math.min(n, down(room - kept, step)), kept]
    }
    const kept = Math.min(n, down(room, step))
    return [kept, Math.min(f, down(room - kept, step))]
  })
  return rectOf(result as Pairs)
}

export interface SnapChange {
  edge: Edge
  from: number
  to: number
  /** `grid`: snapped down; `size`: grown for an off-grid frame; `inside`: kept in the picture. */
  reason: 'grid' | 'size' | 'inside'
}

/** A manual crop as the job stores it, and each value that differs from `requested`. */
export function snapCrop(
  requested: CropRect,
  previous: CropRect,
  grid: CropGrid,
): { rect: CropRect; changes: SnapChange[] } {
  const inside = keepInside(requested, previous, grid)
  const rect = appliedCrop(inside, grid)
  const changes = EDGES.filter((edge) => rect[edge] !== requested[edge]).map(
    (edge): SnapChange => ({
      edge,
      from: requested[edge],
      to: rect[edge],
      reason:
        inside[edge] !== requested[edge]
          ? 'inside'
          : rect[edge] > requested[edge]
            ? 'size'
            : 'grid',
    }),
  )
  return { rect, changes }
}
