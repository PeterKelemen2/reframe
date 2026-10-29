// Which FFmpeg the `*.server.test.ts` files give the server. Plain JavaScript: it needs Node's
// types, which the app's tsconfig does not have.
import { existsSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const BUILDS = fileURLToPath(
  new URL('../../../../.tools/ffmpeg/default-linux-x64/', import.meta.url),
)

/**
 * The bin folder of the pinned FFmpeg: `REFRAME_TEST_TOOLS_DIR`, else the build that
 * `scripts/fetch-tools.py` put into `.tools/`; `null` when there is none (the server then finds
 * one itself).
 */
export function pinnedTools() {
  const given = process.env.REFRAME_TEST_TOOLS_DIR
  if (given) return given
  if (!existsSync(BUILDS)) return null
  for (const name of readdirSync(BUILDS)) {
    const bin = `${BUILDS}${name}/bin`
    if (existsSync(`${bin}/ffmpeg`) && existsSync(`${bin}/ffprobe`)) return bin
  }
  return null
}
