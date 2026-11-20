import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import { configureClient } from '@/api/client'
import { FakeServer } from '@/api/testing/fakes'
import type { JobSettings, JobTemplate, JsonPatchOp, NameResult } from '@/api/types'
import { applyOps } from '@/editor/patch'
import { sampleJob, samplePreset } from '@/editor/testing/samples'
import type { EditorTarget } from '@/stores/editor'
import { templateOfPreset } from '@/stores/presets'

import {
  type Copied,
  jobSectionOps,
  pasteIntoFile,
  pasteIntoGroup,
  templateSectionOps,
} from './clipboard'

// Doubles of the stores: the paste functions only call their actions.
const editor = reactive({
  target: null as EditorTarget | null,
  currentTemplate: null as JobTemplate | null,
  patch: vi.fn<(ops: JsonPatchOp[]) => void>(),
  patchTemplate: vi.fn<(ops: JsonPatchOp[]) => void>(),
  editGroup: vi.fn<(groupId: string) => Promise<void>>(),
  mergeIntoGroup: vi.fn<(...args: unknown[]) => Promise<void>>(async () => {}),
})
const sources = { select: vi.fn<(id: string) => Promise<void>>() }
vi.mock('@/stores/editor', () => ({ useEditorStore: () => editor }))
vi.mock('@/stores/sources', () => ({ useSourcesStore: () => sources }))

const TEMPLATE = templateOfPreset(samplePreset())
const X264 = { ...TEMPLATE.video!, encoder: 'libx264' }
const OPUS_RULE = {
  selector: { kind: 'audio', languages: ['ja'], nth: 0, sort: 'source_order' },
  multiple: false,
  settings: { kind: 'audio', action: 'encode', encoder: 'libopus', bitrate: 448 },
  metadata: { name_template: 'Japanese 5.1' },
  required: true,
} as unknown as NonNullable<JobTemplate['audio_rules']>[number]

function job(path = '/m/E02.mkv'): JobSettings {
  const found = sampleJob()
  found.source = { path, fingerprint: null }
  return found
}

function groupTarget(groupId: string, template: JobTemplate): EditorTarget {
  return {
    kind: 'group',
    groupId,
    sourceId: 'e01',
    job: job('/m/E01.mkv'),
    template,
    presetId: null,
    overrides: {},
    scope: 'group',
  }
}

function named(template: string): NameResult {
  return { template } as NameResult
}

let server: FakeServer

beforeEach(() => {
  server = new FakeServer()
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  editor.target = null
  editor.currentTemplate = null
  vi.clearAllMocks()
})

afterEach(() => vi.restoreAllMocks())

describe('templateSectionOps', () => {
  it('gives the base every field of the section and nothing else', () => {
    const incoming = { ...TEMPLATE, audio_rules: [OPUS_RULE], video: X264 }
    const { audio_defaults: _missing, ...base } = TEMPLATE
    const result = applyOps(base, templateSectionOps(base, incoming, 'audio')) as JobTemplate
    expect(result.audio_rules).toEqual([OPUS_RULE])
    expect(result.audio_defaults).toEqual(TEMPLATE.audio_defaults)
    expect(result.video).toEqual(TEMPLATE.video)
  })

  it('removes a field of the section that the copied template does not have', () => {
    const incoming = { ...TEMPLATE, naming: undefined }
    const base = { ...TEMPLATE, naming: { movie_template: '{title}' } } as JobTemplate
    expect(templateSectionOps(base, incoming, 'naming')).toEqual([
      { op: 'remove', path: '/naming' },
    ])
  })
})

