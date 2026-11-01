// Media files the `*.server.test.ts` files make with FFmpeg. Plain JavaScript: it needs Node's
// types, which the app's tsconfig does not have.
import { execFileSync } from 'node:child_process'

import { pinnedTools } from '../../../editor/testing/tools.mjs'

/**
 * Writes an MKV with an English AC-3 5.1 track (its bitrate in the stream) and an untitled
 * English Opus 2.0 track at 48 kb/s that ffprobe gives no bitrate for. The Opus packets are
 * 2.5 ms long, so a bitrate scan of it takes about a second per ten minutes.
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
