import type { JobSettings, RenderedTags, TagName, ValidationIssue } from '@/api/types'

import { TAG_NAMES } from './tags'

function each(value: (name: TagName) => string | null): Record<TagName, string | null> {
  return Object.fromEntries(TAG_NAMES.map((name) => [name, value(name)])) as Record<
    TagName,
    string | null
  >
}

/** A `jobs/tags` answer: `{name}` filled in as the server would for multitrack.mkv. */
export function renderedFor(job: JobSettings, issues: ValidationIssue[] = []): RenderedTags {
  return {
    values: each((name) => job.tags?.[name]?.replaceAll('{name}', 'multitrack') ?? null),
    source: each((name) => (name === 'title' ? 'Source title' : null)),
    issues,
  }
}
