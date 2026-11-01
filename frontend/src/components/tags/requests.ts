import { apiQuiet, unwrap } from '@/api/client'
import type { JobSettings, RenderedTags } from '@/api/types'

// The route is not in the generated schema yet: the cast stays inside this module.
type Post = (
  path: string,
  init: { body: unknown; signal?: AbortSignal },
) => Promise<{ data?: unknown; error?: unknown; response: Response }>

/** Each tag as it will be written, and the source's value (`POST /api/jobs/tags`). */
export async function renderedTags(job: JobSettings, signal?: AbortSignal): Promise<RenderedTags> {
  const send = apiQuiet.POST as unknown as Post
  return unwrap(await send('/api/jobs/tags', { body: { job }, signal })) as RenderedTags
}
