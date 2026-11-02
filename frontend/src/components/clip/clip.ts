import { ApiError, clientBaseUrl } from '@/api/client'
import type { FrameLink } from '@/api/types'

/** The clip lengths offered, in seconds. */
export const CLIP_LENGTHS = [10, 15, 30, 60] as const

/** How many frames of a clip the frame compare shows. */
export const COMPARE_FRAMES = 5

export function reason(failure: unknown): string {
  return failure instanceof ApiError ? failure.problem.title : String(failure)
}

// The link is relative to the server, which is not the page's origin in the desktop app.
export function absoluteUrl(url: string): string {
  return new URL(url, clientBaseUrl() || globalThis.location.origin).href
}

export function absolute(frame: FrameLink): FrameLink {
  return { ...frame, url: absoluteUrl(frame.url) }
}

/** Seconds as whole milliseconds: the server keys a frame by them. */
export function millis(seconds: number): number {
  return Math.round(seconds * 1000)
}

/**
 * Evenly spaced times inside a clip of `duration` seconds, each in the middle of its part: a
 * time at the very end has no frame, and the server fails such a request.
 */
export function compareTimes(duration: number): number[] {
  return Array.from(
    { length: COMPARE_FRAMES },
    (_, at) => millis((duration * (at + 0.5)) / COMPARE_FRAMES) / 1000,
  )
}
