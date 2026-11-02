import { type CheckAnswer, type CheckRequest, losesContent, lumaVariance } from './cropCheck'

// Decoding a full-resolution frame and reading its pixels takes long enough on a 4K source to
// stall the page, so it happens here.
addEventListener('message', async (event: MessageEvent<CheckRequest>) => {
  const { key, blob, bands } = event.data
  // Without it Chromium converts the PNG's cICP colours, and the luma is no longer the frame's.
  const bitmap = await createImageBitmap(blob, { colorSpaceConversion: 'none' })
  const variances = bands.map((band) => {
    const canvas = new OffscreenCanvas(band.width, band.height)
    const context = canvas.getContext('2d', { willReadFrequently: true })!
    context.drawImage(
      bitmap,
      band.x,
      band.y,
      band.width,
      band.height,
      0,
      0,
      band.width,
      band.height,
    )
    return lumaVariance(context.getImageData(0, 0, band.width, band.height).data)
  })
  bitmap.close()
  const answer: CheckAnswer = { key, variances, lost: losesContent(variances) }
  postMessage(answer)
})