describe('jobSectionOps', () => {
  const resolved = job()
  resolved.audio = [{ ...resolved.audio![0]!, encoder: 'libopus', bitrate: 448 }]
  resolved.subtitles = [{ ...resolved.subtitles![0]!, source: 5 }]
  resolved.video = {
    ...resolved.video!,
    encoder: 'libx264',
    metadata: { ...resolved.video!.metadata!, language: 'ja' },
  }
  resolved.chapters = { enabled: false, names: null, generate_every: null }

  function pasted(
    target: JobSettings,
    section: Parameters<typeof jobSectionOps>[4],
    template = TEMPLATE,
  ) {
    return applyOps(
      target,
      jobSectionOps(target, resolved, named('{name} E{episode:02}'), template, section),
    ) as JobSettings
  }

  it('replaces only the section’s fields of the job', () => {
    const result = pasted(job(), 'audio')
    expect(result.audio).toEqual(resolved.audio)
    expect(result.subtitles).toEqual(job().subtitles)
    expect(result.video).toEqual(job().video)
  })

  it('keeps the file’s external subtitle files after the pasted tracks', () => {
    const target = job()
    const external = { action: 'copy', source: { path: '/m/E02.en.srt' } } as never
    target.subtitles = [...target.subtitles!, external]
    expect(pasted(target, 'subtitles').subtitles).toEqual([...resolved.subtitles!, external])
  })

  it('keeps the video track’s metadata', () => {
    const result = pasted(job(), 'video')
    expect(result.video?.encoder).toBe('libx264')
    expect(result.video?.metadata).toEqual(job().video?.metadata)
  })

  it('keeps the file’s chapter names unless the template generates them', () => {
    const target = job()
    target.chapters = { enabled: true, names: ['Intro', 'Part A'], generate_every: null }
    expect(pasted(target, 'chapters').chapters).toEqual({
      enabled: false,
      names: ['Intro', 'Part A'],
      generate_every: null,
    })
    resolved.chapters = { enabled: true, names: ['Chapter 1', 'Chapter 2'], generate_every: null }
    expect(pasted(target, 'chapters').chapters?.names).toEqual(['Chapter 1', 'Chapter 2'])
  })

  it('names the file with the template that named the resolved job, and keeps its path', () => {
    const template = { ...TEMPLATE, naming: { name_source: 'folder' } } as JobTemplate
    const target = job()
    target.output!.naming!.field_overrides = { episode: '7' }
    const result = pasted(target, 'naming', template)
    expect(result.output?.naming).toEqual({
      ...target.output?.naming,
      template: '{name} E{episode:02}',
      name_source: 'folder',
    })
    expect(result.output?.path).toBe(target.output?.path)
  })

  it('takes the settings’ naming again when the template has none', () => {
    const target = job()
    target.output!.naming!.template = '{title}'
    target.output!.naming!.name_source = 'file'
    const naming = pasted(target, 'naming').output?.naming
    expect([naming?.template, naming?.name_source]).toEqual([null, null])
  })
})

describe('pasteIntoGroup', () => {
  it('derives a job’s section into the group', async () => {
    const copied: Copied = { from: 'job', section: 'audio', job: job(), sourceId: 'e02' }
    await pasteIntoGroup('g1', copied)
    expect(editor.mergeIntoGroup).toHaveBeenCalledExactlyOnceWith('g1', copied.job, 'e02', [
      'audio',
    ])
    expect(editor.patchTemplate).not.toHaveBeenCalled()
  })

  it('edits the group first, then puts a template’s section into its template in one step', async () => {
    const own = { ...TEMPLATE, audio_rules: [] }
    editor.editGroup.mockImplementation(async (groupId) => {
      editor.target = groupTarget(groupId, own)
    })
    const copied: Copied = {
      from: 'group',
      section: 'audio',
      template: { ...TEMPLATE, audio_rules: [OPUS_RULE] },
      groupId: 'g1',
    }
    await pasteIntoGroup('g2', copied)
    expect(editor.editGroup).toHaveBeenCalledExactlyOnceWith('g2')
    expect(editor.patchTemplate).toHaveBeenCalledOnce()
    const [ops] = editor.patchTemplate.mock.calls[0]!
    expect((applyOps(own, ops) as JobTemplate).audio_rules).toEqual([OPUS_RULE])
  })

  it('does not edit the group again when it is the edited one', async () => {
    editor.target = groupTarget('g1', TEMPLATE)
    await pasteIntoGroup('g1', {
      from: 'group',
      section: 'tags',
      template: TEMPLATE,
      groupId: 'g1',
    })
    expect(editor.editGroup).not.toHaveBeenCalled()
    expect(editor.patchTemplate).toHaveBeenCalledOnce()
  })
})

