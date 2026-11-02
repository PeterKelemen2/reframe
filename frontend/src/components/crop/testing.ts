import { vi } from 'vitest'
import { reactive } from 'vue'

import type { CropDetection, CropRect, FrameLink } from '@/api/types'
import type { PictureSize } from '@/stores/crop'
import type { SourcePoint } from '@/stores/preview'

/** The `letterbox` fixture: 320×180, letterbox frames at 0.2–1.8 s, pillarbox at 2.2–3.8 s. */
export const SIZE: PictureSize = { width: 320, height: 180 }
export const LETTERBOX: CropRect = { top: 22, bottom: 24, left: 0, right: 0 }
export const PILLARBOX: CropRect = { top: 0, bottom: 0, left: 40, right: 40 }
const TIMES = [0.2, 0.6, 1, 1.4, 1.8, 2.2, 2.6, 3, 3.4, 3.8]

export function strip(signature = 'a'): FrameLink[] {
  return TIMES.map((timestamp, i) => ({
    key: `f${i}`,
    kind: 'source',
    timestamp,
    width: SIZE.width,
    height: SIZE.height,
    cached: true,
    url: `/api/preview/frames/f${i}.png?exp=1&sig=${signature}`,
  }))
}

export function detection(): CropDetection {
  return {
    samples: TIMES.map((timestamp, i) => ({ timestamp, crop: i < 5 ? LETTERBOX : PILLARBOX })),
    auto: LETTERBOX,
    auto_frames: 5,
    conservative: { top: 0, bottom: 0, left: 0, right: 0 },
    notes: [],
  }
}

/** The preview store's members these components use, as plain state. */
export function fakePreview() {
  return reactive({
    strip: [] as FrameLink[],
    index: null as number | null,
    current: null as FrameLink | null,
    pointer: null as SourcePoint | null,
    select: vi.fn<(at: number) => void>(),
    step: vi.fn<(delta: 1 | -1) => void>(),
    reload: vi.fn<() => Promise<void>>(async () => {}),
  })
}

/** The crop store's members these components use, as plain state. */
export function fakeCrop() {
  return reactive({
    rect: null as CropRect | null,
    sourceSize: null as PictureSize | null,
    editable: false,
    detection: null as CropDetection | null,
  })
}

/** A decoded frame as far as the components see it. */
export function fakeBitmap(): ImageBitmap {
  return { width: SIZE.width, height: SIZE.height, close: vi.fn() } as unknown as ImageBitmap
}
