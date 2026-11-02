import { describe, expect, it, vi } from 'vitest'

import { problem, settle } from '@/api/testing/fakes'
import type { AppSettings, JobSettings, JobTemplate, MediaSource } from '@/api/types'
import {
  geometryOf,
  LETTERBOX,
  letterboxDetection,
  setUpCrop,
} from '@/components/dimensions/testing'
import { sampleJob } from '@/editor/testing/samples'

import { useCropStore } from './crop'
import { useEditorStore } from './editor'
import { useSettingsStore } from './settings'
import { useSourcesStore } from './sources'

function jobIn(crop: NonNullable<NonNullable<JobSettings['dimensions']>['crop']>): JobSettings {
  const job = sampleJob()
  job.dimensions = { ...job.dimensions!, crop }
  return job
}

async function opened(options: Parameters<typeof setUpCrop>[0] = {}, sourceId = 'letterbox') {
  const setup = setUpCrop(options)
  const editor = useEditorStore()
  const crop = useCropStore()
  await editor.open(sourceId)
  await settle()
  return { ...setup, editor, crop }
}

function sampled(count: number): AppSettings {
  return { preview: { sample_frames: count, cache_size_mb: 1024 } } as AppSettings
}

function detectRequests(setup: { server: { requests: { path: string; body: unknown }[] } }) {
  return setup.server.requests.filter((request) => request.path === '/api/preview/cropdetect')
}

describe('crop detection of the shown file', () => {
  it('detects the shown file and writes the automatic crop without an undo step', async () => {
    const setup = await opened()
    expect(detectRequests(setup).map((request) => request.body)).toEqual([
      { source_id: 'letterbox' },
    ])
    expect(setup.crop.detecting).toBe(true)
    expect(setup.editor.get('/dimensions/crop/rect')).toBeNull()
    setup.detections[0]!.resolve()
    await settle()
    expect(setup.crop.detecting).toBe(false)
    expect(setup.crop.detection?.auto_frames).toBe(5)
    expect(setup.editor.get('/dimensions/crop')).toEqual({
      mode: 'auto',
      rect: { top: 22, bottom: 24, left: 0, right: 0 },
    })
    expect(setup.editor.canUndo).toBe(false)
    expect(setup.crop.rect).toEqual({ top: 22, bottom: 24, left: 0, right: 0 })
  })

  it('writes the conservative crop for a job in conservative mode', async () => {
    const setup = await opened({ job: jobIn({ mode: 'conservative', rect: null }) })
    setup.detections[0]!.resolve()
    await settle()
    expect(setup.editor.get('/dimensions/crop/rect')).toEqual({
      top: 0,
      bottom: 0,
      left: 0,
      right: 0,
    })
  })

  it('writes nothing into a job that left the detected mode before the answer came', async () => {
    const setup = await opened()
    setup.editor.set('/dimensions/crop/mode', 'none')
    setup.detections[0]!.resolve()
    await settle()
    expect(setup.editor.get('/dimensions/crop')).toEqual({ mode: 'none', rect: null })
  })

  it('writes nothing into a job that has a rectangle', async () => {
    const own = { top: 2, bottom: 2, left: 0, right: 0 }
    const setup = await opened({ job: jobIn({ mode: 'auto', rect: own }) })
    setup.detections[0]!.resolve()
    await settle()
    expect(setup.editor.get('/dimensions/crop/rect')).toEqual(own)
  })

  it("writes a file's answer into that file's job only", async () => {
    const setup = await opened()
    await setup.editor.open('other')
    await settle()
    setup.detections[0]!.resolve()
    await settle()
    expect(setup.editor.get('/dimensions/crop/rect')).toBeNull()
    expect(setup.crop.detection).toBeNull()
    setup.detections[1]!.resolve()
    await settle()
    expect(setup.editor.get('/dimensions/crop/rect')).toEqual({
      top: 22,
      bottom: 24,
      left: 0,
      right: 0,
    })
  })

  it('detects each file once for the page, and again on detect()', async () => {
    const setup = await opened({ job: jobIn({ mode: 'none', rect: null }) })
    setup.detections[0]!.resolve()
    await settle()
    await setup.editor.open('other')
    await settle()
    setup.detections[1]!.resolve()
    await settle()
    await setup.editor.open('letterbox')
    await settle()
    expect(detectRequests(setup)).toHaveLength(2)
    expect(setup.crop.detection?.auto).toEqual({ top: 22, bottom: 24, left: 0, right: 0 })

    const again = setup.crop.detect()
    await settle()
    expect(detectRequests(setup)).toHaveLength(3)
    expect(detectRequests(setup)[2]!.body).toEqual({ source_id: 'letterbox' })
    setup.detections[2]!.resolve()
    await expect(again).resolves.toMatchObject({ auto_frames: 5 })
  })

  it('detects again on the new sample times when Settings → Preview changes the count', async () => {
    const setup = setUpCrop()
    const settings = useSettingsStore()
    settings.settings = sampled(10)
    const editor = useEditorStore()
    const crop = useCropStore()
    await editor.open('letterbox')
    await settle()
    setup.detections[0]!.resolve()
    await settle()
    expect(crop.detection?.samples).toHaveLength(10)

    setup.outcome.task = {
      state: 'done',
      result: { ...letterboxDetection(), samples: letterboxDetection().samples.slice(0, 5) },
    } as never
    settings.settings = sampled(5)
    await settle()
    expect(detectRequests(setup)).toHaveLength(2)
    expect(crop.detecting).toBe(true)
    expect(crop.detection).toBeNull()
    setup.detections[1]!.resolve()
    await settle()
    expect(crop.detection?.samples).toHaveLength(5)

    // The first count's detection is kept.
    settings.settings = sampled(10)
    await settle()
    expect(detectRequests(setup)).toHaveLength(2)
    expect(crop.detection?.samples).toHaveLength(10)
  })

  it("shows the task's error when the detection fails, and the problem's title when it is refused", async () => {
    const setup = await opened()
    setup.outcome.task = { state: 'failed', error: 'ffmpeg exited with 1' }
    setup.detections[0]!.resolve()
    await settle()
    expect(setup.crop.detecting).toBe(false)
    expect(setup.crop.detectionError).toBe('ffmpeg exited with 1')
    expect(setup.crop.detection).toBeNull()
    expect(setup.editor.get('/dimensions/crop/rect')).toBeNull()

    setup.server.on('POST /api/preview/cropdetect', () =>
      problem(404, 'sources.unknown', 'The source is not open'),
    )
    await expect(setup.crop.detect()).rejects.toThrow('The source is not open')
    expect(setup.crop.detectionError).toBe('The source is not open')
  })

  it("shows a group's shown file's detection and writes it nowhere", async () => {
    const setup = await opened({ job: jobIn({ mode: 'none', rect: null }) })
    const amend = vi.spyOn(setup.editor, 'amend')
    const job = jobIn({ mode: 'auto', rect: null })
    setup.editor.target = {
      kind: 'group',
      groupId: 'g1',
      sourceId: 'episode',
      job,
      template: {} as JobTemplate,
      presetId: null,
      overrides: {},
      scope: 'group',
    }
    await settle()
    expect(detectRequests(setup).at(-1)!.body).toEqual({ source_id: 'episode' })
    setup.detections.at(-1)!.resolve()
    await settle()
    expect(setup.crop.detection?.auto).toEqual({ top: 22, bottom: 24, left: 0, right: 0 })
    expect(setup.crop.rect).toEqual({ top: 22, bottom: 24, left: 0, right: 0 })
    expect(amend).not.toHaveBeenCalled()
    expect(setup.editor.get('/dimensions/crop/rect')).toBeNull()
  })
})