describe('pasteIntoFile', () => {
  const resolvedJob = job()
  resolvedJob.audio = [{ ...resolvedJob.audio![0]!, encoder: 'libopus' }]

  function answers(): void {
    server
      .on('POST /api/batch/derive', { ...TEMPLATE, audio_rules: [OPUS_RULE] })
      .on('POST /api/batch/resolve', {
        columns: [],
        rows: [{ path: '/m/E02.mkv', job: resolvedJob, naming: named('{title}'), status: 'ok' }],
      })
  }

  it('opens the file, derives the copied job’s section onto the editor’s template, resolves it on the file, and patches once', async () => {
    answers()
    const copied: Copied = {
      from: 'job',
      section: 'audio',
      job: job('/m/E01.mkv'),
      sourceId: 'e01',
    }
    sources.select.mockImplementation(async (id) => {
      editor.target = { kind: 'job', sourceId: id, job: job() }
      editor.currentTemplate = TEMPLATE
    })
    await pasteIntoFile('e02', copied)
    expect(sources.select).toHaveBeenCalledExactlyOnceWith('e02')
    const derive = server.requests.find((request) => request.path === '/api/batch/derive')
    expect(derive?.body).toEqual({
      job: copied.job,
      source_id: 'e01',
      sections: ['audio'],
      base: TEMPLATE,
    })
    const resolve = server.requests.find((request) => request.path === '/api/batch/resolve')
    expect(resolve?.body).toEqual({
      template: { ...TEMPLATE, audio_rules: [OPUS_RULE] },
      source_ids: ['e02'],
      detect_crop: false,
    })
    expect(editor.patch).toHaveBeenCalledOnce()
    const [ops] = editor.patch.mock.calls[0]!
    expect((applyOps(job(), ops) as JobSettings).audio).toEqual(resolvedJob.audio)
  })

  it('puts a group’s section into the editor’s template, without opening the open file again', async () => {
    answers()
    editor.target = { kind: 'job', sourceId: 'e02', job: job() }
    editor.currentTemplate = TEMPLATE
    const copied: Copied = {
      from: 'group',
      section: 'audio',
      template: { ...TEMPLATE, audio_rules: [OPUS_RULE], video: X264 },
      groupId: 'g1',
    }
    await pasteIntoFile('e02', copied)
    expect(sources.select).not.toHaveBeenCalled()
    expect(server.count('POST /api/batch/derive')).toBe(0)
    const resolve = server.requests.find((request) => request.path === '/api/batch/resolve')
    expect(resolve?.body).toEqual({
      template: { ...TEMPLATE, audio_rules: [OPUS_RULE] },
      source_ids: ['e02'],
      detect_crop: false,
    })
    expect(editor.patch).toHaveBeenCalledOnce()
  })

  it('changes nothing when another file was opened before the answer', async () => {
    server.on('POST /api/batch/resolve', () => {
      editor.target = { kind: 'job', sourceId: 'other', job: job('/m/other.mkv') }
      return { rows: [{ path: '/m/E02.mkv', job: resolvedJob, status: 'ok' }] }
    })
    editor.target = { kind: 'job', sourceId: 'e02', job: job() }
    editor.currentTemplate = TEMPLATE
    await pasteIntoFile('e02', {
      from: 'group',
      section: 'audio',
      template: TEMPLATE,
      groupId: 'g1',
    })
    expect(editor.patch).not.toHaveBeenCalled()
  })
})
