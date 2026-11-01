import { apiQuiet, unwrap } from '@/api/client'
import type { JobSettings, RenderedTags } from '@/api/types'

/** Each tag as it will be written, and the source's value. */
export async function renderedTags(job: JobSettings, signal?: AbortSignal): Promise<RenderedTags> {
  return unwrap(await apiQuiet.POST('/api/jobs/tags', { body: { job }, signal }))
}