describe('the crop mode', () => {
  it('switches between automatic and conservative in one undo step that carries the rectangle', async () => {
    const setup = await opened()
    setup.detections[0]!.resolve()
    await settle()
    await setup.crop.setMode('conservative')
    expect(setup.editor.get('/dimensions/crop')).toEqual({
      mode: 'conservative',
      rect: { top: 0, bottom: 0, left: 0, right: 0 },
    })
    setup.editor.undo()
    expect(setup.editor.get('/dimensions/crop')).toEqual({
      mode: 'auto',
      rect: { top: 22, bottom: 24, left: 0, right: 0 },
    })
    expect(setup.editor.canUndo).toBe(false)
  })

  it('detects first when the file has no detection yet', async () => {
    const setup = await opened({ job: jobIn({ mode: 'none', rect: null }) })
    setup.outcome.task = { state: 'failed', error: 'no' }
    setup.detections[0]!.resolve()
    await settle()
    setup.outcome.task = { state: 'done', result: letterboxDetection() as never }
    const switched = setup.crop.setMode('auto')
    await settle()
    expect(setup.editor.get('/dimensions/crop/mode')).toBe('none')
    setup.detections[1]!.resolve()
    await switched
    expect(setup.editor.get('/dimensions/crop')).toEqual({
      mode: 'auto',
      rect: { top: 22, bottom: 24, left: 0, right: 0 },
    })
    setup.editor.undo()
    expect(setup.editor.get('/dimensions/crop/mode')).toBe('none')
  })

  it('drops a switch whose detection ends after another job opened', async () => {
    const setup = await opened({ job: jobIn({ mode: 'none', rect: null }) })
    setup.outcome.task = { state: 'failed', error: 'no' }
    setup.detections[0]!.resolve()
    await settle()
    const switched = setup.crop.setMode('auto')
    await settle()
    await setup.editor.open('other')
    await settle()
    setup.detections[1]!.resolve()
    await switched
    expect(setup.editor.get('/dimensions/crop/mode')).toBe('none')
  })

  it('keeps the crop chosen last when an earlier Automatic waited for the detection', async () => {
    const setup = await opened({ job: jobIn({ mode: 'none', rect: null }) })
    expect(setup.crop.detecting).toBe(true)
    const automatic = setup.crop.setMode('auto')
    await setup.crop.setMode('manual')
    setup.crop.setRect({ top: 20, bottom: 0, left: 0, right: 0 })
    setup.detections[0]!.resolve()
    await automatic
    await settle()
    expect(setup.editor.get('/dimensions/crop')).toEqual({
      mode: 'manual',
      rect: { top: 20, bottom: 0, left: 0, right: 0 },
    })
  })

  it('drops a waiting Automatic when a manual crop was typed over another manual one', async () => {
    const setup = await opened({
      job: jobIn({ mode: 'manual', rect: { top: 2, bottom: 0, left: 0, right: 0 } }),
    })
    const automatic = setup.crop.setMode('auto')
    setup.crop.setRect({ top: 20, bottom: 0, left: 0, right: 0 })
    setup.detections[0]!.resolve()
    await automatic
    expect(setup.editor.get('/dimensions/crop/mode')).toBe('manual')
  })

  it('applies a waiting Conservative when only the detected crop came in meanwhile', async () => {
    const setup = await opened()
    const conservative = setup.crop.setMode('conservative')
    setup.detections[0]!.resolve()
    await conservative
    await settle()
    expect(setup.editor.get('/dimensions/crop')).toEqual({
      mode: 'conservative',
      rect: { top: 0, bottom: 0, left: 0, right: 0 },
    })
  })

  it('keeps a crop field of a newer version when the mode or the rectangle changes', async () => {
    const setup = await opened({ job: jobIn({ mode: 'none', rect: null, newer: 7 } as never) })
    setup.detections[0]!.resolve()
    await settle()
    await setup.crop.setMode('manual')
    expect(setup.editor.get('/dimensions/crop/newer')).toBe(7)
    setup.crop.setRect({ top: 20, bottom: 0, left: 0, right: 0 })
    expect(setup.editor.get('/dimensions/crop')).toEqual({
      mode: 'manual',
      rect: { top: 20, bottom: 0, left: 0, right: 0 },
      newer: 7,
    })
  })

  it('starts manual from the current crop, and None clears it', async () => {
    const setup = await opened()
    setup.detections[0]!.resolve()
    await settle()
    await setup.crop.setMode('manual')
    expect(setup.editor.get('/dimensions/crop')).toEqual({
      mode: 'manual',
      rect: { top: 22, bottom: 24, left: 0, right: 0 },
    })
    expect(setup.crop.editable).toBe(true)
    await setup.crop.setMode('none')
    expect(setup.editor.get('/dimensions/crop')).toEqual({ mode: 'none', rect: null })
    expect(setup.crop.rect).toBeNull()
  })

  it('gives a group the mode only: its files are queued without detection', async () => {
    const setup = await opened({ job: jobIn({ mode: 'none', rect: null }) })
    setup.detections[0]!.resolve()
    await settle()
    const set = vi.spyOn(setup.editor, 'set').mockImplementation(() => {})
    setup.editor.target = {
      kind: 'group',
      groupId: 'g1',
      sourceId: 'letterbox',
      job: jobIn({ mode: 'none', rect: null }),
      template: {} as JobTemplate,
      presetId: null,
      overrides: {},
      scope: 'group',
    }
    await setup.crop.setMode('auto')
    expect(set).toHaveBeenCalledWith('/dimensions/crop', { mode: 'auto', rect: null }, undefined)
  })
})

