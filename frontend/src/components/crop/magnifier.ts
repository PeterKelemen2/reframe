import type { CropRect } from '@/api/types'
import type { Edge } from '@/components/dimensions/grid'
import type { PictureSize } from '@/stores/crop'
import type { SourcePoint } from '@/stores/preview'

import type { Box } from './cropCheck'

export type MagnifierZoom = 2 | 4 | 8

export const ZOOMS: readonly MagnifierZoom[] = [2, 4, 8]

/** The left and right strips' length and every strip's depth, in CSS pixels. */
export const STRIP_LENGTH = 384
export const STRIP_DEPTH = 96
export const LOUPE_SIZE = 160
export const LOUPE_ZOOM = 4

const TINT = 'rgba(255, 0, 90, 0.35)'
const LINE = '#ffd400'
const GRID = 'rgba(128, 128, 128, 0.6)'

/** Source pixels shown on a canvas: `box` (it may reach past the picture) at `zoom`. */
export interface View {
  box: Box
  zoom: number
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high)
}

export function isHorizontal(edge: Edge): boolean {
  return edge === 'top' || edge === 'bottom'
}

/** Where the crop line of `edge` is: the first kept row or column, or the first removed one. */
function boundary(edge: Edge, rect: CropRect, size: PictureSize): number {
  switch (edge) {
    case 'top':
      return rect.top
    case 'bottom':
      return size.height - rect.bottom
    case 'left':
      return rect.left
    case 'right':
      return size.width - rect.right
  }
}

/** The longest strip within `room` CSS pixels that shows whole source pixels at every zoom. */
export function fittedLength(room: number): number {
  const step = ZOOMS.at(-1)!
  return Math.max(0, Math.floor(room / step) * step)
}

/**
 * The source pixels of an edge strip `length` CSS pixels long: the crop line in the middle of its
 * depth, and along the line around `centre` (the pointer's column or row) and inside the picture.
 */
export function stripView(
  edge: Edge,
  rect: CropRect,
  size: PictureSize,
  zoom: MagnifierZoom,
  centre: number | null,
  length: number,
): View {
  const across = boundary(edge, rect, size) - STRIP_DEPTH / 2 / zoom
  const depth = STRIP_DEPTH / zoom
  const extent = isHorizontal(edge) ? size.width : size.height
  const along = Math.min(length / zoom, extent)
  const start = clamp(Math.round((centre ?? extent / 2) - along / 2), 0, extent - along)
  const box = isHorizontal(edge)
    ? { x: start, y: across, width: along, height: depth }
    : { x: across, y: start, width: depth, height: along }
  return { box, zoom }
}

/** The loupe's source pixels, with the middle of the pixel under the pointer in its centre. */
export function loupeView(point: SourcePoint): View {
  const span = LOUPE_SIZE / LOUPE_ZOOM
  return {
    box: {
      x: Math.floor(point.x) + 0.5 - span / 2,
      y: Math.floor(point.y) + 0.5 - span / 2,
      width: span,
      height: span,
    },
    zoom: LOUPE_ZOOM,
  }
}

/** The first and last row (top and bottom strips) or column of the picture that a strip shows. */
export function stripRange(edge: Edge, view: View, size: PictureSize): [number, number] {
  const { box } = view
  const [start, count, extent] = isHorizontal(edge)
    ? [box.y, box.height, size.height]
    : [box.x, box.width, size.width]
  return [Math.max(start, 0), Math.min(start + count, extent) - 1]
}

/** Where things go on the canvas of `view`, in CSS pixels. */
export interface ViewLayout {
  width: number
  height: number
  /** The part of the picture inside the view; `null` when the view is off the picture. */
  source: Box | null
  /** Where `source` is drawn. */
  target: Box
  /** The picture's area on the canvas (it may reach past the canvas). */
  picture: Box
  /** The kept rectangle on the canvas: the crop lines are its edges, outside it is tinted. */
  crop: Box
}

function onCanvas(box: Box, view: View): Box {
  return {
    x: (box.x - view.box.x) * view.zoom,
    y: (box.y - view.box.y) * view.zoom,
    width: box.width * view.zoom,
    height: box.height * view.zoom,
  }
}

export function viewLayout(view: View, rect: CropRect, size: PictureSize): ViewLayout {
  const { box } = view
  const x = Math.max(box.x, 0)
  const y = Math.max(box.y, 0)
  const right = Math.min(box.x + box.width, size.width)
  const bottom = Math.min(box.y + box.height, size.height)
  const source = right > x && bottom > y ? { x, y, width: right - x, height: bottom - y } : null
  const crop = {
    x: rect.left,
    y: rect.top,
    width: size.width - rect.left - rect.right,
    height: size.height - rect.top - rect.bottom,
  }
  return {
    width: box.width * view.zoom,
    height: box.height * view.zoom,
    source,
    target: onCanvas(source ?? { x: 0, y: 0, width: 0, height: 0 }, view),
    picture: onCanvas({ x: 0, y: 0, ...size }, view),
    crop: onCanvas(crop, view),
  }
}

/**
 * Sizes `canvas` for `width` × `height` CSS pixels at the device pixel ratio and returns its
 * context in CSS pixels. Setting the size clears the canvas, so it is set only when it changes.
 */
export function prepareCanvas(
  canvas: HTMLCanvasElement,
  width: number,
  height: number,
): CanvasRenderingContext2D {
  const ratio = globalThis.devicePixelRatio || 1
  const pixelsWide = Math.round(width * ratio)
  const pixelsHigh = Math.round(height * ratio)
  if (canvas.width !== pixelsWide) canvas.width = pixelsWide
  if (canvas.height !== pixelsHigh) canvas.height = pixelsHigh
  const context = canvas.getContext('2d')!
  context.setTransform(ratio, 0, 0, ratio, 0, 0)
  return context
}

/** The view's pixels without smoothing, the removed part tinted, the crop lines and the grid. */
export function drawView(
  context: CanvasRenderingContext2D,
  image: ImageBitmap,
  layout: ViewLayout,
  zoom: number,
  grid: boolean,
): void {
  const { source, target, picture, crop } = layout
  context.clearRect(0, 0, layout.width, layout.height)
  if (source === null) return
  context.imageSmoothingEnabled = false
  context.drawImage(
    image,
    source.x,
    source.y,
    source.width,
    source.height,
    target.x,
    target.y,
    target.width,
    target.height,
  )
  if (grid) {
    context.fillStyle = GRID
    for (let x = target.x + zoom; x < target.x + target.width; x += zoom) {
      context.fillRect(x, target.y, 1, target.height)
    }
    for (let y = target.y + zoom; y < target.y + target.height; y += zoom) {
      context.fillRect(target.x, y, target.width, 1)
    }
  }
  context.fillStyle = TINT
  context.beginPath()
  context.rect(picture.x, picture.y, picture.width, picture.height)
  context.rect(crop.x, crop.y, crop.width, crop.height)
  context.fill('evenodd')
  // Two pixels wide, one on each side of the boundary between the last removed and the first
  // kept pixel.
  context.strokeStyle = LINE
  context.lineWidth = 2
  context.strokeRect(crop.x, crop.y, crop.width, crop.height)
}
