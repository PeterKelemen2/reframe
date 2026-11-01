// Test media for `*.server.test.ts`. Plain JavaScript: the app's tsconfig has no Node types.
import { execFileSync } from 'node:child_process'

import { pinnedTools } from '../../../editor/testing/tools.mjs'

/**
 * An MKV with an English AC-3 5.1 track and an untitled English Opus 2.0 track. ffprobe gives no
 * bitrate for the Opus track, so a bitrate scan has to measure it; the 2.5 ms Opus packets make
 * that scan slow enough to cancel.
 */
export function makeCommentaryFile(path, seconds = 600) {
  const tools = pinnedTools()
  const ffmpeg = tools === null ? 'ffmpeg' : `${tools}/ffmpeg`
  const tone = (frequency) => `sine=frequency=${frequency}:sample_rate=48000:duration=${seconds}`
  execFileSync(
    ffmpeg,
    // oxfmt-ignore
    [
      '-hide_banner', '-loglevel', 'error', '-y',
      '-f', 'lavfi', '-i', tone(440), '-f', 'lavfi', '-i', tone(220),
      '-map', '0:a', '-map', '1:a',
      '-c:a:0', 'ac3', '-ac:a:0', '6', '-b:a:0', '192k',
      '-c:a:1', 'libopus', '-frame_duration', '2.5', '-ac:a:1', '2', '-b:a:1', '48k',
      '-metadata:s:a:0', 'language=eng', '-metadata:s:a:1', 'language=eng',
      '-disposition:a:0', 'default', '-disposition:a:1', '0',
      path,
    ],
    { stdio: ['ignore', 'ignore', 'pipe'] },
  )
}
