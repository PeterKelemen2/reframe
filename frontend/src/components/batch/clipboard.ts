import { shallowRef } from 'vue'

import { api, unwrap } from '@/api/client'
import type {
  JobSettings,
  JobTemplate,
  JsonPatchOp,
  NameResult,
  TemplateSection,
} from '@/api/types'
import { useEditorStore } from '@/stores/editor'
import { hasPointer } from '@/stores/settings'
import { useSourcesStore } from '@/stores/sources'

/** The sections of *Apply to group* and of copy / paste, in the order they are listed. */
export const SECTIONS: readonly TemplateSection[] = [
  'dimensions',
  'filters',
  'video',
  'audio',
  'subtitles',
  'chapters',
  'tags',
  'naming',
]

/** The template fields of each section. */
const SECTION_FIELDS: Record<TemplateSection, readonly (keyof JobTemplate)[]> = {
  dimensions: ['dimensions', 'crop_policy'],
  filters: ['filters'],
  video: ['video'],
  audio: ['audio_rules', 'audio_defaults'],
  subtitles: ['subtitle_rules', 'subtitle_defaults'],
  chapters: ['chapters', 'chapter_name_policy'],
  tags: ['tags'],
  naming: ['naming'],
}

/** One section copied from the open job, or from the edited group's template. */
export type Copied =
  | { from: 'job'; section: TemplateSection; job: JobSettings; sourceId: string }
  | { from: 'group'; section: TemplateSection; template: JobTemplate; groupId: string }

/** What was copied last; page state, as an open job is. */
export const clipboard = shallowRef<Copied | null>(null)

function put(document: unknown, path: string, value: unknown): JsonPatchOp {
  return { op: hasPointer(document, path) ? 'replace' : 'add', path, value } as JsonPatchOp
}

/** The operations that give `base` the `section` fields of `incoming`. */
export function templateSectionOps(
  base: JobTemplate,
  incoming: JobTemplate,
  section: TemplateSection,
): JsonPatchOp[] {
  return SECTION_FIELDS[section].flatMap((field): JsonPatchOp[] => {
    const path = `/${field}`
    if (incoming[field] !== undefined) return [put(base, path, incoming[field])]
    return hasPointer(base, path) ? [{ op: 'remove', path }] : []
  })
}

/** `base` with the `section` fields of `incoming`. */
function withSection(
  base: JobTemplate,
  incoming: JobTemplate,
  section: TemplateSection,
): JobTemplate {
  const fields = SECTION_FIELDS[section].map((field) => [field, incoming[field]])
  return { ...base, ...Object.fromEntries(fields) }
}

/**
 * The operations that replace `job`'s fields of `section` with those of `resolved` (the same
 * file's job resolved from `template`, named `name`). The file's own parts stay: its external
 * subtitle files, its chapter names unless `resolved` generates them, the video track's metadata,
 * its output path, a manual name and the corrected name fields.
 */
export function jobSectionOps(
  job: JobSettings,
  resolved: JobSettings,
  name: NameResult | null,
  template: JobTemplate,
  section: TemplateSection,
): JsonPatchOp[] {
  switch (section) {
    case 'dimensions':
      return [put(job, '/dimensions', resolved.dimensions)]
    case 'filters':
      return [put(job, '/filters', resolved.filters)]
    case 'video':
      return [put(job, '/video', { ...resolved.video, metadata: job.video?.metadata })]
    case 'audio':
      return [put(job, '/audio', resolved.audio ?? [])]
    case 'subtitles': {
      const external = (job.subtitles ?? []).filter((track) => typeof track.source !== 'number')
      return [put(job, '/subtitles', [...(resolved.subtitles ?? []), ...external])]
    }
    case 'chapters': {
      const names = resolved.chapters?.names ?? job.chapters?.names ?? null
      return [put(job, '/chapters', { ...resolved.chapters, names })]
    }
    case 'tags':
      return [put(job, '/tags', resolved.tags)]
    case 'naming': {
      // The resolved job is named by the template's naming options, not by its own fields.
      const naming = template.naming ?? null
      return [
        put(job, '/output/naming/template', naming === null ? null : (name?.template ?? null)),
        put(job, '/output/naming/name_source', naming?.name_source ?? null),
      ]
    }
  }
}

/**
 * *Paste* into a group: a job's section is derived into the group's template, a template's
 * section replaces the group's (the group is edited first). One undo step. Rejects with the
 * `ApiError` of a failed request (already a toast).
 */
export async function pasteIntoGroup(groupId: string, copied: Copied): Promise<void> {
  const editor = useEditorStore()
  if (copied.from === 'job') {
    await editor.mergeIntoGroup(groupId, copied.job, copied.sourceId, [copied.section])
    return
  }
  const edited = editor.target
  if (edited?.kind !== 'group' || edited.groupId !== groupId) await editor.editGroup(groupId)
  const target = editor.target
  if (target?.kind !== 'group' || target.groupId !== groupId) return
  editor.patchTemplate(templateSectionOps(target.template, copied.template, copied.section))
}

/**
 * *Paste* into a file, opened first when it is not the open job: the section as the editor's
 * template would give it to this file, in one undo step. Rejects as `pasteIntoGroup`.
 */
export async function pasteIntoFile(sourceId: string, copied: Copied): Promise<void> {
  const editor = useEditorStore()
  const opened = editor.target
  if (opened?.kind !== 'job' || opened.sourceId !== sourceId) {
    await useSourcesStore().select(sourceId)
  }
  const base = editor.currentTemplate
  const template =
    copied.from === 'job'
      ? unwrap(
          await api.POST('/api/batch/derive', {
            body: {
              job: copied.job,
              source_id: copied.sourceId,
              sections: [copied.section],
              base,
            },
          }),
        )
      : withSection(base ?? copied.template, copied.template, copied.section)
  const answer = unwrap(
    await api.POST('/api/batch/resolve', {
      body: { template, source_ids: [sourceId] },
    }),
  )
  const target = editor.target
  // Another file was opened while the requests were on their way.
  if (target?.kind !== 'job' || target.sourceId !== sourceId) return
  const row = answer.rows?.[0]
  if (row?.job == null) throw new Error('batch/resolve gave no job for an open source')
  editor.patch(jobSectionOps(target.job, row.job, row.naming ?? null, template, copied.section))
}
