import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { CheckRequest } from './cropCheck'

const posted = vi.fn<(answer: unknown) => void>()
let listener: ((event: MessageEvent<CheckRequest>) => Promise<void>) | null = null

beforeEach(async () => {
  vi.resetModules()
  posted.mockReset()
  vi.spyOn(globalThis, 'addEventListener').mockImplementation((_type, handler) => {
    listener = handler as never
  })
  vi.stubGlobal('postMessage', posted)
  await import('./cropCheck.worker')
})

describe('the crop check worker', () => {
  it('answers with the reason when it cannot decode a frame', async () => {
    vi.stubGlobal('createImageBitmap', async () => {
      throw new DOMException('The source image could not be decoded.', 'InvalidStateError')
    })
    const request: CheckRequest = {
      key: 'f0',
      blob: new Blob(['not a png']),
      bands: [{ x: 0, y: 0, width: 320, height: 22 }],
    }
    await listener!({ data: request } as MessageEvent<CheckRequest>).catch(() => {})
    expect(posted).toHaveBeenCalledWith({
      key: 'f0',
      error: 'InvalidStateError: The source image could not be decoded.',
    })
  })
})