async function manual(source = LETTERBOX) {
  const setup = await opened({
    job: jobIn({ mode: 'manual', rect: { top: 0, bottom: 0, left: 0, right: 0 } }),
    geometry: geometryOf(source),
  })
  setup.detections[0]!.resolve()
  await settle()
  return setup
}

describe('a manual crop', () => {
  it('snaps a value down to the chroma grid with a note, in one undo step', async () => {
    const setup = await manual()
    setup.crop.setRect({ top: 141, bottom: 0, left: 0, right: 0 })
    expect(setup.editor.get('/dimensions/crop')).toEqual({
      mode: 'manual',
      rect: { top: 140, bottom: 0, left: 0, right: 0 },
    })
    expect(setup.crop.snapNote).toBe('Top 141 → 140 (4:2:0 chroma grid)')
    setup.crop.setRect({ top: 140, bottom: 24, left: 0, right: 0 })
    expect(setup.crop.snapNote).toBeNull()
    setup.crop.setRect({ top: 141, bottom: 24, left: 0, right: 0 })
    await settle()
    expect(setup.crop.snapNote).toBe('Top 141 → 140 (4:2:0 chroma grid)')
    // An undo takes the explained values away, and the note with them.
    setup.editor.undo()
    await settle()
    expect(setup.crop.snapNote).toBeNull()
    setup.editor.undo()
    expect(setup.editor.get('/dimensions/crop/rect')).toEqual({
      top: 0,
      bottom: 0,
      left: 0,
      right: 0,
    })
  })

  it('names an interlaced grid and keeps the moved edge inside the picture', async () => {
    const setup = await manual({ ...LETTERBOX, interlaced: true })
    setup.crop.setRect({ top: 6, bottom: 0, left: 0, right: 0 })
    expect(setup.crop.snapNote).toBe('Top 6 → 4 (interlaced 4:2:0 chroma grid)')
    setup.crop.setRect({ top: 4, bottom: 500, left: 0, right: 0 })
    expect(setup.editor.get('/dimensions/crop/rect')).toEqual({
      top: 4,
      bottom: 172,
      left: 0,
      right: 0,
    })
    expect(setup.crop.snapNote).toBe('Bottom 500 → 172 (kept inside the picture)')
  })

  it('turns a detected mode into manual, and a coalesced run into one undo step', async () => {
    const setup = await opened()
    setup.detections[0]!.resolve()
    await settle()
    for (const left of [10, 20, 30]) {
      setup.crop.setRect({ top: 22, bottom: 24, left, right: 0 }, { coalesce: 'crop.drag.1' })
    }
    expect(setup.editor.get('/dimensions/crop')).toEqual({
      mode: 'manual',
      rect: { top: 22, bottom: 24, left: 30, right: 0 },
    })
    setup.editor.undo()
    expect(setup.editor.get('/dimensions/crop')).toEqual({
      mode: 'auto',
      rect: { top: 22, bottom: 24, left: 0, right: 0 },
    })
  })

  it('measures the picture as decoded: a 90° display matrix swaps its sides and steps', async () => {
    const setup = await manual({ ...LETTERBOX, rotation: 90, chroma_step_y: 1 })
    expect(setup.crop.sourceSize).toEqual({ width: 180, height: 320 })
    setup.crop.setRect({ top: 3, bottom: 0, left: 3, right: 0 })
    expect(setup.editor.get('/dimensions/crop/rect')).toEqual({
      top: 2,
      bottom: 0,
      left: 3,
      right: 0,
    })
  })

  it('explains no value that a handle moved', async () => {
    const setup = await manual()
    setup.crop.setRect({ top: 141, bottom: 0, left: 0, right: 0 })
    expect(setup.crop.snapNote).not.toBeNull()
    setup.crop.setRect({ top: -2, bottom: 0, left: 0, right: 0 }, { quiet: true })
    expect(setup.editor.get('/dimensions/crop/rect')).toMatchObject({ top: 0 })
    expect(setup.crop.snapNote).toBeNull()
  })
})

