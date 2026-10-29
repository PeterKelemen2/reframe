import type { Preset } from '@/api/types'
import { samplePreset } from '@/editor/testing/samples'

/** A preset shaped as the server sends it: built-in when `built_in` is not given. */
export function preset(id: string, name: string, overrides: Partial<Preset> = {}): Preset {
  return { ...samplePreset(), id, name, ...overrides }
}

export function userPreset(id: string, name: string, overrides: Partial<Preset> = {}): Preset {
  return preset(id, name, { built_in: false, category: 'Custom', ...overrides })
}

/** The server's `GET /api/presets` for these presets. */
export function presetList(presets: Preset[], defaultId = 'h265-mkv-1080p') {
  return { presets, default_id: defaultId }
}

/** The server's answer to a name that is taken (as `reframe-server` sends it). */
export function nameConflict(name: string, free: string): Response {
  return new Response(
    JSON.stringify({
      type: 'about:blank',
      title: `A preset named “${name}” already exists.`,
      status: 409,
      detail: null,
      code: 'preset.name_conflict',
      issues: [
        {
          severity: 'error',
          code: 'preset.name_conflict',
          path: 'name',
          message: `A preset named “${name}” already exists.`,
          fixes: [
            {
              label: `Use “${free}”`,
              patch: [{ op: 'replace', path: '/name', value: free }],
              target: 'template',
            },
          ],
        },
      ],
      errors: [],
    }),
    { status: 409, headers: { 'Content-Type': 'application/problem+json' } },
  )
}