describe('no picture to edit', () => {
  it('turns the picture off while the job copies the video', async () => {
    const job = jobIn({ mode: 'manual', rect: { top: 22, bottom: 24, left: 0, right: 0 } })
    job.video = { ...job.video!, passthrough: true }
    const setup = await opened({ job })
    expect(setup.crop.pictureEditable).toBe(false)
    expect(setup.crop.editable).toBe(false)
    setup.editor.set('/video/passthrough', false)
    expect(setup.crop.pictureEditable).toBe(true)
    expect(setup.crop.editable).toBe(true)
  })

  it('asks no detection for a file without video, and turns the picture off', async () => {
    const setup = setUpCrop()
    useSourcesStore().entries = [
      {
        id: 'music',
        path: '/media/music.mkv',
        source: { video: [], audio: [{}] } as unknown as MediaSource,
      },
    ]
    const editor = useEditorStore()
    const crop = useCropStore()
    await editor.open('music')
    await settle()
    expect(detectRequests(setup)).toHaveLength(0)
    expect(crop.pictureEditable).toBe(false)
  })

  it('turns the picture off when jobs/geometry finds no video', async () => {
    const setup = await opened({ geometry: { source: null, geometry: null } })
    expect(setup.crop.pictureEditable).toBe(false)
  })
})
